from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

from core import db, client, init_storage, now, uid  # noqa: E402
import auth  # noqa: E402
import anchors  # noqa: E402
import channels  # noqa: E402
import projects  # noqa: E402
import billing  # noqa: E402
import admin  # noqa: E402
import worker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("anchorai")

app = FastAPI(title="AnchorAI News API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
for r in (auth.router, anchors.router, channels.router, projects.router, billing.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
async def health():
    await db.command("ping")
    return {"ok": True, "time": now()}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


app.add_middleware(CORSMiddleware, allow_credentials=False,
                   allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


async def ensure_indexes():
    from bootstrap import INDEXES
    for coll, keys, opts in INDEXES:
        await db[coll].create_index(keys, **opts)


async def seed_admin():
    email = os.environ["ADMIN_EMAIL"].lower()
    pw = os.environ["ADMIN_PASSWORD"]
    u = await db.users.find_one({"email": email})
    if not u:
        user = {"id": uid(), "email": email, "name": "Platform Admin", "password_hash": auth.hash_password(pw),
                "role": "admin", "status": "active", "email_verified": True, "auth_identifier": f"password:{email}",
                "created_at": now()}
        await db.users.insert_one(user)
        await auth.create_workspace(user["id"], "Admin Newsroom")
    elif not auth.verify_password(pw, u["password_hash"]):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": auth.hash_password(pw)}})
    admin_ids = [a["id"] async for a in db.users.find({"role": "admin"}, {"id": 1})]
    await db.workspaces.update_many({"owner_id": {"$in": admin_ids}},
                                    {"$set": {"unlimited_credits": True, "plan_id": "admin_unlimited"}})


@app.on_event("startup")
async def startup():
    await ensure_indexes()
    await seed_admin()
    try:
        await asyncio.to_thread(init_storage)
    except Exception as e:
        log.error("Storage init failed: %s", type(e).__name__)
    if os.environ.get("RUN_WORKER", "1") == "1":
        app.state.worker = asyncio.create_task(worker.worker_loop())


@app.on_event("shutdown")
async def shutdown():
    client.close()
