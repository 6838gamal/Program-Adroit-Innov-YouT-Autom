import uuid
from datetime import datetime, timedelta
from typing import Optional
from shared.base_entity import BaseEntity
from shared.value_objects import PublishStatus


class PublishingJob(BaseEntity):
    """Represents a single publishing operation to a platform."""

    MAX_RETRIES = 3

    def __init__(
        self,
        project_id: uuid.UUID,
        account_id: uuid.UUID,
        export_job_id: Optional[uuid.UUID] = None,
        profile_id: Optional[uuid.UUID] = None,
        metadata: Optional[dict] = None,
        scheduled_at: Optional[datetime] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.project_id = project_id
        self.account_id = account_id
        self.export_job_id = export_job_id
        self.profile_id = profile_id
        self.metadata: dict = metadata or {}
        self.scheduled_at = scheduled_at
        self.status = PublishStatus.SCHEDULED if scheduled_at else PublishStatus.PENDING
        self.platform_post_id: Optional[str] = None
        self.platform_url: Optional[str] = None
        self.error_message: Optional[str] = None
        self.retry_count: int = 0
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = PublishStatus.UPLOADING
        self.started_at = datetime.utcnow()
        self._touch()

    def mark_published(self, platform_post_id: str, platform_url: str) -> None:
        self.status = PublishStatus.PUBLISHED
        self.platform_post_id = platform_post_id
        self.platform_url = platform_url
        self.completed_at = datetime.utcnow()
        self._touch()

    def mark_failed(self, error: str) -> None:
        self.status = PublishStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.utcnow()
        self._touch()

    def cancel(self) -> None:
        self.status = PublishStatus.CANCELLED
        self._touch()

    @property
    def can_retry(self) -> bool:
        return self.retry_count < self.MAX_RETRIES and self.status == PublishStatus.FAILED

    def schedule_retry(self, delay_seconds: int = 60) -> datetime:
        self.retry_count += 1
        self.status = PublishStatus.SCHEDULED
        self.error_message = None
        retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds * self.retry_count)
        self.scheduled_at = retry_at
        self._touch()
        return retry_at

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "account_id": str(self.account_id),
            "export_job_id": str(self.export_job_id) if self.export_job_id else None,
            "profile_id": str(self.profile_id) if self.profile_id else None,
            "metadata": self.metadata,
            "status": self.status.value,
            "platform_post_id": self.platform_post_id,
            "platform_url": self.platform_url,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }
