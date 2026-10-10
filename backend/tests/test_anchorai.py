"""Automated tests. Provider calls are MOCKED here (never proof of live generation).
Run: cd /app/backend && TEST_DB_NAME=anchorai_test python -m pytest tests -q"""
import os
import io
import json
import hmac
import hashlib
import asyncio
import subprocess

os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "anchorai_test")
os.environ["RUN_WORKER"] = "0"
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import server  # noqa: E402
from core import db  # noqa: E402
import render  # noqa: E402
import worker  # noqa: E402
import providers  # noqa: E402

GU = "નમસ્તે, આપ જોઈ રહ્યા છો તાજા સમાચાર. આજે અમદાવાદમાં ભારે વરસાદ પડ્યો છે."


@pytest.fixture(scope="session")
def client():
    from pymongo import MongoClient
    MongoClient(os.environ["MONGO_URL"]).drop_database(os.environ["DB_NAME"])
    with TestClient(server.app) as c:
        yield c
    MongoClient(os.environ["MONGO_URL"]).drop_database(os.environ["DB_NAME"])


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def register(c, email):
    import core
    core._rate.clear()
    r = c.post("/api/v1/auth/register", json={"name": "T", "email": email, "password": "password123",
                                             "workspace_name": "WS"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def portrait_bytes(size=(800, 1000), fmt="JPEG"):
    b = io.BytesIO()
    Image.new("RGB", size, (120, 90, 80)).save(b, fmt)
    return b.getvalue()


def upload(c, h, data=None, consent=True, name="p.jpg"):
    return c.post("/api/v1/anchors", headers=h, files={"file": (name, data or portrait_bytes(), "image/jpeg")},
                  data={"display_name": "A", "authorized_by": "Person", "consent_basis": "self",
                        "consent_confirmed": str(consent).lower(), "consent_version": "2026-06-v1"})


def verify_and_fund(user_id, ws_credits):
    async def go():
        from motor.motor_asyncio import AsyncIOMotorClient
        d = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await d.users.update_one({"id": user_id}, {"$set": {"email_verified": True}})
        u = await d.users.find_one({"id": user_id})
        await d.workspaces.update_one({"id": u["current_workspace_id"]}, {"$set": {"credits_balance": ws_credits}})
    asyncio.run(go())


def test_register_creates_workspace(client):
    h, _ = register(client, "reg@example.com")
    ws = client.get("/api/v1/workspaces/current", headers=h).json()
    assert ws["role"] == "owner" and ws["credits_balance"] == 0


def test_gujarati_script_analysis(client):
    r = client.post("/api/v1/scripts/analyze", json={"script": GU}).json()
    assert r["valid"] and r["estimated_seconds"] > 0
    bad = client.post("/api/v1/scripts/analyze", json={"script": "Only English text here"}).json()
    assert not bad["valid"]
    long = client.post("/api/v1/scripts/analyze", json={"script": GU * 20}).json()
    assert not long["valid"]


def test_portrait_validation(client):
    h, _ = register(client, "img@example.com")
    assert upload(client, h).status_code == 200
    assert upload(client, h, b"not an image at all" * 20).status_code == 415
    assert upload(client, h, b"\xff\xd8\xff" + b"0" * 500).status_code == 400
    assert upload(client, h, portrait_bytes((300, 300))).status_code == 400
    assert upload(client, h, b"\xff\xd8\xff" + os.urandom(11 * 1024 * 1024)).status_code == 413
    assert upload(client, h, consent=False).status_code == 400


def _project(client, h, anchor_id):
    return client.post("/api/v1/projects", headers=h, json={"name": "P", "anchor_id": anchor_id, "script": GU,
                                                           "headline": "હેડલાઇન", "voice": "Sarah"}).json()


def test_generation_guards_and_idempotency(client, monkeypatch):
    h, u = register(client, "gen@example.com")
    a = upload(client, h).json()
    p = _project(client, h, a["id"])
    key = {"Idempotency-Key": "test-key-0000000000001"}
    r = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, **key}, json={"consent_confirmed": True})
    assert r.status_code == 403  # email not verified
    verify_and_fund(u["id"], 0)
    r = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, **key}, json={})
    assert r.status_code == 400  # no consent confirmation
    r = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, **key}, json={"consent_confirmed": True})
    assert r.status_code == 402  # insufficient credits
    monkeypatch.setenv("EMERGENT_LLM_KEY", "")
    monkeypatch.setenv("FAL_KEY", "")
    verify_and_fund(u["id"], 100)
    r = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, **key}, json={"consent_confirmed": True})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]
    monkeypatch.undo()
    r1 = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, **key}, json={"consent_confirmed": True})
    r2 = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, **key}, json={"consent_confirmed": True})
    assert r1.status_code == 200 and r2.json()["id"] == r1.json()["id"]
    bal = client.get("/api/v1/billing/balance", headers=h).json()
    assert bal["available"] == 100 - r1.json()["reserved_credits"]
    # cancel queued job -> full release
    client.post(f"/api/v1/jobs/{r1.json()['id']}/cancel", headers=h)
    assert client.get("/api/v1/billing/balance", headers=h).json()["available"] == 100


def test_cross_workspace_denied(client):
    h1, _ = register(client, "x1@example.com")
    h2, _ = register(client, "x2@example.com")
    a = upload(client, h1).json()
    p = _project(client, h1, a["id"])
    assert client.get(f"/api/v1/anchors/{a['id']}", headers=h2).status_code == 404
    assert client.get(f"/api/v1/projects/{p['id']}", headers=h2).status_code == 404
    assert client.delete(f"/api/v1/anchors/{a['id']}", headers=h2).status_code == 404
    assert client.post("/api/v1/videos/nonexistent/download-url", headers=h2).status_code == 404


def test_signed_file_requires_valid_token(client):
    assert client.get("/api/v1/files/signed?t=forged").status_code == 401


def test_portrait_deletion_blocks_use(client):
    h, _ = register(client, "del@example.com")
    a = upload(client, h).json()
    assert client.delete(f"/api/v1/anchors/{a['id']}", headers=h).status_code == 200
    lst = client.get("/api/v1/anchors", headers=h).json()["items"]
    assert all(x["id"] != a["id"] for x in lst)
    t = a["image_url"].split("t=")[1]
    assert client.get(f"/api/v1/files/signed?t={t}").status_code == 404


def test_payment_webhook_signature_and_duplicates(client):
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1",
                                                                                         "order_id": "order_x"}}}})
    assert client.post("/api/v1/webhooks/payments/razorpay", content=body,
                       headers={"X-Razorpay-Signature": "bad"}).status_code == 400
    sig = hmac.new(b"test_webhook_secret", body.encode(), hashlib.sha256).hexdigest()
    hd = {"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_1"}
    assert client.post("/api/v1/webhooks/payments/razorpay", content=body, headers=hd).json()["status"] == "ok"
    assert client.post("/api/v1/webhooks/payments/razorpay", content=body, headers=hd).json()["status"] == "duplicate"


def test_subtitles_timing_and_export():
    cues, spoken, _ = render.build_spoken(GU, [{"word": "અમદાવાદમાં", "say": "અમદાવાદ માં"}])
    assert cues[1].startswith("આજે અમદાવાદમાં") and "અમદાવાદ માં" in spoken[1]
    timed, method = render.time_cues(cues, spoken, {}, 6.0)
    assert method == "proportional_estimate" and timed[-1]["end"] == pytest.approx(6.0)
    render.validate_cues(timed, 6.0)
    assert "-->" in render.to_srt(timed) and render.to_vtt(timed).startswith("WEBVTT")
    img = render.draw_cue(cues[0], {"size": 42})
    assert img.width > 100


def _fake_anchor(tmp, seconds=4):
    p = tmp / "anchor.mp4"
    subprocess.run([render.FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=720x900:rate=25", "-f", "lavfi", "-i",
                    "sine=f=300", "-t", str(seconds), "-c:v", "libx264", "-c:a", "aac", str(p)], capture_output=True)
    return p


def test_render_valid_mp4(tmp_path):
    a = _fake_anchor(tmp_path)
    timed, _ = render.time_cues(*render.build_spoken(GU, [])[:2], {}, 4.0)
    out, info, _ = render.render_final(tmp_path / "r", a, a, {"headline": "હેડલાઇન", "ticker_text": "ટિકર",
                                                               "outro_enabled": True}, timed, {"enabled": True})
    assert (info["width"], info["height"]) == (1920, 1080) and info["has_audio"] and info["video_codec"] == "h264"
    assert info["duration"] == pytest.approx(7.0, abs=1.0)


def test_render_failure_on_bad_input(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"garbage")
    with pytest.raises(render.RenderError):
        render.render_final(tmp_path / "r", bad, bad, {}, [], {})


def test_worker_mocked_success_and_failure(client, monkeypatch, tmp_path):
    """MOCKED provider: verifies capture on success and full release on failure."""
    h, u = register(client, "wk@example.com")
    verify_and_fund(u["id"], 100)
    a = upload(client, h).json()
    anchor_mp4 = _fake_anchor(tmp_path, 5).read_bytes()
    mp3 = tmp_path / "n.mp3"
    subprocess.run([render.FFMPEG, "-y", "-f", "lavfi", "-i", "sine=f=200", "-t", "5", str(mp3)], capture_output=True)
    sub = {"request_id": "r", "status_url": "s", "response_url": "x", "cancel_url": None}
    monkeypatch.setattr(providers.FalQueueAdapter, "submit", lambda self, *a, **k: sub)
    monkeypatch.setattr(providers.FalQueueAdapter, "get_status", lambda self, *a: "COMPLETED")
    monkeypatch.setattr(providers.FalQueueAdapter, "retrieve_output",
                        lambda self, s, stage: {"audio": {"url": "a"}, "timestamps": []} if "narration" in stage
                        else {"video": {"url": "v"}, "duration": 5})
    monkeypatch.setattr(worker, "download", lambda url, *a, **k: mp3.read_bytes() if url == "a" else anchor_mp4)

    async def no_mail(*a, **k):
        return True
    monkeypatch.setattr(worker, "send_video_ready", no_mail)
    p = _project(client, h, a["id"])
    j = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**h, "Idempotency-Key": "worker-test-0000000001"},
                    json={"consent_confirmed": True}).json()
    fresh(lambda: worker.process(j["id"]))
    done = client.get(f"/api/v1/jobs/{j['id']}", headers=h).json()
    assert done["status"] == "completed", done.get("error_message")
    assert done["final_credits"] == 10
    assert client.get("/api/v1/billing/balance", headers=h).json()["available"] == 90
    jdoc = await_job(j["id"])
    fresh(lambda: worker.settle(jdoc, 10))  # duplicate capture is a no-op
    assert client.get("/api/v1/billing/balance", headers=h).json()["available"] == 90
    vids = client.get(f"/api/v1/projects/{p['id']}/videos", headers=h).json()["items"]
    assert vids and client.post(f"/api/v1/videos/{vids[0]['id']}/download-url", headers=h).status_code == 200

    def boom(self, *a):
        raise providers.ProviderError("provider_timeout", "timeout")
    monkeypatch.setattr(providers.FalQueueAdapter, "get_status", boom)
    p2 = _project(client, h, a["id"])
    j2 = client.post(f"/api/v1/projects/{p2['id']}/generate", headers={**h, "Idempotency-Key": "worker-test-0000000002"},
                     json={"consent_confirmed": True}).json()
    fresh(lambda: worker.process(j2["id"]))
    f = client.get(f"/api/v1/jobs/{j2['id']}", headers=h).json()
    assert f["status"] == "failed" and f["final_credits"] == 0
    assert client.get("/api/v1/billing/balance", headers=h).json()["available"] == 90


def await_job(job_id):
    async def go():
        from motor.motor_asyncio import AsyncIOMotorClient
        return await AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]].jobs.find_one({"id": job_id})
    return asyncio.run(go())


def fresh(fn):
    """Run worker code in a new event loop with a Mongo client bound to that loop, then restore."""
    import importlib
    import core
    from motor.motor_asyncio import AsyncIOMotorClient
    mods = (core, worker, importlib.import_module("ledger"))
    orig = [m.db for m in mods]

    async def go():
        d = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        for m in mods:
            m.db = d
        try:
            return await fn()
        finally:
            for m, o in zip(mods, orig):
                m.db = o
    return asyncio.run(go())


def test_admin_unlimited_and_grant(client):
    import core
    core._rate.clear()
    t = client.post("/api/v1/auth/login", json={"email": os.environ["ADMIN_EMAIL"],
                                               "password": os.environ["ADMIN_PASSWORD"]}).json()["token"]
    ha = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/v1/billing/balance", headers=ha).json()["unlimited"] is True
    a = upload(client, ha).json()
    p = _project(client, ha, a["id"])
    j = client.post(f"/api/v1/projects/{p['id']}/generate", headers={**ha, "Idempotency-Key": "admin-unlim-00000001"},
                    json={"consent_confirmed": True})
    assert j.status_code == 200  # no 402 despite zero balance
    client.post(f"/api/v1/jobs/{j.json()['id']}/cancel", headers=ha)
    assert client.get("/api/v1/billing/balance", headers=ha).json()["available"] == 0
    hu, u = register(client, "granted@example.com")
    ws = client.get("/api/v1/workspaces/current", headers=hu).json()["id"]
    assert client.post("/api/v1/admin/credits/adjust", headers=ha,
                       json={"workspace_id": ws, "amount": 60, "reason": "Granted by admin"}).status_code == 200
    assert client.get("/api/v1/billing/balance", headers=hu).json()["available"] == 60
    assert client.post("/api/v1/admin/credits/adjust", headers=hu,
                       json={"workspace_id": ws, "amount": 60, "reason": "self grant"}).status_code == 403
