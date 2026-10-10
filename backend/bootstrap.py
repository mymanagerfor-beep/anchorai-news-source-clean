"""Synchronous bootstrap (indexes + admin seed). Used by cPanel/Passenger and `python manage.py init`."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from pymongo import MongoClient, ASCENDING, DESCENDING  # noqa: E402

# (collection, keys, options) — single source of truth for "migrations"
INDEXES = [
    ("users", [("email", ASCENDING)], {"unique": True}),
    ("users", [("id", ASCENDING)], {"unique": True}),
    ("sessions", [("id", ASCENDING)], {"unique": True}),
    ("sessions", [("expires_at", ASCENDING)], {"expireAfterSeconds": 0}),
    ("email_tokens", [("token_hash", ASCENDING)], {"unique": True}),
    ("email_tokens", [("expires_at", ASCENDING)], {"expireAfterSeconds": 0}),
    ("login_attempts", [("identifier", ASCENDING)], {}),
    ("workspaces", [("id", ASCENDING)], {"unique": True}),
    ("workspace_memberships", [("workspace_id", ASCENDING), ("user_id", ASCENDING)], {"unique": True}),
    ("anchors", [("workspace_id", ASCENDING), ("created_at", DESCENDING)], {}),
    ("anchors", [("id", ASCENDING)], {"unique": True}),
    ("consents", [("id", ASCENDING)], {"unique": True}),
    ("channels", [("workspace_id", ASCENDING), ("id", ASCENDING)], {}),
    ("projects", [("workspace_id", ASCENDING), ("updated_at", DESCENDING)], {}),
    ("projects", [("id", ASCENDING)], {"unique": True}),
    ("jobs", [("id", ASCENDING)], {"unique": True}),
    ("jobs", [("workspace_id", ASCENDING), ("idempotency_key", ASCENDING)], {"unique": True}),
    ("jobs", [("status", ASCENDING), ("lease_until", ASCENDING)], {}),
    ("media_assets", [("storage_key", ASCENDING)], {}),
    ("media_assets", [("workspace_id", ASCENDING), ("asset_type", ASCENDING)], {}),
    ("credit_ledger", [("idempotency_key", ASCENDING)], {"unique": True}),
    ("credit_ledger", [("workspace_id", ASCENDING), ("created_at", DESCENDING)], {}),
    ("payments", [("order_id", ASCENDING)], {"unique": True}),
    ("payments", [("upi_ref", ASCENDING)], {"unique": True, "partialFilterExpression": {"upi_ref": {"$type": "string"}}}),
    ("webhook_events", [("event_id", ASCENDING)], {"unique": True}),
    ("audit_events", [("workspace_id", ASCENDING), ("created_at", DESCENDING)], {}),
    ("voice_previews", [("voice", ASCENDING)], {"unique": True}),
]


def bootstrap_sync():
    import bcrypt
    from datetime import datetime, timezone
    import uuid
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for coll, keys, opts in INDEXES:
        db[coll].create_index(keys, **opts)
    email, pw = os.environ["ADMIN_EMAIL"].lower(), os.environ["ADMIN_PASSWORD"]
    u = db.users.find_one({"email": email})
    now = datetime.now(timezone.utc).isoformat()
    if not u:
        uid, wid = str(uuid.uuid4()), str(uuid.uuid4())
        db.users.insert_one({"id": uid, "email": email, "name": "Platform Admin", "role": "admin", "status": "active",
                             "password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode(),
                             "email_verified": True, "auth_identifier": f"password:{email}", "created_at": now,
                             "current_workspace_id": wid})
        db.workspaces.insert_one({"id": wid, "name": "Admin Newsroom", "owner_id": uid, "plan_id": "admin_unlimited",
                                  "credits_balance": 0, "unlimited_credits": True, "created_at": now})
        db.workspace_memberships.insert_one({"id": str(uuid.uuid4()), "workspace_id": wid, "user_id": uid,
                                             "role": "owner", "status": "active", "created_at": now})
    elif not bcrypt.checkpw(pw.encode(), u["password_hash"].encode()):
        db.users.update_one({"email": email}, {"$set": {"password_hash": bcrypt.hashpw(pw.encode(),
                                                                                       bcrypt.gensalt()).decode()}})
    admin_ids = [a["id"] for a in db.users.find({"role": "admin"}, {"id": 1})]
    db.workspaces.update_many({"owner_id": {"$in": admin_ids}},
                              {"$set": {"unlimited_credits": True, "plan_id": "admin_unlimited"}})
