"""Application service for Project use cases."""
import uuid
import logging
from typing import Optional

from core.domain.project.project import Project
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from shared.domain_events import ProjectCreated, ProjectDeleted
from shared.value_objects import BrandColors
from shared.exceptions import ProjectNotFoundError

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(
        self,
        repo: SQLProjectRepository,
        event_bus: InMemoryEventBus,
    ):
        self._repo = repo
        self._bus = event_bus

    async def create(
        self,
        title: str,
        description: str = "",
        script: str = "",
        tags: Optional[list[str]] = None,
        template_id: Optional[uuid.UUID] = None,
        brand_colors: Optional[dict] = None,
    ) -> Project:
        project = Project(
            title=title,
            description=description,
            script=script,
            tags=tags or [],
            template_id=template_id,
            brand_colors=BrandColors.from_dict(brand_colors) if brand_colors else BrandColors(),
        )
        await self._repo.save(project)
        await self._bus.publish(ProjectCreated(project_id=project.id, title=project.title))
        logger.info("Project created: %s (%s)", project.title, project.id)
        return project

    async def get(self, project_id: uuid.UUID) -> Project:
        project = await self._repo.get(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)
        return project

    async def update(
        self,
        project_id: uuid.UUID,
        title: Optional[str] = None,
        description: Optional[str] = None,
        script: Optional[str] = None,
        tags: Optional[list[str]] = None,
        template_id: Optional[uuid.UUID] = None,
        brand_colors: Optional[dict] = None,
        settings: Optional[dict] = None,
    ) -> Project:
        project = await self.get(project_id)
        project.update(
            title=title,
            description=description,
            script=script,
            tags=tags,
            template_id=template_id,
            brand_colors=BrandColors.from_dict(brand_colors) if brand_colors else None,
            settings=settings,
        )
        await self._repo.save(project)
        return project

    async def delete(self, project_id: uuid.UUID) -> None:
        project = await self.get(project_id)
        await self._repo.soft_delete(project_id)
        await self._bus.publish(ProjectDeleted(project_id=project_id))

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Project], int]:
        projects = await self._repo.list_all(limit=limit, offset=offset, status=status, search=search)
        total = await self._repo.count(status=status)
        return projects, total
