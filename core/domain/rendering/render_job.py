import uuid
from datetime import datetime
from typing import Optional
from shared.base_entity import BaseEntity
from shared.value_objects import JobStatus


class RenderJob(BaseEntity):
    """Represents a render job for a project."""

    def __init__(
        self,
        project_id: uuid.UUID,
        renderer: str = "ffmpeg",
        settings: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.project_id = project_id
        self.renderer = renderer
        self.status = JobStatus.PENDING
        self.progress: float = 0.0
        self.current_stage: str = ""
        self.output_path: Optional[str] = None
        self.error_message: Optional[str] = None
        self.settings: dict = settings or {}
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = JobStatus.PROCESSING
        self.started_at = datetime.utcnow()
        self._touch()

    def update_progress(self, progress: float, stage: str = "") -> None:
        self.progress = min(100.0, max(0.0, progress))
        if stage:
            self.current_stage = stage
        self._touch()

    def complete(self, output_path: str) -> None:
        self.status = JobStatus.COMPLETED
        self.progress = 100.0
        self.output_path = output_path
        self.completed_at = datetime.utcnow()
        self._touch()

    def fail(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.utcnow()
        self._touch()

    def cancel(self) -> None:
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.utcnow()
        self._touch()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "renderer": self.renderer,
            "status": self.status.value,
            "progress": self.progress,
            "current_stage": self.current_stage,
            "output_path": self.output_path,
            "error_message": self.error_message,
            "settings": self.settings,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }


class ExportJob(BaseEntity):
    """Represents a format-specific export from a render result."""

    def __init__(
        self,
        project_id: uuid.UUID,
        render_job_id: uuid.UUID,
        format: str = "mp4",
        aspect_ratio: str = "16:9",
        width: int = 1920,
        height: int = 1080,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.project_id = project_id
        self.render_job_id = render_job_id
        self.format = format
        self.aspect_ratio = aspect_ratio
        self.width = width
        self.height = height
        self.status = JobStatus.PENDING
        self.output_path: Optional[str] = None
        self.file_size: int = 0
        self.completed_at: Optional[datetime] = None

    def complete(self, output_path: str, file_size: int = 0) -> None:
        self.status = JobStatus.COMPLETED
        self.output_path = output_path
        self.file_size = file_size
        self.completed_at = datetime.utcnow()
        self._touch()

    def fail(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.completed_at = datetime.utcnow()
        self._touch()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "render_job_id": str(self.render_job_id),
            "format": self.format,
            "aspect_ratio": self.aspect_ratio,
            "width": self.width,
            "height": self.height,
            "status": self.status.value,
            "output_path": self.output_path,
            "file_size": self.file_size,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }
