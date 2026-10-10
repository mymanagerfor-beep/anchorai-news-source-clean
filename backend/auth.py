import os
import secrets
import hashlib
from datetime import timedelta, datetime

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from core import db, now, now_dt, uid, Cfg, rate_limit, client_ip, audit
from emailer import send_verification, send_reset

router = APIRouter(prefix="/api/v1")
ALG = "HS256"


def secret():
    return os.environ["JWT_SECRET"]


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def sign(payload: dict, minutes: int) -> str:
    return jwt.encode({**payload, "exp": now_dt() + timedelta(minutes=minutes)}, secret(), algorithm=ALG)


def unsign(token: str, typ: str) -> dict:
    try:
        data = jwt.decode(token, secret(), algorithms=[ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Link or session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    if data.get("type") != typ:
        raise HTTPException(401, "Invalid token type")
    return data


def public_user(u):
    return {k: u.get(k) for k in ("id", "email", "name", "role", "email_verified", "status", "created_at",
                                   "current_workspace_id")}


async def create_workspace(user_id, name):
    owner = await db.users.find_one({"id": user_id}, {"role": 1})
    unlimited = bool(owner and owner.get("role") == "admin")
    ws = {"id": uid(), "name": name.strip()[:80] or "My Newsroom", "owner_id": user_id,
          "plan_id": "admin_unlimited" if unlimited else "credits_payg", "credits_balance": 0,
          "unlimited_credits": unlimited, "created_at": now()}
    await db.workspaces.insert_one(ws)
    await db.workspace_memberships.insert_one({"id": uid(), "workspace_id": ws["id"], "user_id": user_id,
                                               "role": "owner", "status": "active", "created_at": now()})
    await db.users.update_one({"id": user_id}, {"$set": {"current_workspace_id": ws["id"]}})
    ws.pop("_id", None)
    return ws


async def start_session(user, request: Request):
    sid = uid()
    expires = now_dt() + timedelta(hours=Cfg.SESSION_HOURS)
    await db.sessions.insert_one({"id": sid, "user_id": user["id"], "created_at": now(), "expires_at": expires,
                                  "revoked": False, "ip": client_ip(request)})
    token = sign({"sub": user["id"], "sid": sid, "type": "access"}, Cfg.SESSION_HOURS * 60)
    return {"token": token, "expires_at": expires.isoformat(), "user": public_user(user)}


async def get_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    data = unsign(auth[7:], "access")
    sess = await db.sessions.find_one({"id": data.get("sid")}, {"_id": 0})
    if not sess or sess["revoked"]:
        raise HTTPException(401, "Session revoked. Please sign in again.")
    user = await db.users.find_one({"id": data["sub"]}, {"_id": 0, "password_hash": 0})
    if not user or user.get("status") != "active":
        raise HTTPException(401, "Account not active")
    user["_sid"] = sess["id"]
    return user


async def get_ctx(user=Depends(get_user)):
    ws_id = user.get("current_workspace_id")
    mem = await db.workspace_memberships.find_one({"workspace_id": ws_id, "user_id": user["id"], "status": "active"})
    if not mem:
        raise HTTPException(403, "No active workspace")
    ws = await db.workspaces.find_one({"id": ws_id}, {"_id": 0})
    return {"user": user, "ws": ws, "role": mem["role"], "ws_id": ws_id}


async def require_admin(user=Depends(get_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str = Field(min_length=1, max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenIn(BaseModel):
    token: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


async def issue_email_token(user, kind, hours):
    raw = secrets.token_urlsafe(32)
    await db.email_tokens.insert_one({"token_hash": hashlib.sha256(raw.encode()).hexdigest(), "user_id": user["id"],
                                      "kind": kind, "used": False, "expires_at": now_dt() + timedelta(hours=hours)})
    return raw


async def consume_email_token(raw, kind):
    rec = await db.email_tokens.find_one_and_update(
        {"token_hash": hashlib.sha256(raw.encode()).hexdigest(), "kind": kind, "used": False,
         "expires_at": {"$gt": now_dt()}}, {"$set": {"used": True}})
    if not rec:
        raise HTTPException(400, "This link is invalid or has expired. Request a new one.")
    return rec


async def send_verify_mail(user):
    raw = await issue_email_token(user, "verify", 24)
    return await send_verification(user["email"], user["name"], f"{Cfg.APP_URL}/verify-email?token={raw}")


@router.post("/auth/register")
async def register(body: RegisterIn, request: Request):
    rate_limit(f"register:{client_ip(request)}", 5, 600)
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "An account with this email already exists")
    user = {"id": uid(), "email": email, "name": body.name.strip(), "password_hash": hash_password(body.password),
            "role": "user", "status": "active", "email_verified": False, "auth_identifier": f"password:{email}",
            "created_at": now()}
    await db.users.insert_one(user)
    ws = await create_workspace(user["id"], body.workspace_name)
    user["current_workspace_id"] = ws["id"]
    await audit(ws["id"], user["id"], "user.registered")
    sent = await send_verify_mail(user)
    out = await start_session(user, request)
    out["verification_email_sent"] = sent
    return out


@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    email = body.email.lower()
    ident = f"{client_ip(request)}:{email}"
    att = await db.login_attempts.find_one({"identifier": ident})
    if att and att.get("count", 0) >= 5 and att.get("locked_until") and att["locked_until"] > now_dt().replace(tzinfo=None):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    user = await db.users.find_one({"email": email})
    if not user or user.get("status") != "active" or not verify_password(body.password, user["password_hash"]):
        await db.login_attempts.update_one({"identifier": ident}, {"$inc": {"count": 1},
                                           "$set": {"locked_until": (now_dt() + timedelta(minutes=15)).replace(tzinfo=None)}},
                                           upsert=True)
        raise HTTPException(401, "Invalid email or password")
    await db.login_attempts.delete_one({"identifier": ident})
    user.pop("_id", None)
    return await start_session(user, request)


@router.post("/auth/logout")
async def logout(user=Depends(get_user)):
    await db.sessions.update_one({"id": user["_sid"]}, {"$set": {"revoked": True, "revoked_at": now()}})
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_all(user=Depends(get_user)):
    await db.sessions.update_many({"user_id": user["id"]}, {"$set": {"revoked": True, "revoked_at": now()}})
    return {"ok": True}


@router.get("/auth/me")
async def me(user=Depends(get_user)):
    return public_user(user)


@router.post("/auth/verify-email")
async def verify_email(body: TokenIn):
    from ledger import grant
    rec = await consume_email_token(body.token, "verify")
    user = await db.users.find_one({"id": rec["user_id"]}, {"_id": 0})
    await db.users.update_one({"id": user["id"]}, {"$set": {"email_verified": True}})
    owned = await db.workspaces.find_one({"owner_id": user["id"]}, {"_id": 0}, sort=[("created_at", 1)])
    if owned:
        await grant(owned["id"], user["id"], "trial", Cfg.TRIAL_CREDITS, f"trial:{user['id']}", note="Trial credits")
    return {"ok": True}


@router.post("/auth/resend-verification")
async def resend_verification(user=Depends(get_user)):
    rate_limit(f"resend:{user['id']}", 3, 600)
    if user.get("email_verified"):
        return {"ok": True, "already_verified": True}
    sent = await send_verify_mail(user)
    if not sent:
        raise HTTPException(503, "Email is temporarily unavailable. Please try again later.")
    return {"ok": True}


@router.post("/auth/forgot-password")
async def forgot(body: ForgotIn, request: Request):
    rate_limit(f"forgot:{client_ip(request)}", 5, 600)
    user = await db.users.find_one({"email": body.email.lower(), "status": "active"}, {"_id": 0})
    if user:
        raw = await issue_email_token(user, "reset", 1)
        await send_reset(user["email"], user["name"], f"{Cfg.APP_URL}/reset-password?token={raw}")
    return {"ok": True, "message": "If an account exists for this email, a reset link has been sent."}


@router.post("/auth/reset-password")
async def reset(body: ResetIn):
    rec = await consume_email_token(body.token, "reset")
    await db.users.update_one({"id": rec["user_id"]}, {"$set": {"password_hash": hash_password(body.password)}})
    await db.sessions.update_many({"user_id": rec["user_id"]}, {"$set": {"revoked": True}})
    await audit(None, rec["user_id"], "user.password_reset")
    return {"ok": True}


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/workspaces")
async def new_workspace(body: WorkspaceIn, user=Depends(get_user)):
    ws = await create_workspace(user["id"], body.name)
    await audit(ws["id"], user["id"], "workspace.created")
    return ws


@router.get("/workspaces")
async def list_workspaces(user=Depends(get_user)):
    mems = await db.workspace_memberships.find({"user_id": user["id"], "status": "active"}, {"_id": 0}).to_list(100)
    ids = [m["workspace_id"] for m in mems]
    wss = await db.workspaces.find({"id": {"$in": ids}}, {"_id": 0}).to_list(100)
    return {"items": wss, "current_workspace_id": user.get("current_workspace_id")}


@router.post("/workspaces/{ws_id}/switch")
async def switch_workspace(ws_id: str, user=Depends(get_user)):
    if not await db.workspace_memberships.find_one({"workspace_id": ws_id, "user_id": user["id"], "status": "active"}):
        raise HTTPException(404, "Workspace not found")
    await db.users.update_one({"id": user["id"]}, {"$set": {"current_workspace_id": ws_id}})
    return {"ok": True}


@router.get("/workspaces/current")
async def current_workspace(ctx=Depends(get_ctx)):
    members = await db.workspace_memberships.find({"workspace_id": ctx["ws_id"]}, {"_id": 0}).to_list(100)
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": [m["user_id"] for m in members]}},
                                                      {"_id": 0, "id": 1, "email": 1, "name": 1}).to_list(100)}
    return {**ctx["ws"], "role": ctx["role"],
            "members": [{**m, "email": users.get(m["user_id"], {}).get("email"),
                         "name": users.get(m["user_id"], {}).get("name")} for m in members]}


@router.get("/account")
async def account(ctx=Depends(get_ctx)):
    u = ctx["user"]
    sessions = await db.sessions.find({"user_id": u["id"], "revoked": False}, {"_id": 0, "id": 1, "created_at": 1,
                                                                                "expires_at": 1}).to_list(50)
    deletion = await db.deletion_requests.find({"user_id": u["id"]}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return {"user": public_user(u), "workspace": ctx["ws"], "role": ctx["role"], "active_sessions": len(sessions),
            "deletion_requests": deletion}


class DeleteAccountIn(BaseModel):
    password: str
    confirm: str


@router.post("/account/delete")
async def delete_account(body: DeleteAccountIn, ctx=Depends(get_ctx)):
    u = await db.users.find_one({"id": ctx["user"]["id"]})
    if body.confirm != "DELETE" or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(400, "Type DELETE and enter your current password to confirm")
    owned = await db.workspaces.find({"owner_id": u["id"]}, {"_id": 0, "id": 1}).to_list(100)
    ws_ids = [w["id"] for w in owned]
    await db.anchors.update_many({"workspace_id": {"$in": ws_ids}, "status": {"$ne": "deleted"}},
                                 {"$set": {"status": "deleted", "deleted_at": now()}})
    await db.media_assets.update_many({"workspace_id": {"$in": ws_ids}},
                                      {"$set": {"is_deleted": True, "retention_status": "pending_purge"}})
    await db.jobs.update_many({"workspace_id": {"$in": ws_ids}, "status": {"$in": ["queued", "validating", "generating",
                                                                                   "retrieving", "rendering"]}},
                              {"$set": {"cancel_requested": True}})
    await db.users.update_one({"id": u["id"]}, {"$set": {"status": "deleted", "email": f"deleted+{u['id']}@invalid",
                                                         "deleted_at": now()}})
    await db.sessions.update_many({"user_id": u["id"]}, {"$set": {"revoked": True}})
    await db.deletion_requests.insert_one({"id": uid(), "user_id": u["id"], "workspace_ids": ws_ids,
                                           "type": "account_deletion", "status": "completed", "created_at": now()})
    await audit(ctx["ws_id"], u["id"], "account.deleted")
    return {"ok": True}


class DataDeletionIn(BaseModel):
    scope: str = Field(pattern="^(all_media|anchors|videos)$")
    note: str = Field("", max_length=500)


@router.post("/account/data-deletion")
async def data_deletion(body: DataDeletionIn, ctx=Depends(get_ctx)):
    ws = ctx["ws_id"]
    if body.scope in ("all_media", "anchors"):
        await db.anchors.update_many({"workspace_id": ws, "status": {"$ne": "deleted"}},
                                     {"$set": {"status": "deleted", "deleted_at": now()}})
        await db.media_assets.update_many({"workspace_id": ws, "asset_type": {"$in": ["portrait", "portrait_provider"]}},
                                          {"$set": {"is_deleted": True, "retention_status": "pending_purge"}})
    if body.scope in ("all_media", "videos"):
        await db.media_assets.update_many({"workspace_id": ws, "asset_type": {"$nin": ["portrait", "portrait_provider",
                                                                                         "logo"]}},
                                          {"$set": {"is_deleted": True, "retention_status": "pending_purge"}})
    rec = {"id": uid(), "user_id": ctx["user"]["id"], "workspace_ids": [ws], "type": f"data_deletion:{body.scope}",
           "note": body.note, "status": "completed", "created_at": now()}
    await db.deletion_requests.insert_one(rec)
    await audit(ws, ctx["user"]["id"], "data.deletion_requested", meta={"scope": body.scope})
    rec.pop("_id", None)
    return rec
