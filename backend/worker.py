"""Crash-resumable background worker. Jobs are leased in MongoDB; every provider submission is persisted
before polling so a restart resumes polling instead of re-submitting (no duplicate provider jobs)."""
import asyncio
import base64
import json
import logging
import math
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from core import db, now, now_dt, Cfg, get_object, store_media, StorageError, audit
from ledger import settle, release, credits_for_seconds
from providers import GujaratiTTS, get_avatar_provider, ProviderError, download
from emailer import send_video_ready
import render

log = logging.getLogger("anchorai.worker")
ACTIVE = ["queued", "validating", "generating", "retrieving", "rendering"]
LEASE_SECONDS = 90
STAGE_TIMEOUT = 25 * 60
MAX_CONCURRENT = 2
_running = set()


class Cancelled(Exception):
    pass


class JobFail(Exception):
    def __init__(self, code, message, retry_safe=True):
        super().__init__(message)
        self.code, self.message, self.retry_safe = code, message, retry_safe


async def _set(job_id, status=None, msg=None, **fields):
    upd = {"updated_at": now(), **fields}
    ops = {"$set": upd}
    if status:
        upd["status"] = status
        ops["$push"] = {"events": {"at": now(), "status": status, "msg": msg or status}}
    await db.jobs.update_one({"id": job_id}, ops)
    if status:
        j = await db.jobs.find_one({"id": job_id}, {"project_id": 1})
        await db.projects.update_one({"id": j["project_id"]}, {"$set": {"status": status, "updated_at": now()}})


async def _heartbeat(job_id):
    j = await db.jobs.find_one_and_update({"id": job_id}, {"$set": {
        "lease_until": now_dt() + timedelta(seconds=LEASE_SECONDS)}}, projection={"_id": 0})
    if j.get("cancel_requested"):
        raise Cancelled()
    if j.get("anchor_blocked"):
        raise JobFail("consent_revoked" if j["anchor_blocked"] == "consent_revoked" else "anchor_deleted",
                      "The anchor's consent was revoked or the portrait was deleted before generation started. "
                      "Credits were released.", retry_safe=False)
    return j


async def finish_cancel(job):
    sub = (job.get("avatar") or {}).get("submission") or (job.get("tts") or {}).get("submission")
    if sub and not (job.get("avatar") or {}).get("done"):
        await asyncio.to_thread(get_avatar_provider().cancel_job, sub)
    await release(job, "Released: job cancelled by user")
    await _set(job["id"], "cancelled", "Cancelled by user", completed_at=now(), retry_safe=True, lease_until=None)
    await audit(job["workspace_id"], job["owner_id"], "job.cancelled", job["id"])


async def _poll(adapter, sub, job_id, stage, field):
    start = time.time()
    while True:
        await _heartbeat(job_id)
        st = await asyncio.to_thread(adapter.get_status, sub, stage)
        await db.jobs.update_one({"id": job_id}, {"$set": {"provider_status": f"{stage}: {st}",
                                                           f"{field}.status": st}})
        if st in ("COMPLETED", "OK"):
            return await asyncio.to_thread(adapter.retrieve_output, sub, stage)
        if time.time() - start > STAGE_TIMEOUT:
            await asyncio.to_thread(adapter.cancel_job, sub)
            raise JobFail("provider_timeout", f"The AI provider took too long on {stage}. Credits were released; "
                          "you can retry.")
        await asyncio.sleep(4)


async def stage_validate(job):
    a = await db.anchors.find_one({"id": job["anchor_id"]}, {"_id": 0})
    if not a or a["status"] != "active" or a["consent_status"] != "granted":
        raise JobFail("consent_missing", "The anchor is no longer authorized (consent revoked or portrait deleted).",
                      retry_safe=False)
    if not await db.consents.find_one({"id": job["consent_id"], "revoked": False}):
        raise JobFail("consent_missing", "Consent record missing or revoked.", retry_safe=False)
    GujaratiTTS().validate_configuration()
    get_avatar_provider().validate_configuration()
    return a


async def stage_tts(job, work: Path):
    tts = GujaratiTTS()
    t = job.get("tts") or {}
    if t.get("done"):
        return
    snap = job["snapshot"]
    cues, spoken_cues, spoken = render.build_spoken(snap["script"], snap.get("pronunciation"))
    if not t.get("submission"):
        sub = await asyncio.to_thread(tts.create, spoken, snap["voice"])
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"tts.submission": sub, "tts.request_id": sub["request_id"],
                                                              "provider_status": "narration: IN_QUEUE"}})
        t["submission"] = sub
    result = await _poll(tts, t["submission"], job["id"], "Gujarati narration", "tts")
    audio_url, alignment = tts.parse(result)
    audio = await asyncio.to_thread(download, audio_url, 50 * 1024 * 1024)
    p = work / "narration.mp3"
    p.write_bytes(audio)
    info = render.probe(p)
    if not info["has_audio"] or not info["duration"]:
        raise JobFail("provider_bad_response", "The narration audio returned by the provider is invalid.")
    if info["duration"] > Cfg.MAX_NARRATION_SECONDS + 8:
        raise JobFail("script_too_long", f"Narration is {info['duration']:.0f}s, above the "
                      f"{Cfg.MAX_NARRATION_SECONDS}s limit. Shorten the script.", retry_safe=False)
    asset = await store_media(job["workspace_id"], "tts_audio", audio, "audio/mpeg", "mp3", job["project_id"],
                              job["id"], {"duration": info["duration"]})
    timed, method = render.time_cues(cues, spoken_cues, alignment, info["duration"])
    await db.jobs.update_one({"id": job["id"]}, {"$set": {
        "tts.done": True, "tts.audio_key": asset["storage_key"], "tts.remote_url": audio_url,
        "tts.remote_at": time.time(), "tts.duration": info["duration"], "tts.cues": timed, "tts.timing": method}})


async def stage_avatar(job, anchor):
    av = job.get("avatar") or {}
    if av.get("done"):
        return
    prov = get_avatar_provider()
    if not av.get("submission"):
        img = await asyncio.to_thread(get_object, anchor["provider_storage_key"])
        data_url = "data:image/jpeg;base64," + base64.b64encode(img).decode()
        audio_url = job["tts"].get("remote_url")
        if not audio_url or time.time() - job["tts"].get("remote_at", 0) > 12 * 3600:
            audio = await asyncio.to_thread(get_object, job["tts"]["audio_key"])
            audio_url = "data:audio/mpeg;base64," + base64.b64encode(audio).decode()
        sub = await asyncio.to_thread(prov.create, data_url, audio_url)
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"avatar.submission": sub,
                                                              "avatar.request_id": sub["request_id"],
                                                              "provider_job_id": sub["request_id"],
                                                              "provider_status": "anchor video: IN_QUEUE"}})
        av["submission"] = sub
    result = await _poll(prov, av["submission"], job["id"], "talking-anchor video", "avatar")
    url, duration = prov.parse(result)
    await db.jobs.update_one({"id": job["id"]}, {"$set": {"avatar.done": True, "avatar.remote_url": url,
                                                          "avatar.duration": duration}})


async def stage_retrieve(job, work: Path):
    av = job["avatar"]
    if av.get("raw_key"):
        (work / "anchor.mp4").write_bytes(await asyncio.to_thread(get_object, av["raw_key"]))
        return
    data = await asyncio.to_thread(download, av["remote_url"])
    p = work / "anchor.mp4"
    p.write_bytes(data)
    info = render.probe(p)
    if not info["duration"] or not info["width"] or info["duration"] < 1:
        raise JobFail("provider_bad_response", "The generated anchor video is invalid or empty.")
    if not await asyncio.to_thread(render.decodes, p):
        raise JobFail("provider_bad_response", "The generated anchor video could not be decoded.")
    asset = await store_media(job["workspace_id"], "avatar_raw", data, "video/mp4", "mp4", job["project_id"],
                              job["id"], {"duration": info["duration"], "dimensions": [info["width"], info["height"]]})
    await db.jobs.update_one({"id": job["id"]}, {"$set": {"avatar.raw_key": asset["storage_key"],
                                                          "avatar.probe": info}})


async def stage_render(job, work: Path):
    snap = job["snapshot"]
    narr = work / "narration.mp3"
    if not narr.exists():
        narr.write_bytes(await asyncio.to_thread(get_object, job["tts"]["audio_key"]))
    logo = None
    if snap.get("logo_storage_key"):
        try:
            logo = await asyncio.to_thread(get_object, snap["logo_storage_key"])
        except Exception:
            logo = None
    cues = job["tts"]["cues"]
    render.validate_cues(cues, job["tts"]["duration"])
    final, info, offset = await asyncio.to_thread(render.render_final, work / "r", work / "anchor.mp4", narr,
                                                  snap["branding"], cues, snap["subtitle_style"], logo)
    data = final.read_bytes()
    seconds = job["tts"]["duration"]
    credits = credits_for_seconds(seconds)
    asset = await store_media(job["workspace_id"], "final_video", data, "video/mp4", "mp4", job["project_id"],
                              job["id"], {"duration": info["duration"], "width": info["width"],
                                          "height": info["height"], "cues": cues, "cue_offset": offset,
                                          "subtitle_timing": job["tts"]["timing"], "credits_charged": credits,
                                          "dimensions": [info["width"], info["height"]]})
    back = await asyncio.to_thread(get_object, asset["storage_key"])
    if len(back) != len(data):
        await db.media_assets.update_one({"id": asset["id"]}, {"$set": {"is_deleted": True}})
        raise JobFail("storage_failed", "The final video could not be verified in storage. Credits were released.")
    return asset, info, credits


async def process(job_id):
    work = Path(tempfile.mkdtemp(prefix=f"job-{job_id[:8]}-"))
    try:
        job = await _heartbeat(job_id)
        if job["status"] == "queued":
            await _set(job_id, "validating", "Checking consent, script and provider", started_at=now())
        anchor = await stage_validate(job)
        job = await _heartbeat(job_id)
        if job["status"] in ("validating", "generating"):
            if job["status"] == "validating":
                await _set(job_id, "generating", "Generating Gujarati narration and talking anchor")
            await stage_tts(await _heartbeat(job_id), work)
            await stage_avatar(await _heartbeat(job_id), anchor)
            await _set(job_id, "retrieving", "Retrieving generated anchor video")
        job = await _heartbeat(job_id)
        if job["status"] in ("retrieving", "rendering"):
            await stage_retrieve(job, work)
            if job["status"] == "retrieving":
                await _set(job_id, "rendering", "Rendering Breaking News graphics and subtitles")
            job = await _heartbeat(job_id)
            asset, info, credits = await stage_render(job, work)
            job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
            await settle(job, credits)
            await _set(job_id, "completed", f"Completed: {info['duration']:.1f}s 1920×1080 MP4", completed_at=now(),
                       lease_until=None, **{"final.video_asset_id": asset["id"], "final.duration": info["duration"],
                                            "final.width": info["width"], "final.height": info["height"],
                                            "final.file_size": info["file_size"],
                                            "final.subtitle_timing": job["tts"]["timing"]})
            await audit(job["workspace_id"], job["owner_id"], "job.completed", job_id, {"credits": credits})
            user = await db.users.find_one({"id": job["owner_id"]}, {"_id": 0})
            if user:
                await send_video_ready(user["email"], user["name"], job["project_name"], f"{Cfg.APP_URL}/app/library")
    except Cancelled:
        await finish_cancel(await db.jobs.find_one({"id": job_id}, {"_id": 0}))
    except (JobFail, ProviderError, render.RenderError, StorageError) as e:
        code = getattr(e, "code", None) or ("render_failed" if isinstance(e, render.RenderError) else "storage_failed")
        msg = getattr(e, "message", None) or str(e)
        safe = getattr(e, "retry_safe", True)
        await _fail(job_id, code, msg, safe)
    except Exception:
        log.exception("Unexpected worker error for job %s", job_id)
        await _fail(job_id, "internal_error", "An unexpected error occurred. Credits were released; you can retry.", True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def _fail(job_id, code, msg, retry_safe):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if job["status"] in ("completed", "failed", "cancelled"):
        return
    log.warning("job %s failed: %s", job_id, code)
    await release(job, f"Released: job failed ({code})")
    await _set(job_id, "failed", msg, error_code=code, error_message=msg, retry_safe=retry_safe,
               completed_at=now(), lease_until=None)
    await audit(job["workspace_id"], job["owner_id"], "job.failed", job_id, {"code": code})


async def _claim():
    return await db.jobs.find_one_and_update(
        {"status": {"$in": ACTIVE}, "id": {"$nin": list(_running)},
         "$or": [{"lease_until": None}, {"lease_until": {"$lt": now_dt()}}]},
        {"$set": {"lease_until": now_dt() + timedelta(seconds=LEASE_SECONDS)}}, sort=[("created_at", 1)],
        projection={"_id": 0, "id": 1})


async def _run(job_id):
    try:
        await process(job_id)
    finally:
        _running.discard(job_id)


async def worker_loop():
    log.info("worker started")
    while True:
        try:
            while len(_running) < MAX_CONCURRENT:
                j = await _claim()
                if not j:
                    break
                _running.add(j["id"])
                asyncio.create_task(_run(j["id"]))
        except Exception:
            log.exception("worker loop error")
        await asyncio.sleep(3)
