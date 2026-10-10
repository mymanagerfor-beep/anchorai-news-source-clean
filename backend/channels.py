from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from core import db, now, uid, audit, store_media, StorageError
from auth import get_ctx
from anchors import validate_image, file_url

router = APIRouter(prefix="/api/v1")
HEX = r"^#[0-9A-Fa-f]{6}$"


class SubtitleStyle(BaseModel):
    enabled: bool = True
    size: int = Field(42, ge=28, le=64)
    color: str = Field("#FFFFFF", pattern=HEX)
    background: str = Field("box", pattern="^(box|outline)$")
    position: str = Field("bottom", pattern="^(bottom|top)$")


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    primary_color: str = Field("#DC2626", pattern=HEX)
    secondary_color: str = Field("#0F172A", pattern=HEX)
    logo_corner: str = Field("top-right", pattern="^(top-left|top-right)$")
    ticker_label: str = Field("તાજા સમાચાર", max_length=24)
    default_ticker: str = Field("", max_length=600)
    subtitle_style: SubtitleStyle = SubtitleStyle()
    default_template: str = Field("breaking_news", pattern="^breaking_news$")


class ChannelPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    primary_color: Optional[str] = Field(None, pattern=HEX)
    secondary_color: Optional[str] = Field(None, pattern=HEX)
    logo_corner: Optional[str] = Field(None, pattern="^(top-left|top-right)$")
    ticker_label: Optional[str] = Field(None, max_length=24)
    default_ticker: Optional[str] = Field(None, max_length=600)
    subtitle_style: Optional[SubtitleStyle] = None


def channel_out(c):
    c = {k: v for k, v in c.items() if k != "_id"}
    c["logo_url"] = file_url(c["logo_storage_key"], c["logo_mime"]) if c.get("logo_storage_key") else None
    return c


async def get_channel(ctx, cid):
    c = await db.channels.find_one({"id": cid, "workspace_id": ctx["ws_id"], "deleted": {"$ne": True}}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Channel not found")
    return c


@router.get("/channels")
async def list_channels(ctx=Depends(get_ctx)):
    items = await db.channels.find({"workspace_id": ctx["ws_id"], "deleted": {"$ne": True}}, {"_id": 0}) \
        .sort("created_at", -1).to_list(100)
    return {"items": [channel_out(c) for c in items]}


@router.post("/channels")
async def create_channel(body: ChannelIn, ctx=Depends(get_ctx)):
    c = {"id": uid(), "workspace_id": ctx["ws_id"], **body.model_dump(), "logo_asset_id": None,
         "logo_storage_key": None, "logo_mime": None, "created_at": now()}
    await db.channels.insert_one(c)
    await audit(ctx["ws_id"], ctx["user"]["id"], "channel.created", c["id"])
    return channel_out(c)


@router.patch("/channels/{cid}")
async def update_channel(cid: str, body: ChannelPatch, ctx=Depends(get_ctx)):
    await get_channel(ctx, cid)
    upd = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if upd:
        await db.channels.update_one({"id": cid}, {"$set": upd})
    return channel_out(await get_channel(ctx, cid))


@router.post("/channels/{cid}/logo")
async def upload_logo(cid: str, file: UploadFile = File(...), ctx=Depends(get_ctx)):
    await get_channel(ctx, cid)
    data = await file.read(2 * 1024 * 1024 + 1)
    mime, img = validate_image(data, 2)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    try:
        asset = await store_media(ctx["ws_id"], "logo", data, mime, ext, meta={"channel_id": cid,
                                                                             "dimensions": [img.width, img.height]})
    except StorageError as e:
        raise HTTPException(502, str(e))
    await db.channels.update_one({"id": cid}, {"$set": {"logo_asset_id": asset["id"],
                                                        "logo_storage_key": asset["storage_key"], "logo_mime": mime,
                                                        "logo_has_alpha": img.mode in ("RGBA", "LA", "P")}})
    return channel_out(await get_channel(ctx, cid))


@router.delete("/channels/{cid}")
async def delete_channel(cid: str, ctx=Depends(get_ctx)):
    await get_channel(ctx, cid)
    await db.channels.update_one({"id": cid}, {"$set": {"deleted": True, "deleted_at": now()}})
    await audit(ctx["ws_id"], ctx["user"]["id"], "channel.deleted", cid)
    return {"ok": True}
