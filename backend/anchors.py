import asyncio
import hashlib
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import Response
from PIL import Image

from core import db, now, uid, Cfg, CONSENT_TEXT, CONSENT_BASES, audit, store_media, get_object, rate_limit, StorageError
from auth import get_ctx, sign, unsign

router = APIRouter(prefix="/api/v1")

SIGNATURES = {"image/jpeg": [b"\xff\xd8\xff"], "image/png": [b"\x89PNG\r\n\x1a\n"]}
FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def sniff_image(data: bytes):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes, max_mb: int, min_px: int = 0):
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {max_mb} MB")
    if len(data) < 100:
        raise HTTPException(400, "File is empty or malformed")
    mime = sniff_image(data)
    if not mime:
        raise HTTPException(415, "Unsupported file type. Use JPG, PNG or WebP.")
    try:
        Image.open(BytesIO(data)).verify()
        img = Image.open(BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(400, "The image file is corrupted or malformed")
    if FORMAT_MIME.get(img.format) != mime:
        raise HTTPException(400, "File contents do not match the declared image format")
    if min_px and min(img.size) < min_px:
        raise HTTPException(400, f"Portrait is too small. The short side must be at least {min_px} px.")
    return mime, img


def file_url(path: str, mime: str, minutes=30, download_name=None):
    t = sign({"type": "file", "p": path, "m": mime, "dn": download_name}, minutes)
    return f"{Cfg.API_PUBLIC_URL}/api/v1/files/signed?t={t}"


@router.get("/files/signed")
async def signed_file(request: Request, t: str = Query(...)):
    data = unsign(t, "file")
    asset = await db.media_assets.find_one({"storage_key": data["p"], "is_deleted": False}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "File not found or deleted")
    try:
        blob = await asyncio.to_thread(get_object, data["p"])
    except Exception:
        raise HTTPException(502, "Could not read the file from storage")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=300"}
    if data.get("dn"):
        headers["Content-Disposition"] = f'attachment; filename="{data["dn"]}"'
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        s, _, e = rng[6:].partition("-")
        start = int(s or 0)
        end = min(int(e) if e else len(blob) - 1, len(blob) - 1)
        if start >= len(blob):
            raise HTTPException(416, "Range not satisfiable")
        headers["Content-Range"] = f"bytes {start}-{end}/{len(blob)}"
        return Response(blob[start:end + 1], 206, headers=headers, media_type=data["m"])
    return Response(blob, headers=headers, media_type=data["m"])


def anchor_out(a, consent=None):
    a = {k: v for k, v in a.items() if k != "_id"}
    a["image_url"] = file_url(a["storage_key"], a["mime_type"]) if a["status"] != "deleted" else None
    a["usable"] = a["status"] == "active" and a.get("consent_status") == "granted"
    if consent:
        a["consent"] = consent
    return a


@router.get("/consent/text")
async def consent_text():
    return {"version": Cfg.CONSENT_VERSION, "text": CONSENT_TEXT, "bases": CONSENT_BASES}


@router.post("/anchors/upload-url")
async def upload_url(ctx=Depends(get_ctx)):
    # Object storage has no presigned uploads; the backend receives and validates the file directly.
    return {"upload_url": "/api/v1/anchors", "method": "POST", "encoding": "multipart/form-data",
            "max_bytes": Cfg.MAX_UPLOAD_MB * 1024 * 1024, "accepted": ["image/jpeg", "image/png", "image/webp"],
            "min_short_side_px": Cfg.MIN_PORTRAIT_PX}


@router.post("/anchors")
async def create_anchor(file: UploadFile = File(...), display_name: str = Form(...), description: str = Form(""),
                        authorized_by: str = Form(...), consent_basis: str = Form(...),
                        consent_confirmed: bool = Form(...), consent_version: str = Form(...), ctx=Depends(get_ctx)):
    rate_limit(f"upload:{ctx['user']['id']}", 20, 3600)
    if not consent_confirmed:
        raise HTTPException(400, "You must confirm the consent statement")
    if consent_basis not in CONSENT_BASES:
        raise HTTPException(400, "Choose a valid authorization basis")
    if consent_version != Cfg.CONSENT_VERSION:
        raise HTTPException(409, "Consent text has changed. Please review it again.")
    if not display_name.strip() or len(display_name) > 80 or not authorized_by.strip():
        raise HTTPException(400, "Display name and likeness owner are required")
    data = await file.read(Cfg.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    mime, img = validate_image(data, Cfg.MAX_UPLOAD_MB, Cfg.MIN_PORTRAIT_PX)
    prov = img.convert("RGB")
    prov.thumbnail((1280, 1280))
    buf = BytesIO()
    prov.save(buf, "JPEG", quality=88)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    try:
        orig = await store_media(ctx["ws_id"], "portrait", data, mime, ext)
        pcopy = await store_media(ctx["ws_id"], "portrait_provider", buf.getvalue(), "image/jpeg", "jpg")
    except StorageError as e:
        raise HTTPException(502, str(e))
    anchor_id = uid()
    consent = {"id": uid(), "user_id": ctx["user"]["id"], "workspace_id": ctx["ws_id"], "asset_id": anchor_id,
               "confirmed": True, "consent_version": Cfg.CONSENT_VERSION,
               "consent_text_sha256": hashlib.sha256(CONSENT_TEXT.encode()).hexdigest(), "basis": consent_basis,
               "authorized_by": authorized_by.strip()[:120], "revoked": False, "created_at": now()}
    await db.consents.insert_one(consent)
    a = {"id": anchor_id, "workspace_id": ctx["ws_id"], "display_name": display_name.strip(),
         "description": description.strip()[:500], "authorized_by": authorized_by.strip()[:120],
         "storage_key": orig["storage_key"], "provider_storage_key": pcopy["storage_key"], "mime_type": mime,
         "file_size": len(data), "width": img.width, "height": img.height, "consent_id": consent["id"],
         "consent_status": "granted", "status": "active", "created_by": ctx["user"]["id"], "created_at": now(),
         "deleted_at": None}
    await db.anchors.insert_one(a)
    await db.media_assets.update_many({"storage_key": {"$in": [orig["storage_key"], pcopy["storage_key"]]}},
                                      {"$set": {"anchor_id": anchor_id}})
    await audit(ctx["ws_id"], ctx["user"]["id"], "anchor.created", anchor_id, {"basis": consent_basis})
    await audit(ctx["ws_id"], ctx["user"]["id"], "consent.granted", anchor_id, {"version": Cfg.CONSENT_VERSION})
    return anchor_out(a)


@router.get("/anchors")
async def list_anchors(ctx=Depends(get_ctx), include_deleted: bool = False):
    q = {"workspace_id": ctx["ws_id"]}
    if not include_deleted:
        q["status"] = {"$ne": "deleted"}
    items = await db.anchors.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": [anchor_out(a) for a in items]}


async def get_anchor(ctx, anchor_id):
    a = await db.anchors.find_one({"id": anchor_id, "workspace_id": ctx["ws_id"]}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Anchor not found")
    return a


@router.get("/anchors/{anchor_id}")
async def anchor_detail(anchor_id: str, ctx=Depends(get_ctx)):
    a = await get_anchor(ctx, anchor_id)
    consent = await db.consents.find_one({"id": a["consent_id"]}, {"_id": 0})
    history = await db.audit_events.find({"workspace_id": ctx["ws_id"], "target": anchor_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(50)
    out = anchor_out(a, consent)
    out["history"] = history
    return out


async def fail_jobs_for_anchor(anchor_id, reason):
    await db.jobs.update_many({"anchor_id": anchor_id, "status": {"$in": ["queued", "validating", "generating"]}},
                              {"$set": {"anchor_blocked": reason}})


@router.post("/anchors/{anchor_id}/revoke-consent")
async def revoke(anchor_id: str, ctx=Depends(get_ctx)):
    a = await get_anchor(ctx, anchor_id)
    if a["consent_status"] == "revoked":
        return anchor_out(a)
    await db.consents.update_one({"id": a["consent_id"]}, {"$set": {"revoked": True, "revoked_at": now(),
                                                                    "revoked_by": ctx["user"]["id"]}})
    await db.anchors.update_one({"id": anchor_id}, {"$set": {"consent_status": "revoked", "status": "revoked"}})
    await fail_jobs_for_anchor(anchor_id, "consent_revoked")
    await audit(ctx["ws_id"], ctx["user"]["id"], "consent.revoked", anchor_id)
    return anchor_out(await get_anchor(ctx, anchor_id))


@router.delete("/anchors/{anchor_id}")
async def delete_anchor(anchor_id: str, ctx=Depends(get_ctx)):
    a = await get_anchor(ctx, anchor_id)
    await db.anchors.update_one({"id": anchor_id}, {"$set": {"status": "deleted", "consent_status": "revoked",
                                                             "deleted_at": now()}})
    await db.consents.update_one({"id": a["consent_id"], "revoked": False}, {"$set": {"revoked": True,
                                                                                      "revoked_at": now()}})
    await db.media_assets.update_many({"anchor_id": anchor_id}, {"$set": {"is_deleted": True,
                                                                         "retention_status": "pending_purge",
                                                                         "deleted_at": now()}})
    await fail_jobs_for_anchor(anchor_id, "anchor_deleted")
    await audit(ctx["ws_id"], ctx["user"]["id"], "anchor.deleted", anchor_id)
    return {"ok": True}


async def load_anchor_bytes(anchor, provider=True):
    return await asyncio.to_thread(get_object, anchor["provider_storage_key" if provider else "storage_key"])
