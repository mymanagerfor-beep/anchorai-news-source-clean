import os
import uuid
import time
import logging
import asyncio
from collections import defaultdict, deque, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("anchorai")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]


def env_int(name, default):
    return int(os.environ.get(name, default))


def env_float(name, default):
    return float(os.environ.get(name, default))


class Cfg:
    APP_URL = os.environ.get("APP_URL", "").rstrip("/")
    API_PUBLIC_URL = (os.environ.get("API_PUBLIC_URL") or os.environ.get("APP_URL", "")).rstrip("/")
    STORAGE_PREFIX = os.environ.get("STORAGE_PREFIX", "anchorai")
    MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 10)
    MIN_PORTRAIT_PX = env_int("MIN_PORTRAIT_PX", 512)
    MAX_NARRATION_SECONDS = env_int("MAX_NARRATION_SECONDS", 60)
    GU_CHARS_PER_SECOND = env_float("GU_CHARS_PER_SECOND", 13.0)
    CREDITS_PER_SECOND = env_float("CREDITS_PER_SECOND", 1.0)
    MIN_CREDITS_PER_VIDEO = env_int("MIN_CREDITS_PER_VIDEO", 10)
    RESERVE_BUFFER = env_float("RESERVE_BUFFER", 0.15)
    TRIAL_CREDITS = env_int("TRIAL_CREDITS", 30)
    SESSION_HOURS = env_int("SESSION_HOURS", 12)
    CONSENT_VERSION = "2026-06-v1"


CONSENT_TEXT = (
    "I confirm that I have the legal right and the explicit permission of the person shown in this portrait "
    "to animate their likeness and to generate synthetic speech in their apparent voice using AI. "
    "I will not use generated videos to deceive viewers about what this person said, endorsed or attended, "
    "and every video will carry a visible AI-generated disclosure. Public figures and politicians may only be "
    "animated by that person themselves."
)
CONSENT_BASES = {
    "self": "This is me",
    "employee_release": "Employee or talent with a signed release",
    "licensed_presenter": "Contracted or licensed presenter",
}


def now_dt():
    return datetime.now(timezone.utc)


def now():
    return now_dt().isoformat()


def uid():
    return str(uuid.uuid4())


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


_rate = defaultdict(deque)


def rate_limit(key: str, limit: int, window: int):
    q = _rate[key]
    t = time.monotonic()
    while q and q[0] < t - window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests. Please wait a moment and try again.")
    q.append(t)


async def audit(workspace_id, user_id, action, target=None, meta=None):
    await db.audit_events.insert_one({
        "id": uid(), "workspace_id": workspace_id, "user_id": user_id, "action": action,
        "target": target, "meta": meta or {}, "created_at": now(),
    })


# Private object storage: "emergent" (managed) or "local" (server disk, for cPanel/VPS). Access only via backend.
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "emergent").lower()
LOCAL_STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR") or Path(__file__).parent / "data" / "storage").resolve()


def _local_path(path: str) -> Path:
    p = (LOCAL_STORAGE_DIR / path).resolve()
    if LOCAL_STORAGE_DIR not in p.parents:
        raise ValueError("Invalid storage path")
    return p

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
_storage_key = None
_cache = OrderedDict()
_CACHE_MAX = 300 * 1024 * 1024


def init_storage(force=False):
    global _storage_key
    if STORAGE_BACKEND == "local":
        LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        return "local"
    if _storage_key and not force:
        return _storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ["EMERGENT_LLM_KEY"]}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if STORAGE_BACKEND == "local":
        p = _local_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        return {"path": path, "size": len(data)}
    for attempt in range(2):
        resp = requests.put(f"{STORAGE_URL}/objects/{path}",
                            headers={"X-Storage-Key": init_storage(force=attempt > 0), "Content-Type": content_type},
                            data=data, timeout=180)
        if resp.status_code == 404 and attempt == 0:
            continue
        resp.raise_for_status()
        return resp.json()


def get_object(path: str) -> bytes:
    if path in _cache:
        _cache.move_to_end(path)
        return _cache[path]
    if STORAGE_BACKEND == "local":
        return _local_path(path).read_bytes()
    for attempt in range(2):
        resp = requests.get(f"{STORAGE_URL}/objects/{path}",
                            headers={"X-Storage-Key": init_storage(force=attempt > 0)}, timeout=120)
        if resp.status_code == 404 and attempt == 0:
            continue
        resp.raise_for_status()
        data = resp.content
        _cache[path] = data
        while sum(len(v) for v in _cache.values()) > _CACHE_MAX and len(_cache) > 1:
            _cache.popitem(last=False)
        return data


def storage_path(workspace_id: str, kind: str, ext: str) -> str:
    return f"{Cfg.STORAGE_PREFIX}/{workspace_id}/{kind}/{uid()}.{ext}"


async def store_media(workspace_id, asset_type, data: bytes, mime, ext, project_id=None, job_id=None, meta=None):
    path = storage_path(workspace_id, asset_type, ext)
    try:
        res = await asyncio.to_thread(put_object, path, data, mime)
    except Exception as e:
        logger.error("storage upload failed: %s", type(e).__name__)
        raise StorageError("Could not save the file to private storage. Please try again.")
    doc = {
        "id": uid(), "workspace_id": workspace_id, "project_id": project_id, "job_id": job_id,
        "asset_type": asset_type, "storage_key": res["path"], "mime_type": mime, "file_size": len(data),
        "retention_status": "active", "is_deleted": False, "created_at": now(), **(meta or {}),
    }
    await db.media_assets.insert_one(doc)
    doc.pop("_id", None)
    return doc


class StorageError(Exception):
    pass
