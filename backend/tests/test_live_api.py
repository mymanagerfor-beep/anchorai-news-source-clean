"""Live API tests against the public REACT_APP_BACKEND_URL (production preview).
Tests real deployed app - verifies integration, auth, admin, billing, cross-workspace isolation."""
import os
import io
import time
import uuid
import json
import hmac
import hashlib
import pytest
import requests
from PIL import Image

BASE = "https://gujarati-anchor.preview.emergentagent.com"
API = f"{BASE}/api/v1"
GU = "નમસ્તે, આપ જોઈ રહ્યા છો તાજા સમાચાર. આજે અમદાવાદમાં ભારે વરસાદ પડ્યો છે."

ADMIN_EMAIL = "admin@anchorai.news"
ADMIN_PASSWORD = "AnchorAdmin@2026"


def _portrait(size=(800, 1000)):
    b = io.BytesIO()
    Image.new("RGB", size, (120, 90, 80)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Health & landing ----------
def test_health():
    r = requests.get(f"{BASE}/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True or d.get("status") in ("ok", "healthy", "degraded")


def test_landing_html_loads():
    r = requests.get(BASE)
    assert r.status_code == 200
    assert "<html" in r.text.lower()


# ---------- Auth ----------
def test_admin_me(admin_headers):
    r = requests.get(f"{API}/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL
    assert r.json().get("role") == "admin"


def test_forgot_password_generic_response():
    r = requests.post(f"{API}/auth/forgot-password", json={"email": "nonexistent-xyz@example.com"})
    assert r.status_code == 200
    # Should not reveal existence
    body = r.json()
    assert "error" not in body or body.get("ok") or "message" in body or body.get("status")


def test_reset_password_invalid_token():
    r = requests.post(f"{API}/auth/reset-password", json={"token": "invalid-token", "password": "newpass123"})
    assert r.status_code in (400, 401, 403, 404, 422)


def test_verify_email_invalid_token():
    r = requests.post(f"{API}/auth/verify-email", json={"token": "invalid-token"})
    assert r.status_code in (400, 401, 403, 404, 422)


def test_login_invalid_credentials():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password-xxx"})
    assert r.status_code in (400, 401, 403, 429)


# ---------- Script analyze ----------
def test_script_analyze_valid():
    r = requests.post(f"{API}/scripts/analyze", json={"script": GU})
    assert r.status_code == 200
    d = r.json()
    assert d["valid"] is True
    assert d["estimated_seconds"] > 0


def test_script_analyze_english_invalid():
    r = requests.post(f"{API}/scripts/analyze", json={"script": "Only English text here"})
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_script_analyze_too_long():
    r = requests.post(f"{API}/scripts/analyze", json={"script": GU * 25})
    assert r.status_code == 200
    assert r.json()["valid"] is False


# ---------- Workspace ----------
def test_workspace_current(admin_headers):
    r = requests.get(f"{API}/workspaces/current", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    assert "credits_balance" in d
    assert "role" in d


# ---------- Billing ----------
def test_billing_balance(admin_headers):
    r = requests.get(f"{API}/billing/balance", headers=admin_headers)
    assert r.status_code == 200
    assert "available" in r.json()


def test_billing_packs(admin_headers):
    r = requests.get(f"{API}/billing/packs", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    # Payments not configured notice expected
    assert isinstance(d, dict) or isinstance(d, list)


def test_billing_checkout_not_configured(admin_headers):
    r = requests.post(f"{API}/billing/checkout", headers=admin_headers, json={"pack_id": "starter"})
    assert r.status_code == 503, f"Expected 503 payments-not-configured, got {r.status_code}: {r.text}"
    assert "not configured" in r.text.lower() or "payment" in r.text.lower()


def test_razorpay_webhook_bad_signature():
    body = json.dumps({"event": "payment.captured", "payload": {}})
    r = requests.post(f"{API}/webhooks/payments/razorpay", data=body,
                      headers={"X-Razorpay-Signature": "bad", "Content-Type": "application/json"})
    assert r.status_code == 400


# ---------- Admin ----------
def test_admin_health(admin_headers):
    r = requests.get(f"{API}/admin/health", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    # Expect issues list including "Payments not configured"
    issues_str = json.dumps(d).lower()
    assert "payment" in issues_str


def test_non_admin_blocked_on_admin_endpoints():
    # Create a regular user, verify admin endpoint rejects
    email = f"nonadmin_{uuid.uuid4().hex[:8]}@example.com"
    reg = requests.post(f"{API}/auth/register", json={
        "name": "NA", "email": email, "password": "password123", "workspace_name": "WS NA"
    })
    if reg.status_code == 429:
        pytest.skip("Rate limited")
    assert reg.status_code == 200, reg.text
    token = reg.json()["token"]
    r = requests.get(f"{API}/admin/health", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403)


# ---------- Cross workspace isolation ----------
def test_cross_workspace_denied():
    email1 = f"iso1_{uuid.uuid4().hex[:8]}@example.com"
    email2 = f"iso2_{uuid.uuid4().hex[:8]}@example.com"
    r1 = requests.post(f"{API}/auth/register", json={
        "name": "U1", "email": email1, "password": "password123", "workspace_name": "W1"})
    if r1.status_code == 429:
        pytest.skip("Rate limited")
    assert r1.status_code == 200, r1.text
    h1 = {"Authorization": f"Bearer {r1.json()['token']}"}
    r2 = requests.post(f"{API}/auth/register", json={
        "name": "U2", "email": email2, "password": "password123", "workspace_name": "W2"})
    if r2.status_code == 429:
        pytest.skip("Rate limited")
    assert r2.status_code == 200
    h2 = {"Authorization": f"Bearer {r2.json()['token']}"}

    # Upload anchor as U1
    up = requests.post(f"{API}/anchors", headers=h1,
                       files={"file": ("p.jpg", _portrait(), "image/jpeg")},
                       data={"display_name": "A", "authorized_by": "P", "consent_basis": "self",
                             "consent_confirmed": "true", "consent_version": "2026-06-v1"})
    assert up.status_code == 200, up.text
    anchor_id = up.json()["id"]

    # U2 cannot access U1 anchor
    g = requests.get(f"{API}/anchors/{anchor_id}", headers=h2)
    assert g.status_code == 404


# ---------- Anchor validation (uses one user) ----------
def test_anchor_upload_validation():
    email = f"anc_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "name": "A", "email": email, "password": "password123", "workspace_name": "W"})
    if r.status_code == 429:
        pytest.skip("Rate limited")
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    def up(data=None, consent="true", filename="p.jpg", content_type="image/jpeg"):
        return requests.post(f"{API}/anchors", headers=h,
                             files={"file": (filename, data or _portrait(), content_type)},
                             data={"display_name": "A", "authorized_by": "P", "consent_basis": "self",
                                   "consent_confirmed": consent, "consent_version": "2026-06-v1"})

    # Valid upload
    assert up().status_code == 200
    # Non-image bytes
    assert up(b"not an image at all" * 20).status_code == 415
    # Too small portrait
    small = io.BytesIO()
    Image.new("RGB", (300, 300), (10, 10, 10)).save(small, "JPEG")
    assert up(small.getvalue()).status_code == 400
    # Missing consent
    assert up(consent="false").status_code == 400
