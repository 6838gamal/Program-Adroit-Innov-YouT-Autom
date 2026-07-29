import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.asset.asset import Asset
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_asset_repository import SQLAssetRepository
from interfaces.schemas.asset_schemas import AssetResponse, AssetListResponse
from shared.exceptions import AssetNotFoundError
from shared.value_objects import AssetType
from config.settings import settings

router = APIRouter(prefix="/assets", tags=["assets"])

MIME_TO_TYPE = {
    "image/jpeg": AssetType.IMAGE, "image/png": AssetType.IMAGE,
    "image/gif": AssetType.IMAGE, "image/webp": AssetType.IMAGE,
    "video/mp4": AssetType.VIDEO, "video/quicktime": AssetType.VIDEO,
    "video/x-msvideo": AssetType.VIDEO, "video/webm": AssetType.VIDEO,
    "audio/mpeg": AssetType.AUDIO, "audio/wav": AssetType.AUDIO,
    "audio/ogg": AssetType.AUDIO, "audio/mp4": AssetType.AUDIO,
}


def get_asset_repo(session: AsyncSession = Depends(get_db)) -> SQLAssetRepository:
    return SQLAssetRepository(session)


@router.get("", response_model=AssetListResponse)
async def list_assets(
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    repo: SQLAssetRepository = Depends(get_asset_repo),
):
    assets = await repo.list_all(type=type, search=search, limit=limit, offset=offset)
    total = await repo.count()
    return AssetListResponse(
        items=[AssetResponse(**a.to_dict()) for a in assets],
        total=total,
    )


@router.post("", response_model=AssetResponse, status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    repo: SQLAssetRepository = Depends(get_asset_repo),
):
    mime = file.content_type or "application/octet-stream"
    asset_type = MIME_TO_TYPE.get(mime, AssetType.IMAGE)

    asset_id = uuid.uuid4()
    ext = Path(file.filename or "file").suffix
    relative_path = f"uploads/{asset_id}{ext}"
    dest = settings.MEDIA_DIR / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = dest.stat().st_size
    display_name = name or file.filename or str(asset_id)

    asset = Asset(
        id=asset_id,
        name=display_name,
        type=asset_type,
        file_path=str(dest),
        file_size=file_size,
        mime_type=mime,
    )
    await repo.save(asset)
    return AssetResponse(**asset.to_dict())


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: uuid.UUID,
    repo: SQLAssetRepository = Depends(get_asset_repo),
):
    asset = await repo.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse(**asset.to_dict())


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: uuid.UUID,
    repo: SQLAssetRepository = Depends(get_asset_repo),
):
    asset = await repo.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await repo.delete(asset_id)
