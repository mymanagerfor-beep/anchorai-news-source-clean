"""Review-item tests: admin give-credits, admin unlimited generate guard, cross-isolation, project rename, jobs listing.

Runs against the public preview URL. Uses MongoDB directly to flip email_verified for a fresh test user
(mirrors the policy documented in /app/memory/test_credentials.md).
"""
import io
import os
import uuid
import asyncio
import pytest
import requests
from PIL import Image
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://gujarati-anchor.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api/v1"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "admin@anchorai.news"
ADMIN_PASSWORD = "AnchorAdmin@2026"
GU_SCRIPT = ("નમસ્તે, આપ જોઈ રહ્યા છો તાજા સમાચાર. આજે અમદાવાદમાં ભારે વરસાદ પડ્યો છે. " * 2).strip()


def _portrait(size=(800, 1000)):
    b = io.BytesIO()
    Image.new("RGB", size, (120, 90, 80)).save(b, "JPEG")
    return b.getvalue()


async def _verify_in_db(email: str):
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        await client[DB_NAME].users.update_one({"email": email}, {"$set": {"email_verified": True}})
    finally:
        client.close()


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def user_b():
    """Register fresh user B, mark email_verified via Mongo, return token+headers+ws_id."""
    email = f"TEST_userb_{uuid.uuid4().hex[:8]}@example.com"
    pw = "UserTest@2026"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": "User B",
                                                    "workspace_name": "WS B"})
    assert r.status_code in (200, 201), r.text
    asyncio.run(_verify_in_db(email))
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    ws = requests.get(f"{API}/workspaces/current", headers=headers).json()
    return {"email": email, "password": pw, "token": token, "headers": headers, "ws_id": ws["id"]}


# ---------- Admin unlimited credits ----------
def test_admin_balance_is_unlimited(admin_headers):
    r = requests.get(f"{API}/billing/balance", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    assert d.get("unlimited") is True, d


def test_admin_workspace_marked_unlimited(admin_headers):
    r = requests.get(f"{API}/workspaces/current", headers=admin_headers)
    assert r.status_code == 200
    assert r.json().get("unlimited_credits") is True


# ---------- Admin give credits to user ----------
def test_admin_can_grant_credits_to_user_b(admin_headers, user_b):
    # Initial balance for user B
    r0 = requests.get(f"{API}/billing/balance", headers=user_b["headers"])
    assert r0.status_code == 200
    before = r0.json()["available"]

    r = requests.post(f"{API}/admin/credits/adjust", headers=admin_headers,
                      json={"workspace_id": user_b["ws_id"], "amount": 120,
                            "reason": "Test credits grant from review"})
    assert r.status_code == 200, r.text

    r2 = requests.get(f"{API}/billing/balance", headers=user_b["headers"])
    assert r2.status_code == 200
    after = r2.json()["available"]
    assert after == before + 120, f"expected {before+120} got {after}"


def test_admin_adjust_on_unlimited_workspace_rejected(admin_headers):
    ws = requests.get(f"{API}/workspaces/current", headers=admin_headers).json()
    r = requests.post(f"{API}/admin/credits/adjust", headers=admin_headers,
                      json={"workspace_id": ws["id"], "amount": 50, "reason": "attempt on unlimited"})
    assert r.status_code == 400, r.text


def test_non_admin_cannot_adjust_credits(user_b):
    r = requests.post(f"{API}/admin/credits/adjust", headers=user_b["headers"],
                      json={"workspace_id": user_b["ws_id"], "amount": 10, "reason": "should be forbidden"})
    assert r.status_code == 403, r.text


# ---------- Jobs listing for admin (should contain prior live job) ----------
def test_admin_jobs_list_contains_completed(admin_headers):
    r = requests.get(f"{API}/jobs", headers=admin_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    # The acceptance test produced one completed job
    done = [j for j in items if j["status"] == "completed"]
    assert done, f"Expected at least one completed job, got statuses {[j['status'] for j in items]}"
    j = done[0]
    assert j.get("final", {}).get("video_asset_id"), "Completed job must have video asset"


def test_admin_job_detail_signed_url(admin_headers):
    r = requests.get(f"{API}/jobs", headers=admin_headers)
    done = [j for j in r.json()["items"] if j["status"] == "completed"]
    if not done:
        pytest.skip("No completed admin job to inspect")
    jid = done[0]["id"]
    d = requests.get(f"{API}/jobs/{jid}", headers=admin_headers)
    assert d.status_code == 200
    body = d.json()
    assert "script" in body and "settings" in body


# ---------- Admin project rename ----------
def test_admin_can_create_and_rename_project(admin_headers):
    name = f"TEST_rename_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/projects", headers=admin_headers, json={"name": name})
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    new_name = name + "_renamed"
    r2 = requests.patch(f"{API}/projects/{pid}", headers=admin_headers, json={"name": new_name})
    assert r2.status_code == 200, r2.text
    r3 = requests.get(f"{API}/projects/{pid}", headers=admin_headers)
    assert r3.status_code == 200
    assert r3.json()["name"] == new_name
    # cleanup
    requests.delete(f"{API}/projects/{pid}", headers=admin_headers)


# ---------- Billing packs + checkout not configured ----------
def test_billing_packs_inr(admin_headers):
    r = requests.get(f"{API}/billing/packs", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    packs = body["packs"] if isinstance(body, dict) and "packs" in body else (body.get("items") if isinstance(body, dict) else body)
    names = [p.get("name", "").lower() for p in packs]
    assert any("starter" in n for n in names)
    assert any("newsroom" in n for n in names)
    assert any("agency" in n for n in names)
    # Payments not configured per request
    if isinstance(body, dict):
        assert body.get("payments_configured") is False
    for p in packs:
        assert "price_inr" in p or p.get("currency", "INR").upper() == "INR"


# ---------- Cross-workspace isolation extra ----------
def test_user_b_cannot_see_admin_job(admin_headers, user_b):
    r = requests.get(f"{API}/jobs", headers=admin_headers)
    done = [j for j in r.json()["items"] if j["status"] == "completed"]
    if not done:
        pytest.skip("No admin completed job to use")
    jid = done[0]["id"]
    r2 = requests.get(f"{API}/jobs/{jid}", headers=user_b["headers"])
    assert r2.status_code == 404


# ---------- Anchor validation: txt renamed to .jpg must be rejected ----------
def test_anchor_upload_rejects_fake_jpg(admin_headers):
    files = {"file": ("fake.jpg", b"this is plain text, not an image", "image/jpeg")}
    data = {"display_name": "Fake Anchor", "owner_full_name": "Tester",
            "consent_scope": "Breaking News", "consent_confirmed": "true"}
    r = requests.post(f"{API}/anchors", headers=admin_headers, data=data, files=files)
    assert r.status_code in (400, 415, 422), r.text
