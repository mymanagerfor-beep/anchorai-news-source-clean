import re
import asyncio
import math
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel, Field

from core import db, now, uid, Cfg, audit, get_object, rate_limit, store_media
from auth import get_ctx
from anchors import file_url
from ledger import reserve, reserve_amount, credits_for_seconds, InsufficientCredits, release
from providers import GUJARATI_VOICES, VOICE_IDS, GujaratiTTS, ProviderError, get_avatar_provider, download
import render

router = APIRouter(prefix="/api/v1")
ACTIVE = ["queued", "validating", "generating", "retrieving", "rendering"]
ALLOWED_CHARS = re.compile(r"[\u0A80-\u0AFFA-Za-z0-9\s.,!?;:'\"()\-–—…%₹/।॥&+@#]")


class Pron(BaseModel):
    word: str = Field(max_length=40)
    say: str = Field(max_length=60)


class Branding(BaseModel):
    branding_enabled: bool = True
    channel_name: str = Field("", max_length=60)
    primary_color: str = Field("#DC2626", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str = Field("#0F172A", pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_corner: str = Field("top-right", pattern="^(top-left|top-right)$")
    banner_text: str = Field("BREAKING NEWS", max_length=30)
    ticker_enabled: bool = True
    ticker_label: str = Field("તાજા સમાચાર", max_length=24)
    ticker_text: str = Field("", max_length=600)
    show_date: bool = False
    intro_enabled: bool = False
    outro_enabled: bool = False


class SubStyle(BaseModel):
    enabled: bool = True
    size: int = Field(42, ge=28, le=64)
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    background: str = Field("box", pattern="^(box|outline)$")
    position: str = Field("bottom", pattern="^(bottom|top)$")


class ProjectIn(BaseModel):
    name: str = Field("Untitled bulletin", min_length=1, max_length=120)
    anchor_id: Optional[str] = None
    channel_id: Optional[str] = None
    script: str = Field("", max_length=5000)
    headline: str = Field("", max_length=120)
    location: str = Field("", max_length=40)
    pronunciation: List[Pron] = Field(default_factory=list, max_length=30)
    voice: str = "Sarah"
    template: str = Field("breaking_news", pattern="^breaking_news$")
    branding: Branding = Branding()
    subtitle_style: SubStyle = SubStyle()


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    anchor_id: Optional[str] = None
    channel_id: Optional[str] = None
    script: Optional[str] = Field(None, max_length=5000)
    headline: Optional[str] = Field(None, max_length=120)
    location: Optional[str] = Field(None, max_length=40)
    pronunciation: Optional[List[Pron]] = None
    voice: Optional[str] = None
    branding: Optional[Branding] = None
    subtitle_style: Optional[SubStyle] = None


def analyze_script(script, pairs):
    _, _, spoken = render.build_spoken(script or "", pairs)
    chars = len(script or "")
    words = len((script or "").split())
    est = round(len(spoken) / Cfg.GU_CHARS_PER_SECOND, 1) if spoken else 0
    bad = sorted({c for c in (script or "") if not ALLOWED_CHARS.match(c)})
    gu = sum(1 for c in (script or "") if "\u0A80" <= c <= "\u0AFF")
    letters = sum(1 for c in (script or "") if c.isalpha() or "\u0A80" <= c <= "\u0AFF")
    issues = []
    if not (script or "").strip():
        issues.append("Script is empty.")
    elif letters and gu / letters < 0.5:
        issues.append("Script must be mainly Gujarati (ગુજરાતી) text.")
    if bad:
        issues.append(f"Unsupported characters: {' '.join(bad[:10])}")
    if est > Cfg.MAX_NARRATION_SECONDS:
        issues.append(f"Estimated narration {est}s exceeds the {Cfg.MAX_NARRATION_SECONDS}s limit. Shorten the script.")
    return {"characters": chars, "words": words, "estimated_seconds": est, "spoken_characters": len(spoken),
            "estimated_credits": credits_for_seconds(est) if est else 0,
            "reserve_credits": reserve_amount(est) if est else 0, "max_seconds": Cfg.MAX_NARRATION_SECONDS,
            "unsupported_characters": bad, "issues": issues, "valid": not issues}


async def get_project(ctx, pid):
    p = await db.projects.find_one({"id": pid, "workspace_id": ctx["ws_id"], "deleted": {"$ne": True}}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Project not found")
    return p


async def check_refs(ctx, data):
    if data.get("anchor_id") and not await db.anchors.find_one({"id": data["anchor_id"], "workspace_id": ctx["ws_id"]}):
        raise HTTPException(404, "Anchor not found")
    if data.get("channel_id") and not await db.channels.find_one({"id": data["channel_id"],
                                                                   "workspace_id": ctx["ws_id"]}):
        raise HTTPException(404, "Channel not found")
    if data.get("voice") and data["voice"] not in VOICE_IDS:
        raise HTTPException(400, "Voice is not verified for Gujarati")


@router.get("/voices")
async def voices():
    return {"language": "gu-IN", "provider": "ElevenLabs v3 via fal.ai", "speed_supported": False,
            "pronunciation_notes": "Word replacements applied to the spoken text only",
            "voices": GUJARATI_VOICES}


PREVIEW_TEXT = "નમસ્તે, આ AnchorAI News ની ગુજરાતી અવાજની ઝલક છે. આજના મુખ્ય સમાચાર જોઈએ."


@router.get("/voices/{voice}/preview")
async def voice_preview(voice: str, ctx=Depends(get_ctx)):
    if voice not in VOICE_IDS:
        raise HTTPException(404, "Unknown voice")
    cached = await db.voice_previews.find_one({"voice": voice}, {"_id": 0})
    if not cached:
        rate_limit(f"vprev:{ctx['ws_id']}", 6, 3600)
        tts = GujaratiTTS()
        try:
            def gen():
                import time
                sub = tts.create(PREVIEW_TEXT, voice)
                for _ in range(60):
                    if tts.get_status(sub, "voice preview") in ("COMPLETED", "OK"):
                        url, _ = tts.parse(tts.retrieve_output(sub, "voice preview"))
                        return download(url, 5 * 1024 * 1024)
                    time.sleep(2)
                raise ProviderError("provider_timeout", "Voice preview timed out.")
            audio = await asyncio.to_thread(gen)
        except ProviderError as e:
            raise HTTPException(503, e.message)
        asset = await store_media("system", "voice_preview", audio, "audio/mpeg", "mp3", meta={"voice": voice})
        cached = {"voice": voice, "storage_key": asset["storage_key"], "created_at": now()}
        await db.voice_previews.update_one({"voice": voice}, {"$setOnInsert": cached}, upsert=True)
    return {"voice": voice, "text": PREVIEW_TEXT, "url": file_url(cached["storage_key"], "audio/mpeg")}


@router.post("/scripts/analyze")
async def analyze(body: ProjectPatch):
    return analyze_script(body.script or "", [p.model_dump() for p in body.pronunciation or []])


def project_out(p, job=None):
    p = {k: v for k, v in p.items() if k != "_id"}
    p["analysis"] = analyze_script(p.get("script", ""), p.get("pronunciation", []))
    if job:
        p["latest_job"] = job_out(job)
    return p


@router.post("/projects")
async def create_project(body: ProjectIn, ctx=Depends(get_ctx)):
    data = body.model_dump()
    await check_refs(ctx, data)
    p = {"id": uid(), "workspace_id": ctx["ws_id"], "owner_id": ctx["user"]["id"], **data, "language": "gu-IN",
         "aspect_ratio": "16:9", "resolution": "1920x1080", "output_format": "mp4", "status": "draft",
         "created_at": now(), "updated_at": now()}
    await db.projects.insert_one(p)
    return project_out(p)


@router.get("/projects")
async def list_projects(ctx=Depends(get_ctx)):
    items = await db.projects.find({"workspace_id": ctx["ws_id"], "deleted": {"$ne": True}}, {"_id": 0}) \
        .sort("updated_at", -1).to_list(200)
    return {"items": [project_out(p) for p in items]}


@router.get("/projects/{pid}")
async def project_detail(pid: str, ctx=Depends(get_ctx)):
    p = await get_project(ctx, pid)
    job = await db.jobs.find_one({"project_id": pid}, {"_id": 0}, sort=[("created_at", -1)])
    return project_out(p, job)


@router.patch("/projects/{pid}")
async def patch_project(pid: str, body: ProjectPatch, ctx=Depends(get_ctx)):
    p = await get_project(ctx, pid)
    upd = body.model_dump(exclude_none=True)
    await check_refs(ctx, upd)
    if p["status"] in ACTIVE and set(upd) - {"name"}:
        raise HTTPException(409, "This project is generating. Only the name can be changed now.")
    upd["updated_at"] = now()
    await db.projects.update_one({"id": pid}, {"$set": upd})
    return project_out(await get_project(ctx, pid))


@router.delete("/projects/{pid}")
async def delete_project(pid: str, ctx=Depends(get_ctx)):
    p = await get_project(ctx, pid)
    if p["status"] in ACTIVE:
        raise HTTPException(409, "Cancel the running job before deleting this project")
    await db.projects.update_one({"id": pid}, {"$set": {"deleted": True, "deleted_at": now()}})
    await db.media_assets.update_many({"project_id": pid}, {"$set": {"is_deleted": True,
                                                                    "retention_status": "pending_purge"}})
    await audit(ctx["ws_id"], ctx["user"]["id"], "project.deleted", pid)
    return {"ok": True}


async def resolve_channel(ctx, p):
    if not p.get("channel_id"):
        return None
    return await db.channels.find_one({"id": p["channel_id"], "workspace_id": ctx["ws_id"]}, {"_id": 0})


@router.post("/projects/{pid}/generate")
async def generate(pid: str, request: Request, ctx=Depends(get_ctx),
                   idempotency_key: str = Header(..., alias="Idempotency-Key")):
    rate_limit(f"gen:{ctx['ws_id']}", 10, 3600)
    if not re.fullmatch(r"[A-Za-z0-9\-]{16,64}", idempotency_key):
        raise HTTPException(400, "Invalid Idempotency-Key")
    existing = await db.jobs.find_one({"workspace_id": ctx["ws_id"], "idempotency_key": idempotency_key}, {"_id": 0})
    if existing:
        return job_out(existing)
    body = await request.json() if await request.body() else {}
    if not body.get("consent_confirmed"):
        raise HTTPException(400, "Confirm permission to animate this person before generating")
    p = await get_project(ctx, pid)
    if not ctx["user"].get("email_verified"):
        raise HTTPException(403, "Verify your email address before generating videos")
    if await db.jobs.find_one({"project_id": pid, "status": {"$in": ACTIVE}}):
        raise HTTPException(409, "This project already has a job in progress")
    a = await db.anchors.find_one({"id": p.get("anchor_id"), "workspace_id": ctx["ws_id"]}, {"_id": 0})
    if not a or a["status"] != "active" or a["consent_status"] != "granted":
        raise HTTPException(400, "Select an anchor with active consent")
    consent = await db.consents.find_one({"id": a["consent_id"], "revoked": False})
    if not consent:
        raise HTTPException(400, "Consent for this anchor is missing or revoked")
    info = analyze_script(p["script"], p.get("pronunciation", []))
    if not info["valid"]:
        raise HTTPException(400, " ".join(info["issues"]))
    if p.get("voice") not in VOICE_IDS:
        raise HTTPException(400, "Unsupported Gujarati voice")
    try:
        GujaratiTTS().validate_configuration()
        get_avatar_provider().validate_configuration()
    except ProviderError as e:
        raise HTTPException(503, e.message)
    channel = await resolve_channel(ctx, p)
    branding = {**p["branding"], "headline": p.get("headline", ""), "location": p.get("location", "")}
    if channel and not branding.get("channel_name"):
        branding["channel_name"] = channel["name"]
    job_id = uid()
    amount = info["reserve_credits"]
    try:
        await reserve(ctx["ws_id"], ctx["user"]["id"], job_id, amount, f"job:{job_id}:a1:reserve")
    except InsufficientCredits:
        raise HTTPException(402, f"Insufficient credits: this video needs up to {amount} credits. Buy a credit pack "
                                 "to continue.")
    job = {"id": job_id, "project_id": pid, "workspace_id": ctx["ws_id"], "owner_id": ctx["user"]["id"],
           "anchor_id": a["id"], "anchor_name": a["display_name"], "project_name": p["name"],
           "template": p["template"], "provider": get_avatar_provider().name, "tts_provider": GujaratiTTS.name,
           "provider_job_id": None, "provider_status": None, "idempotency_key": idempotency_key, "status": "queued",
           "reserved_credits": amount, "estimated_credits": info["estimated_credits"], "final_credits": None,
           "reservation_state": "held", "error_code": None, "error_message": None, "retry_safe": False,
           "attempt_count": 1, "cancel_requested": False, "consent_id": a["consent_id"],
           "snapshot": {"script": p["script"], "pronunciation": p.get("pronunciation", []), "voice": p["voice"],
                        "branding": branding, "subtitle_style": p["subtitle_style"],
                        "logo_storage_key": (channel or {}).get("logo_storage_key"),
                        "estimated_seconds": info["estimated_seconds"]},
           "tts": {}, "avatar": {}, "final": {}, "events": [{"at": now(), "status": "queued", "msg": "Job submitted"}],
           "lease_until": None, "created_at": now(), "updated_at": now(), "started_at": None, "completed_at": None}
    await db.jobs.insert_one(job)
    await db.projects.update_one({"id": pid}, {"$set": {"status": "queued", "updated_at": now()}})
    await audit(ctx["ws_id"], ctx["user"]["id"], "job.submitted", job_id, {"reserved": amount})
    return job_out(job)


def job_out(j):
    j = {k: v for k, v in j.items() if k not in ("_id", "lease_until")}
    j.pop("snapshot", None)
    for k in ("tts", "avatar"):
        s = j.get(k) or {}
        j[k] = {kk: s.get(kk) for kk in ("request_id", "status", "duration", "done")}
    final = j.get("final") or {}
    j["final"] = {kk: final.get(kk) for kk in ("video_asset_id", "duration", "width", "height", "file_size",
                                               "subtitle_timing")}
    return j


async def get_job(ctx, jid):
    j = await db.jobs.find_one({"id": jid, "workspace_id": ctx["ws_id"]}, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@router.get("/jobs")
async def list_jobs(ctx=Depends(get_ctx), status: Optional[str] = None):
    q = {"workspace_id": ctx["ws_id"]}
    if status:
        q["status"] = status
    items = await db.jobs.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": [job_out(j) for j in items]}


@router.get("/jobs/{jid}")
async def job_detail(jid: str, ctx=Depends(get_ctx)):
    j = await get_job(ctx, jid)
    out = job_out(j)
    out["script"] = j["snapshot"]["script"]
    out["settings"] = {k: v for k, v in j["snapshot"].items() if k not in ("script", "logo_storage_key")}
    return out


@router.post("/jobs/{jid}/cancel")
async def cancel_job(jid: str, ctx=Depends(get_ctx)):
    j = await get_job(ctx, jid)
    if j["status"] not in ACTIVE:
        raise HTTPException(409, f"A {j['status']} job cannot be cancelled")
    await db.jobs.update_one({"id": jid}, {"$set": {"cancel_requested": True}})
    if j["status"] == "queued":
        from worker import finish_cancel
        await finish_cancel(await get_job(ctx, jid))
    await audit(ctx["ws_id"], ctx["user"]["id"], "job.cancel_requested", jid)
    return job_out(await get_job(ctx, jid))


@router.post("/jobs/{jid}/retry")
async def retry_job(jid: str, ctx=Depends(get_ctx)):
    j = await get_job(ctx, jid)
    if j["status"] not in ("failed", "cancelled") or not j.get("retry_safe"):
        raise HTTPException(409, "This job cannot be retried safely")
    a = await db.anchors.find_one({"id": j["anchor_id"]}, {"_id": 0})
    if not a or a["status"] != "active" or a["consent_status"] != "granted":
        raise HTTPException(400, "The anchor is no longer authorized for use")
    if await db.jobs.find_one({"project_id": j["project_id"], "status": {"$in": ACTIVE}}):
        raise HTTPException(409, "This project already has a job in progress")
    attempt = j["attempt_count"] + 1
    try:
        await reserve(ctx["ws_id"], ctx["user"]["id"], jid, j["reserved_credits"], f"job:{jid}:a{attempt}:reserve")
    except InsufficientCredits:
        raise HTTPException(402, "Insufficient credits to retry this job")
    res = await db.jobs.find_one_and_update(
        {"id": jid, "status": j["status"], "attempt_count": j["attempt_count"]},
        {"$set": {"status": "queued", "attempt_count": attempt, "reservation_state": "held", "error_code": None,
                  "error_message": None, "cancel_requested": False, "anchor_blocked": None, "final_credits": None,
                  "retry_safe": False, "updated_at": now()},
         "$push": {"events": {"at": now(), "status": "queued", "msg": f"Retry attempt {attempt}"}}})
    if not res:
        raise HTTPException(409, "Job state changed; refresh and try again")
    await db.projects.update_one({"id": j["project_id"]}, {"$set": {"status": "queued"}})
    await audit(ctx["ws_id"], ctx["user"]["id"], "job.retried", jid, {"attempt": attempt})
    return job_out(await get_job(ctx, jid))


def video_out(v, project=None):
    out = {k: v.get(k) for k in ("id", "project_id", "job_id", "duration", "width", "height", "file_size",
                                 "mime_type", "created_at", "credits_charged", "subtitle_timing")}
    if project:
        out["project_name"] = project["name"]
        out["headline"] = project.get("headline")
    return out


@router.get("/videos")
async def list_videos(ctx=Depends(get_ctx)):
    vids = await db.media_assets.find({"workspace_id": ctx["ws_id"], "asset_type": "final_video",
                                       "is_deleted": False}, {"_id": 0}).sort("created_at", -1).to_list(200)
    projects = {p["id"]: p for p in await db.projects.find({"id": {"$in": [v["project_id"] for v in vids]},
                                                             "deleted": {"$ne": True}}, {"_id": 0}).to_list(200)}
    return {"items": [video_out(v, projects[v["project_id"]]) for v in vids if v["project_id"] in projects]}


@router.get("/projects/{pid}/videos")
async def project_videos(pid: str, ctx=Depends(get_ctx)):
    p = await get_project(ctx, pid)
    vids = await db.media_assets.find({"workspace_id": ctx["ws_id"], "project_id": pid, "asset_type": "final_video",
                                       "is_deleted": False}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"items": [video_out(v, p) for v in vids]}


async def get_video(ctx, vid):
    v = await db.media_assets.find_one({"id": vid, "workspace_id": ctx["ws_id"], "asset_type": "final_video",
                                        "is_deleted": False}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Video not found")
    return v


@router.post("/videos/{vid}/download-url")
async def video_download_url(vid: str, ctx=Depends(get_ctx), inline: bool = False):
    v = await get_video(ctx, vid)
    p = await db.projects.find_one({"id": v["project_id"]}, {"_id": 0, "name": 1})
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", (p or {}).get("name", "video"))[:60] or "video"
    minutes = 30 if inline else 5
    url = file_url(v["storage_key"], "video/mp4", minutes, None if inline else f"{safe}.mp4")
    await audit(ctx["ws_id"], ctx["user"]["id"], "video.download_url", vid, {"inline": inline})
    return {"url": url, "expires_in_seconds": minutes * 60}


@router.get("/videos/{vid}/subtitles.{fmt}")
async def subtitles(vid: str, fmt: str, ctx=Depends(get_ctx)):
    v = await get_video(ctx, vid)
    if fmt not in ("srt", "vtt"):
        raise HTTPException(404, "Unknown format")
    cues, offset = v.get("cues") or [], v.get("cue_offset", 0.0)
    body = render.to_srt(cues, offset) if fmt == "srt" else render.to_vtt(cues, offset)
    return PlainTextResponse(body, media_type="text/vtt" if fmt == "vtt" else "application/x-subrip",
                             headers={"Content-Disposition": f'attachment; filename="subtitles.{fmt}"'})


@router.delete("/videos/{vid}")
async def delete_video(vid: str, ctx=Depends(get_ctx)):
    await get_video(ctx, vid)
    await db.media_assets.update_one({"id": vid}, {"$set": {"is_deleted": True, "retention_status": "pending_purge",
                                                            "deleted_at": now()}})
    await audit(ctx["ws_id"], ctx["user"]["id"], "video.deleted", vid)
    return {"ok": True}


class PreviewIn(BaseModel):
    anchor_id: Optional[str] = None
    channel_id: Optional[str] = None
    headline: str = Field("", max_length=120)
    location: str = Field("", max_length=40)
    sample_subtitle: str = Field("", max_length=140)
    branding: Branding = Branding()
    subtitle_style: SubStyle = SubStyle()


@router.post("/compose/preview-frame")
async def preview_frame(body: PreviewIn, ctx=Depends(get_ctx)):
    rate_limit(f"pframe:{ctx['user']['id']}", 30, 600)
    portrait = logo = None
    if body.anchor_id:
        a = await db.anchors.find_one({"id": body.anchor_id, "workspace_id": ctx["ws_id"], "status": {"$ne": "deleted"}})
        if a:
            portrait = await asyncio.to_thread(get_object, a["provider_storage_key"])
    b = {**body.branding.model_dump(), "headline": body.headline, "location": body.location}
    if body.channel_id:
        c = await db.channels.find_one({"id": body.channel_id, "workspace_id": ctx["ws_id"]})
        if c and c.get("logo_storage_key"):
            logo = await asyncio.to_thread(get_object, c["logo_storage_key"])
        if c and not b["channel_name"]:
            b["channel_name"] = c["name"]
    jpg = await asyncio.to_thread(render.preview_frame, b, body.subtitle_style.model_dump(), body.sample_subtitle,
                                  logo, portrait)
    return Response(jpg, media_type="image/jpeg", headers={"X-Preview": "static-composition-not-generated-video"})


@router.get("/dashboard")
async def dashboard(ctx=Depends(get_ctx)):
    ws = ctx["ws_id"]
    counts = {s: 0 for s in ["draft"] + ACTIVE + ["completed", "failed", "cancelled"]}
    async for r in db.jobs.aggregate([{"$match": {"workspace_id": ws}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[r["_id"]] = r["n"]
    videos = await db.media_assets.count_documents({"workspace_id": ws, "asset_type": "final_video"})
    recent = await db.projects.find({"workspace_id": ws, "deleted": {"$ne": True}}, {"_id": 0}).sort("updated_at", -1) \
        .to_list(6)
    tx = await db.credit_ledger.find({"workspace_id": ws}, {"_id": 0}).sort("created_at", -1).to_list(8)
    wsdoc = await db.workspaces.find_one({"id": ws}, {"_id": 0})
    return {"videos_generated": videos, "processing": sum(counts[s] for s in ACTIVE), "completed": counts["completed"],
            "failed": counts["failed"], "cancelled": counts["cancelled"], "credits": wsdoc["credits_balance"],
            "unlimited_credits": bool(wsdoc.get("unlimited_credits")),
            "recent_projects": [{k: p.get(k) for k in ("id", "name", "status", "headline", "updated_at")}
                                for p in recent], "recent_transactions": tx,
            "email_verified": ctx["user"].get("email_verified")}
