import uuid
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.asset.asset import Asset
from infrastructure.database.models.asset_model import AssetModel
from shared.value_objects import AssetType


class SQLAssetRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, asset: Asset) -> None:
        existing = await self._session.get(AssetModel, str(asset.id))
        if existing:
            existing.name = asset.name
            existing.tags = asset.tags
            existing.metadata = asset.metadata
        else:
            self._session.add(AssetModel(
                id=str(asset.id),
                name=asset.name,
                type=asset.type.value,
                file_path=asset.file_path,
                file_size=asset.file_size,
                mime_type=asset.mime_type,
                duration=asset.duration,
                width=asset.width,
                height=asset.height,
                tags=asset.tags,
                category_id=str(asset.category_id) if asset.category_id else None,
                project_id=str(asset.project_id) if asset.project_id else None,
                is_global=asset.is_global,
                metadata_=asset.metadata,
                created_at=asset.created_at,
            ))
        await self._session.flush()

    async def get(self, asset_id: uuid.UUID) -> Optional[Asset]:
        row = await self._session.get(AssetModel, str(asset_id))
        return self._to_domain(row) if row else None

    async def list_all(
        self,
        type: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Asset]:
        q = select(AssetModel)
        if type:
            q = q.where(AssetModel.type == type)
        if search:
            q = q.where(AssetModel.name.ilike(f"%{search}%"))
        q = q.order_by(AssetModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(q)
        return [self._to_domain(r) for r in result.scalars()]

    async def count(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(AssetModel))
        return result.scalar() or 0

    async def delete(self, asset_id: uuid.UUID) -> None:
        row = await self._session.get(AssetModel, str(asset_id))
        if row:
            await self._session.delete(row)

    def _to_domain(self, row: AssetModel) -> Asset:
        a = Asset.__new__(Asset)
        a.id = uuid.UUID(row.id)
        a.name = row.name
        a.type = AssetType(row.type)
        a.file_path = row.file_path
        a.file_size = row.file_size or 0
        a.mime_type = row.mime_type or ""
        a.duration = row.duration
        a.width = row.width
        a.height = row.height
        a.tags = row.tags or []
        a.category_id = uuid.UUID(row.category_id) if row.category_id else None
        a.project_id = uuid.UUID(row.project_id) if row.project_id else None
        a.is_global = row.is_global
        a.metadata = row.metadata_ or {}
        a.created_at = row.created_at
        a.updated_at = row.created_at
        return a
