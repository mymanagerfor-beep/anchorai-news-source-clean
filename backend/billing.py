import os
import hmac
import json
import hashlib

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core import db, now, uid, audit, rate_limit
from auth import get_ctx
from ledger import grant

router = APIRouter(prefix="/api/v1")
RZP_API = "https://api.razorpay.com/v1"

# Server-side price list (INR, one-time). Amounts in paise for Razorpay.
PACKS = {
    "starter": {"id": "starter", "name": "Starter", "credits": 120, "price_inr": 1199.0},
    "newsroom": {"id": "newsroom", "name": "Newsroom", "credits": 600, "price_inr": 4999.0},
    "agency": {"id": "agency", "name": "Agency", "credits": 1800, "price_inr": 13499.0},
}


def rzp_keys():
    return os.environ.get("RAZORPAY_KEY_ID", ""), os.environ.get("RAZORPAY_KEY_SECRET", "")


def configured():
    k, s = rzp_keys()
    return bool(k and s)


def manual_upi():
    on = os.environ.get("MANUAL_UPI_ENABLED", "0") == "1" and bool(os.environ.get("UPI_ID"))
    return {"enabled": on, "upi_id": os.environ.get("UPI_ID", "") if on else "",
            "payee_name": os.environ.get("UPI_PAYEE_NAME", "") if on else "", "qr_image": "/upi-qr.jpg" if on else ""}


@router.get("/billing/packs")
async def packs():
    return {"packs": list(PACKS.values()), "currency": "INR", "payments_configured": configured(),
            "manual_upi": manual_upi(),
            "provider": "razorpay", "pricing_note": "1 credit = 1 second of finished narration, minimum 10 per video. "
                                                    "Intro/outro cards are not charged."}


@router.get("/billing/balance")
async def balance(ctx=Depends(get_ctx)):
    held = 0
    async for j in db.jobs.find({"workspace_id": ctx["ws_id"], "reservation_state": "held"}, {"reserved_credits": 1}):
        held += j["reserved_credits"]
    return {"available": ctx["ws"]["credits_balance"], "reserved": held, "unit": "credit",
            "unlimited": bool(ctx["ws"].get("unlimited_credits"))}


@router.get("/billing/ledger")
async def ledger(ctx=Depends(get_ctx)):
    items = await db.credit_ledger.find({"workspace_id": ctx["ws_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items}


@router.get("/billing/payments")
async def payments(ctx=Depends(get_ctx)):
    items = await db.payments.find({"workspace_id": ctx["ws_id"]}, {"_id": 0, "raw": 0}).sort("created_at", -1) \
        .to_list(200)
    return {"items": items}


class CheckoutIn(BaseModel):
    pack_id: str


@router.post("/billing/checkout")
async def checkout(body: CheckoutIn, ctx=Depends(get_ctx)):
    rate_limit(f"checkout:{ctx['user']['id']}", 10, 600)
    pack = PACKS.get(body.pack_id)
    if not pack:
        raise HTTPException(404, "Unknown credit pack")
    if not configured():
        raise HTTPException(503, "Payments are not configured yet. The administrator must add Razorpay keys.")
    key_id, secret = rzp_keys()
    pay_id = uid()
    amount = int(round(pack["price_inr"] * 100))
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{RZP_API}/orders", auth=(key_id, secret), json={
                "amount": amount, "currency": "INR", "receipt": pay_id[:40],
                "notes": {"workspace_id": ctx["ws_id"], "pack_id": pack["id"], "payment_record": pay_id}})
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach the payment provider. Please try again.")
    if r.status_code >= 400:
        raise HTTPException(502, "The payment provider rejected the order. Check the Razorpay configuration.")
    order = r.json()
    await db.payments.insert_one({
        "id": pay_id, "workspace_id": ctx["ws_id"], "user_id": ctx["user"]["id"], "provider": "razorpay",
        "order_id": order["id"], "payment_id": None, "pack_id": pack["id"], "credits": pack["credits"],
        "amount": pack["price_inr"], "currency": "INR", "status": "created", "credited": False,
        "webhook_events": [], "created_at": now(), "updated_at": now()})
    return {"provider": "razorpay", "key_id": key_id, "order_id": order["id"], "amount": amount, "currency": "INR",
            "name": "AnchorAI News", "description": f"{pack['name']} pack · {pack['credits']} credits",
            "prefill": {"email": ctx["user"]["email"], "name": ctx["user"]["name"]}, "payment_record_id": pay_id}


async def fulfil(order_id, payment_id, source):  # noqa: C901
    """Grant credits once per verified payment. Safe under duplicate webhooks and client callbacks."""
    p = await db.payments.find_one({"order_id": order_id}, {"_id": 0})
    if not p:
        return None
    await db.payments.update_one({"order_id": order_id}, {"$set": {"payment_id": payment_id, "status": "paid",
                                                                   "verified_via": source, "updated_at": now()}})
    granted = await grant(p["workspace_id"], p["user_id"], "purchase", p["credits"], f"payment:{order_id}",
                          payment_ref=payment_id, note=f"{PACKS[p['pack_id']]['name']} pack")
    if granted:
        await db.payments.update_one({"order_id": order_id}, {"$set": {"credited": True}})
        await audit(p["workspace_id"], p["user_id"], "payment.credited", p["id"], {"credits": p["credits"]})
    return p


class UpiSubmitIn(BaseModel):
    pack_id: str
    upi_ref: str = Field(min_length=6, max_length=35, pattern=r"^[A-Za-z0-9]+$")
    payer_name: str = Field("", max_length=80)


@router.post("/billing/upi/submit")
async def upi_submit(body: UpiSubmitIn, ctx=Depends(get_ctx)):
    """Manual UPI: records the user's UPI reference. Credits are added only after an admin confirms receipt."""
    rate_limit(f"upi:{ctx['user']['id']}", 5, 3600)
    if not manual_upi()["enabled"]:
        raise HTTPException(503, "UPI payments are not enabled")
    pack = PACKS.get(body.pack_id)
    if not pack:
        raise HTTPException(404, "Unknown credit pack")
    pay_id = uid()
    doc = {"id": pay_id, "workspace_id": ctx["ws_id"], "user_id": ctx["user"]["id"], "provider": "upi_manual",
           "order_id": f"upi_{pay_id}", "payment_id": None, "upi_ref": body.upi_ref.upper(),
           "payer_name": body.payer_name.strip(), "payer_email": ctx["user"]["email"], "pack_id": pack["id"],
           "credits": pack["credits"], "amount": pack["price_inr"], "currency": "INR", "status": "pending_review",
           "credited": False, "webhook_events": [], "created_at": now(), "updated_at": now()}
    try:
        await db.payments.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "This UPI reference has already been submitted")
    await audit(ctx["ws_id"], ctx["user"]["id"], "payment.upi_submitted", pay_id, {"pack": pack["id"]})
    doc.pop("_id", None)
    return doc


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/billing/verify")
async def verify(body: VerifyIn, ctx=Depends(get_ctx)):
    key_id, secret = rzp_keys()
    p = await db.payments.find_one({"order_id": body.razorpay_order_id, "workspace_id": ctx["ws_id"]})
    if not p:
        raise HTTPException(404, "Payment not found")
    expected = hmac.new(secret.encode(), f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(400, "Payment signature verification failed")
    # Confirm with Razorpay directly; the browser callback alone never grants credits.
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{RZP_API}/payments/{body.razorpay_payment_id}", auth=(key_id, secret))
    pay = r.json() if r.status_code < 400 else {}
    if pay.get("order_id") != body.razorpay_order_id or pay.get("status") not in ("captured", "authorized"):
        await db.payments.update_one({"order_id": body.razorpay_order_id}, {"$set": {"status": "pending_capture"}})
        return {"status": "pending", "message": "Payment received but not yet captured. Credits will be added once "
                                                "Razorpay confirms it."}
    if pay.get("status") == "authorized":
        return {"status": "pending", "message": "Payment authorized; credits are added once it is captured."}
    await fulfil(body.razorpay_order_id, body.razorpay_payment_id, "api_check")
    return {"status": "paid"}


@router.post("/webhooks/payments/{provider}")
async def payment_webhook(provider: str, request: Request):
    if provider != "razorpay":
        raise HTTPException(404, "Unknown provider")
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    raw = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")
    if not secret or not hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), sig):
        raise HTTPException(400, "Invalid webhook signature")
    event = json.loads(raw)
    event_id = request.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(raw).hexdigest()
    if await db.webhook_events.find_one({"event_id": event_id}):
        return {"status": "duplicate"}
    await db.webhook_events.insert_one({"event_id": event_id, "provider": "razorpay", "type": event.get("event"),
                                        "status": "processing", "created_at": now()})
    etype = event.get("event")
    pay = (((event.get("payload") or {}).get("payment") or {}).get("entity")) or {}
    order = (((event.get("payload") or {}).get("order") or {}).get("entity")) or {}
    order_id = pay.get("order_id") or order.get("id")
    if etype in ("payment.captured", "order.paid") and order_id:
        await fulfil(order_id, pay.get("id"), "webhook")
    elif etype == "payment.failed" and order_id:
        await db.payments.update_one({"order_id": order_id, "credited": False},
                                     {"$set": {"status": "failed", "updated_at": now(),
                                               "failure_reason": (pay.get("error_description") or "")[:200]}})
    await db.payments.update_one({"order_id": order_id}, {"$push": {"webhook_events": {"id": event_id, "type": etype,
                                                                                       "at": now()}}})
    await db.webhook_events.update_one({"event_id": event_id}, {"$set": {"status": "processed"}})
    return {"status": "ok"}


@router.post("/webhooks/avatar/{provider}")
async def avatar_webhook(provider: str, request: Request):
    # Universal-key fal mode delivers no app webhooks; jobs are tracked by authenticated polling.
    raise HTTPException(400, "Webhook signature cannot be verified for this provider; status is polled instead.")
