import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.rendering.render_job import RenderJob, ExportJob
from infrastructure.database.models.render_job_model import RenderJobModel, ExportJobModel
from shared.value_objects import JobStatus


class SQLRenderJobRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, job: RenderJob) -> None:
        existing = await self._session.get(RenderJobModel, str(job.id))
        if existing:
            existing.status = job.status.value
            existing.progress = job.progress
            existing.current_stage = job.current_stage
            existing.output_path = job.output_path
            existing.error_message = job.error_message
            existing.started_at = job.started_at
            existing.completed_at = job.completed_at
        else:
            self._session.add(RenderJobModel(
                id=str(job.id),
                project_id=str(job.project_id),
                renderer=job.renderer,
                status=job.status.value,
                progress=job.progress,
                current_stage=job.current_stage,
                settings=job.settings,
                created_at=job.created_at,
            ))
        await self._session.flush()

    async def get(self, job_id: uuid.UUID) -> Optional[RenderJob]:
        row = await self._session.get(RenderJobModel, str(job_id))
        return self._to_domain(row) if row else None

    async def list_for_project(self, project_id: uuid.UUID) -> list[RenderJob]:
        q = select(RenderJobModel).where(
            RenderJobModel.project_id == str(project_id)
        ).order_by(RenderJobModel.created_at.desc())
        result = await self._session.execute(q)
        return [self._to_domain(r) for r in result.scalars()]

    async def list_recent(self, limit: int = 20) -> list[RenderJob]:
        q = select(RenderJobModel).order_by(RenderJobModel.created_at.desc()).limit(limit)
        result = await self._session.execute(q)
        return [self._to_domain(r) for r in result.scalars()]

    def _to_domain(self, row: RenderJobModel) -> RenderJob:
        job = RenderJob.__new__(RenderJob)
        job.id = uuid.UUID(row.id)
        job.project_id = uuid.UUID(row.project_id)
        job.renderer = row.renderer
        job.status = JobStatus(row.status)
        job.progress = row.progress
        job.current_stage = row.current_stage or ""
        job.output_path = row.output_path
        job.error_message = row.error_message
        job.settings = row.settings or {}
        job.started_at = row.started_at
        job.completed_at = row.completed_at
        job.created_at = row.created_at
        job.updated_at = row.created_at
        return job
