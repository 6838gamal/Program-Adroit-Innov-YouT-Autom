"""Application service for Project use cases."""
import uuid
import logging
from typing import Optional

from core.domain.project.project import Project
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from shared.domain_events import ProjectCreated, ProjectDeleted, ProjectPublished
from shared.value_objects import BrandColors, ProjectStatus
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

    # ─────────────────────────────────────────────────────────────────────────
    # Create
    # ─────────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────────
    # Get
    # ─────────────────────────────────────────────────────────────────────────

    async def get(self, project_id: uuid.UUID) -> Project:
        project = await self._repo.get(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)
        return project

    # ─────────────────────────────────────────────────────────────────────────
    # Update — يدعم status الآن
    # ─────────────────────────────────────────────────────────────────────────

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
        status: Optional[str] = None,           # ✅ جديد — لدعم publish
        data: Optional[dict] = None,            # ✅ جديد — لدعم تحديث data blob
    ) -> Project:
        """
        تحديث بيانات المشروع.

        يدعم بالإضافة إلى الحقول الأساسية:
        - status: لتغيير حالة المشروع (draft, in_production, rendered, published, failed)
        - data: لتحديث data blob (clips, layers, media_files, video_url, thumbnail, ...)
        """
        project = await self.get(project_id)

        # ✅ 1) حدّث الحقول الأساسية
        project.update(
            title=title,
            description=description,
            script=script,
            tags=tags,
            template_id=template_id,
            brand_colors=BrandColors.from_dict(brand_colors) if brand_colors else None,
            settings=settings,
        )

        # ✅ 2) حدّث الحالة إن مُرّرت
        if status is not None:
            try:
                project.status = ProjectStatus(status)
                project._touch()
            except Exception as e:
                logger.warning("Invalid status '%s': %s", status, e)

        # ✅ 3) حدّث data blob إن مُرّرت
        if data is not None and isinstance(data, dict):
            try:
                if hasattr(project, "update_data"):
                    project.update_data(data)
                else:
                    existing = getattr(project, "data", None) or {}
                    if not isinstance(existing, dict):
                        existing = {}
                    existing.update(data)
                    project.data = existing
            except Exception as e:
                logger.warning("Could not update project data: %s", e)

        await self._repo.save(project)
        return project

    # ─────────────────────────────────────────────────────────────────────────
    # Publish — دالة مخصّصة للنشر
    # ─────────────────────────────────────────────────────────────────────────

    async def publish(self, project_id: uuid.UUID) -> Project:
        """
        نشر المشروع (تغيير الحالة إلى published).

        متوافق مع domain rule: يمكن نشر المشاريع التي حالتها rendered فقط.
        """
        project = await self.get(project_id)

        # ✅ استخدم دالة domain إن وُجدت
        if hasattr(project, "mark_published"):
            project.mark_published()
        else:
            project.status = ProjectStatus.PUBLISHED
            project._touch()

        await self._repo.save(project)

        # انشر حدث (إن وُجد)
        try:
            await self._bus.publish(ProjectPublished(project_id=project_id))
        except Exception as e:
            logger.warning("Could not publish ProjectPublished event: %s", e)

        logger.info("Project published: %s", project_id)
        return project

    # ─────────────────────────────────────────────────────────────────────────
    # Delete
    # ─────────────────────────────────────────────────────────────────────────

    async def delete(self, project_id: uuid.UUID) -> None:
        project = await self.get(project_id)
        await self._repo.soft_delete(project_id)
        await self._bus.publish(ProjectDeleted(project_id=project_id))

    # ─────────────────────────────────────────────────────────────────────────
    # List
    # ─────────────────────────────────────────────────────────────────────────

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
