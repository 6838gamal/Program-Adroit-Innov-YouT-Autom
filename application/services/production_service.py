"""Application service for Production / Render use cases."""
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from core.domain.rendering.render_job import RenderJob
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from infrastructure.database.session import get_session_factory
from plugins.registry import PluginRegistry
from shared.domain_events import (
    ProductionStarted, RenderProgressUpdated,
    RenderCompleted, RenderFailed,
)
from shared.exceptions import ProjectNotFoundError, RenderJobNotFoundError
from shared.ports.renderer_port import RenderSettings
from config.settings import settings

logger = logging.getLogger(__name__)

# Global registry for active render tasks (job_id -> asyncio.Task)
_active_renders: dict[str, asyncio.Task] = {}


class ProductionService:
    def __init__(
        self,
        project_repo: SQLProjectRepository,
        job_repo: SQLRenderJobRepository,
        event_bus: InMemoryEventBus,
        plugin_registry: PluginRegistry,
    ):
        self._projects = project_repo
        self._jobs = job_repo
        self._bus = event_bus
        self._registry = plugin_registry

    async def start_render(
        self,
        project_id: uuid.UUID,
        render_settings: Optional[dict] = None,
    ) -> RenderJob:
        project = await self._projects.get(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)

        job = RenderJob(project_id=project_id, settings=render_settings or {})
        project.start_production()

        await self._jobs.save(job)
        await self._projects.save(project)
        await self._bus.publish(ProductionStarted(project_id=project_id, render_job_id=job.id))

        # Launch render in background
        task = asyncio.create_task(
            self._run_render(job.id, project.to_dict())
        )
        _active_renders[str(job.id)] = task
        return job

    async def _run_render(self, job_id: uuid.UUID, project_data: dict) -> None:
        """Background render task — runs independently of the request."""
        factory = get_session_factory()

        async def save_progress(progress: float, stage: str) -> None:
            async with factory() as session:
                from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
                repo = SQLRenderJobRepository(session)
                j = await repo.get(job_id)
                if j:
                    j.update_progress(progress, stage)
                    await repo.save(j)
                    await session.commit()
            await self._bus.publish(RenderProgressUpdated(
                job_id=job_id, progress=progress, stage=stage
            ))

        async with factory() as session:
            from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
            from infrastructure.repositories.sql_project_repository import SQLProjectRepository
            job_repo = SQLRenderJobRepository(session)
            proj_repo = SQLProjectRepository(session)

            job = await job_repo.get(job_id)
            if not job:
                return

            job.start()
            await job_repo.save(job)
            await session.commit()

        try:
            renderer = self._registry.get_renderer()
            temp_dir = settings.TEMP_DIR / str(job_id)
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Resolve assets (placeholder — real asset resolution in Phase 2)
            assets: dict = {}

            rs = RenderSettings(
                fps=30,
                resolution_width=1920,
                resolution_height=1080,
            )

            await save_progress(5.0, "Initializing")

            result = await renderer.render(
                project_id=uuid.UUID(project_data["id"]),
                timeline_data={"duration": 10.0},
                assets=assets,
                settings=rs,
                temp_dir=temp_dir,
                progress_callback=save_progress,
            )

            # Generate thumbnail
            output_dir = settings.EXPORTS_DIR / str(job_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            thumb_path = settings.THUMBNAILS_DIR / f"{job_id}.jpg"

            from shared.ports.renderer_port import ThumbnailConfig
            await renderer.generate_thumbnail(
                result.output_path,
                ThumbnailConfig(title=project_data.get("title", "")),
                thumb_path,
            )

            await save_progress(100.0, "Complete")

            async with factory() as session:
                job_repo = SQLRenderJobRepository(session)
                proj_repo = SQLProjectRepository(session)
                job = await job_repo.get(job_id)
                project_id = uuid.UUID(project_data["id"])
                project = await proj_repo.get(project_id)
                if job:
                    job.complete(str(result.output_path))
                    await job_repo.save(job)
                if project:
                    project.mark_rendered()
                    await proj_repo.save(project)
                await session.commit()

            await self._bus.publish(RenderCompleted(
                job_id=job_id,
                project_id=uuid.UUID(project_data["id"]),
                output_path=str(result.output_path),
            ))
            logger.info("Render completed: job=%s", job_id)

        except Exception as exc:
            logger.exception("Render failed: job=%s error=%s", job_id, exc)
            async with factory() as session:
                job_repo = SQLRenderJobRepository(session)
                proj_repo = SQLProjectRepository(session)
                job = await job_repo.get(job_id)
                project_id = uuid.UUID(project_data["id"])
                project = await proj_repo.get(project_id)
                if job:
                    job.fail(str(exc))
                    await job_repo.save(job)
                if project:
                    project.mark_failed()
                    await proj_repo.save(project)
                await session.commit()
            await self._bus.publish(RenderFailed(
                job_id=job_id,
                project_id=uuid.UUID(project_data["id"]),
                error=str(exc),
            ))
        finally:
            _active_renders.pop(str(job_id), None)

    async def get_job(self, job_id: uuid.UUID) -> RenderJob:
        job = await self._jobs.get(job_id)
        if not job:
            raise RenderJobNotFoundError(job_id)
        return job

    async def list_jobs(self, limit: int = 20) -> list[RenderJob]:
        return await self._jobs.list_recent(limit=limit)
