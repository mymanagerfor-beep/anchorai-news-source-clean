import math
from pymongo.errors import DuplicateKeyError

from core import db, now, uid, Cfg


class InsufficientCredits(Exception):
    pass


def credits_for_seconds(seconds: float) -> int:
    return max(Cfg.MIN_CREDITS_PER_VIDEO, math.ceil(seconds * Cfg.CREDITS_PER_SECOND))


def reserve_amount(est_seconds: float) -> int:
    return math.ceil(credits_for_seconds(est_seconds) * (1 + Cfg.RESERVE_BUFFER))


async def _entry(ws_id, user_id, typ, amount, key, job_id=None, payment_ref=None, note=None):
    """Append-only ledger insert; returns False if the idempotency key already exists."""
    try:
        await db.credit_ledger.insert_one({
            "id": uid(), "workspace_id": ws_id, "user_id": user_id, "job_id": job_id, "type": typ,
            "amount": amount, "unit": "credit", "idempotency_key": key, "payment_reference": payment_ref,
            "note": note, "created_at": now(),
        })
        return True
    except DuplicateKeyError:
        return False


async def is_unlimited(ws_id):
    ws = await db.workspaces.find_one({"id": ws_id}, {"unlimited_credits": 1})
    return bool(ws and ws.get("unlimited_credits"))


async def grant(ws_id, user_id, typ, amount, key, payment_ref=None, note=None):
    if await _entry(ws_id, user_id, typ, amount, key, payment_ref=payment_ref, note=note):
        await db.workspaces.update_one({"id": ws_id}, {"$inc": {"credits_balance": amount}})
        return True
    return False


async def reserve(ws_id, user_id, job_id, amount, key):
    if await db.credit_ledger.find_one({"idempotency_key": key}):
        return True
    if await is_unlimited(ws_id):
        await _entry(ws_id, user_id, "reservation", 0, key, job_id=job_id,
                     note=f"Unlimited admin workspace: no charge (nominal {amount})")
        return True
    ws = await db.workspaces.find_one_and_update({"id": ws_id, "credits_balance": {"$gte": amount}},
                                                 {"$inc": {"credits_balance": -amount}})
    if not ws:
        raise InsufficientCredits()
    if not await _entry(ws_id, user_id, "reservation", -amount, key, job_id=job_id, note="Reserved for generation"):
        await db.workspaces.update_one({"id": ws_id}, {"$inc": {"credits_balance": amount}})
    return True


async def settle(job, actual_credits: int):
    """Capture actual usage and release the remaining reservation exactly once."""
    j = await db.jobs.find_one_and_update({"id": job["id"], "reservation_state": "held"},
                                          {"$set": {"reservation_state": "captured", "final_credits": actual_credits}})
    if not j:
        return False
    reserved = j["reserved_credits"]
    actual = min(actual_credits, reserved)
    base = f"job:{j['id']}:a{j['attempt_count']}"
    if await is_unlimited(j["workspace_id"]):
        await _entry(j["workspace_id"], j["owner_id"], "capture", 0, f"{base}:capture", job_id=j["id"],
                     note=f"Unlimited admin workspace: no charge (nominal {actual})")
        return True
    if await _entry(j["workspace_id"], j["owner_id"], "release", reserved, f"{base}:release", job_id=j["id"],
                    note="Reservation released at completion"):
        await db.workspaces.update_one({"id": j["workspace_id"]}, {"$inc": {"credits_balance": reserved}})
    if await _entry(j["workspace_id"], j["owner_id"], "capture", -actual, f"{base}:capture", job_id=j["id"],
                    note=f"Charged for {actual} credits of narration"):
        await db.workspaces.update_one({"id": j["workspace_id"]}, {"$inc": {"credits_balance": -actual}})
    if actual != actual_credits:
        await db.jobs.update_one({"id": j["id"]}, {"$set": {"final_credits": actual}})
    return True


async def release(job, reason: str):
    j = await db.jobs.find_one_and_update({"id": job["id"], "reservation_state": "held"},
                                          {"$set": {"reservation_state": "released", "final_credits": 0}})
    if not j:
        return False
    if await is_unlimited(j["workspace_id"]):
        await _entry(j["workspace_id"], j["owner_id"], "release", 0, f"job:{j['id']}:a{j['attempt_count']}:release",
                     job_id=j["id"], note=reason[:200])
        return True
    if await _entry(j["workspace_id"], j["owner_id"], "release", j["reserved_credits"],
                    f"job:{j['id']}:a{j['attempt_count']}:release", job_id=j["id"], note=reason[:200]):
        await db.workspaces.update_one({"id": j["workspace_id"]}, {"$inc": {"credits_balance": j["reserved_credits"]}})
    return True
