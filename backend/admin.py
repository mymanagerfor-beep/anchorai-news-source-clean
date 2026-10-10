import asyncio
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from PIL import features

from core import db, init_storage, audit, now, uid, STORAGE_BACKEND
from emailer import email_configured, EMAIL_BACKEND
from auth import require_admin
from ledger import grant
from providers import health as provider_health
import render
import billing

router = APIRouter(prefix="/api/v1/admin")


@router.get("/health")
async def health(admin=Depends(require_admin)):
    prov = await asyncio.to_thread(provider_health)
    try:
        await asyncio.to_thread(init_storage)
        storage = {"ok": True, "backend": STORAGE_BACKEND}
    except Exception as e:
        storage = {"ok": False, "error": type(e).__name__}
    ff = await asyncio.to_thread(lambda: os.path.exists(render.FFMPEG))
    issues = []
    if not prov["configured"]:
        issues.append("AI provider credentials missing: set FAL_KEY (direct fal.ai) or EMERGENT_LLM_KEY.")
    elif not prov.get("reachable"):
        issues.append("AI provider is unreachable from the server.")
    elif not prov.get("auth_ok", True):
        issues.append("AI provider rejected the configured credentials.")
    if not billing.configured():
        issues.append("Payments not configured: set RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET.")
    if not email_configured():
        issues.append("Email not configured: set EMAIL_BACKEND=smtp with SMTP_* values (or EMERGENT_EMAIL_KEY).")
    if not features.check("raqm"):
        issues.append("Pillow was built without raqm: Gujarati text in videos will not shape correctly.")
    return {"provider": prov, "storage": storage, "ffmpeg": {"ok": ff, "path_basename": os.path.basename(render.FFMPEG)},
            "gujarati_font": render.FONT.exists(), "payments_configured": billing.configured(),
            "webhook_secret_configured": bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET")),
            "email_configured": email_configured(), "email_backend": EMAIL_BACKEND, "storage_backend": STORAGE_BACKEND,
            "disk_free_gb": round(shutil.disk_usage("/tmp").free / 1e9, 1), "issues": issues}


@router.get("/workspaces")
async def workspaces(q: str = "", admin=Depends(require_admin)):
    import re
    flt = {"status": "active"}
    if q:
        flt["email"] = {"$regex": re.escape(q), "$options": "i"}
    users = await db.users.find(flt, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(100)
    owned = {w["owner_id"]: w for w in await db.workspaces.find({"owner_id": {"$in": [u["id"] for u in users]}},
                                                                 {"_id": 0}).to_list(200)}
    return {"items": [{"user": {k: u.get(k) for k in ("id", "email", "name", "role", "email_verified", "status")},
                       "workspace": owned.get(u["id"])} for u in users]}


class AdjustIn(BaseModel):
    workspace_id: str
    amount: int = Field(ge=-100000, le=100000)
    reason: str = Field(min_length=5, max_length=300)


@router.post("/credits/adjust")
async def adjust(body: AdjustIn, admin=Depends(require_admin)):
    ws = await db.workspaces.find_one({"id": body.workspace_id})
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if body.amount == 0:
        raise HTTPException(400, "Amount must be non-zero")
    if ws.get("unlimited_credits"):
        raise HTTPException(400, "This workspace already has unlimited credits")
    if ws["credits_balance"] + body.amount < 0:
        raise HTTPException(400, "Adjustment would make the balance negative")
    await grant(body.workspace_id, admin["id"], "admin_adjustment", body.amount, f"admin:{uid()}", note=body.reason)
    await audit(body.workspace_id, admin["id"], "admin.credit_adjustment", body.workspace_id,
                {"amount": body.amount, "reason": body.reason})
    return {"ok": True}


@router.get("/audit")
async def audit_events(admin=Depends(require_admin)):
    return {"items": await db.audit_events.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)}


@router.get("/reconcile")
async def reconcile(admin=Depends(require_admin)):
    out = []
    async for ws in db.workspaces.find({}, {"_id": 0, "id": 1, "name": 1, "credits_balance": 1}):
        s = await db.credit_ledger.aggregate([{"$match": {"workspace_id": ws["id"]}},
                                              {"$group": {"_id": None, "t": {"$sum": "$amount"}}}]).to_list(1)
        total = s[0]["t"] if s else 0
        if total != ws["credits_balance"]:
            out.append({**ws, "ledger_sum": total})
    return {"mismatches": out, "checked_at": now()}


@router.get("/payments")
async def admin_payments(status: str = "pending_review", admin=Depends(require_admin)):
    q = {"provider": "upi_manual"}
    if status != "all":
        q["status"] = status
    return {"items": await db.payments.find(q, {"_id": 0, "raw": 0}).sort("created_at", -1).to_list(200)}


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    note: str = Field("", max_length=300)


@router.post("/payments/{pid}/review")
async def review_payment(pid: str, body: ReviewIn, admin=Depends(require_admin)):
    p = await db.payments.find_one_and_update(
        {"id": pid, "provider": "upi_manual", "status": "pending_review"},
        {"$set": {"status": "approving" if body.action == "approve" else "rejected", "reviewed_by": admin["id"],
                  "review_note": body.note, "updated_at": now()}})
    if not p:
        raise HTTPException(409, "Payment is not pending review")
    if body.action == "approve":
        await billing.fulfil(p["order_id"], p["upi_ref"], "admin_upi_review")
    await audit(p["workspace_id"], admin["id"], f"payment.upi_{body.action}d", pid,
                {"credits": p["credits"], "note": body.note})
    return {"ok": True, "status": "paid" if body.action == "approve" else "rejected"}
