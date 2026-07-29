import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from publishing.domain.publishing_job import PublishingJob
from publishing.domain.publisher_account import PublisherAccount
from infrastructure.database.models.publishing_model import PublishingJobModel, PublisherAccountModel
from shared.value_objects import PublishStatus


class SQLPublishingJobRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, job: PublishingJob) -> None:
        existing = await self._session.get(PublishingJobModel, str(job.id))
        if existing:
            existing.status = job.status.value
            existing.platform_post_id = job.platform_post_id
            existing.platform_url = job.platform_url
            existing.error_message = job.error_message
            existing.retry_count = job.retry_count
            existing.scheduled_at = job.scheduled_at
            existing.started_at = job.started_at
            existing.completed_at = job.completed_at
            existing.metadata_ = job.metadata
        else:
            self._session.add(PublishingJobModel(
                id=str(job.id),
                project_id=str(job.project_id),
                account_id=str(job.account_id),
                export_job_id=str(job.export_job_id) if job.export_job_id else None,
                status=job.status.value,
                metadata_=job.metadata,
                scheduled_at=job.scheduled_at,
                created_at=job.created_at,
            ))
        await self._session.flush()

    async def get(self, job_id: uuid.UUID) -> Optional[PublishingJob]:
        row = await self._session.get(PublishingJobModel, str(job_id))
        return self._to_domain(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[PublishingJob]:
        q = select(PublishingJobModel).order_by(
            PublishingJobModel.created_at.desc()
        ).limit(limit)
        result = await self._session.execute(q)
        return [self._to_domain(r) for r in result.scalars()]

    def _to_domain(self, row: PublishingJobModel) -> PublishingJob:
        job = PublishingJob.__new__(PublishingJob)
        job.id = uuid.UUID(row.id)
        job.project_id = uuid.UUID(row.project_id)
        job.account_id = uuid.UUID(row.account_id)
        job.export_job_id = uuid.UUID(row.export_job_id) if row.export_job_id else None
        job.profile_id = None
        job.status = PublishStatus(row.status)
        job.metadata = row.metadata_ or {}
        job.platform_post_id = row.platform_post_id
        job.platform_url = row.platform_url
        job.error_message = row.error_message
        job.retry_count = row.retry_count or 0
        job.scheduled_at = row.scheduled_at
        job.started_at = row.started_at
        job.completed_at = row.completed_at
        job.created_at = row.created_at
        job.updated_at = row.created_at
        return job


class SQLAccountRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, account: PublisherAccount) -> None:
        existing = await self._session.get(PublisherAccountModel, str(account.id))
        if existing:
            existing.name = account.name
            existing.is_active = account.is_active
            existing.last_verified = account.last_verified
            existing.metadata_ = account.metadata
        else:
            self._session.add(PublisherAccountModel(
                id=str(account.id),
                name=account.name,
                platform_name=account.platform_name,
                credentials_encrypted=account.credentials_encrypted,
                is_active=account.is_active,
                metadata_=account.metadata,
                created_at=account.created_at,
            ))
        await self._session.flush()

    async def get(self, account_id: uuid.UUID) -> Optional[PublisherAccount]:
        row = await self._session.get(PublisherAccountModel, str(account_id))
        return self._to_domain(row) if row else None

    async def list_all(self) -> list[PublisherAccount]:
        q = select(PublisherAccountModel).where(PublisherAccountModel.is_active == True)
        result = await self._session.execute(q)
        return [self._to_domain(r) for r in result.scalars()]

    def _to_domain(self, row: PublisherAccountModel) -> PublisherAccount:
        a = PublisherAccount.__new__(PublisherAccount)
        a.id = uuid.UUID(row.id)
        a.name = row.name
        a.platform_name = row.platform_name
        a.credentials_encrypted = row.credentials_encrypted
        a.is_active = row.is_active
        a.last_verified = row.last_verified
        a.metadata = row.metadata_ or {}
        a.created_at = row.created_at
        a.updated_at = row.created_at
        return a
