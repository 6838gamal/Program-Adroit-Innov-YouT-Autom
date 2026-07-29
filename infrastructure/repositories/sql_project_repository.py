import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.project.project import Project
from infrastructure.database.models.project_model import ProjectModel
from shared.value_objects import ProjectStatus, BrandColors


class SQLProjectRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, project: Project) -> None:
        existing = await self._session.get(ProjectModel, str(project.id))
        if existing:
            existing.title = project.title
            existing.description = project.description
            existing.script = project.script
            existing.tags = project.tags
            existing.status = project.status.value
            existing.template_id = str(project.template_id) if project.template_id else None
            existing.logo_asset_id = str(project.logo_asset_id) if project.logo_asset_id else None
            existing.brand_colors = project.brand_colors.to_dict()
            existing.settings = project.settings
            existing.updated_at = project.updated_at
        else:
            self._session.add(ProjectModel(
                id=str(project.id),
                title=project.title,
                description=project.description,
                script=project.script,
                tags=project.tags,
                status=project.status.value,
                template_id=str(project.template_id) if project.template_id else None,
                logo_asset_id=str(project.logo_asset_id) if project.logo_asset_id else None,
                brand_colors=project.brand_colors.to_dict(),
                settings=project.settings,
                created_at=project.created_at,
                updated_at=project.updated_at,
            ))
        await self._session.flush()

    async def get(self, project_id: uuid.UUID) -> Optional[Project]:
        row = await self._session.get(ProjectModel, str(project_id))
        if not row or row.deleted_at:
            return None
        return self._to_domain(row)

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[Project]:
        q = select(ProjectModel).where(ProjectModel.deleted_at.is_(None))
        if status:
            q = q.where(ProjectModel.status == status)
        if search:
            q = q.where(ProjectModel.title.ilike(f"%{search}%"))
        q = q.order_by(ProjectModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(q)
        return [self._to_domain(row) for row in result.scalars()]

    async def count(self, status: Optional[str] = None) -> int:
        q = select(func.count()).select_from(ProjectModel).where(ProjectModel.deleted_at.is_(None))
        if status:
            q = q.where(ProjectModel.status == status)
        result = await self._session.execute(q)
        return result.scalar() or 0

    async def soft_delete(self, project_id: uuid.UUID) -> None:
        await self._session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == str(project_id))
            .values(deleted_at=datetime.utcnow())
        )

    def _to_domain(self, row: ProjectModel) -> Project:
        p = Project.__new__(Project)
        p.id = uuid.UUID(row.id)
        p.title = row.title
        p.description = row.description or ""
        p.script = row.script or ""
        p.tags = row.tags or []
        p.status = ProjectStatus(row.status)
        p.template_id = uuid.UUID(row.template_id) if row.template_id else None
        p.logo_asset_id = uuid.UUID(row.logo_asset_id) if row.logo_asset_id else None
        p.brand_colors = BrandColors.from_dict(row.brand_colors or {})
        p.settings = row.settings or {}
        p.created_at = row.created_at
        p.updated_at = row.updated_at
        return p
