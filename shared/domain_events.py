import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DomainEvent:
    """Base class for all domain events."""
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def event_name(self) -> str:
        return self.__class__.__name__


# ── Project Events ────────────────────────────────────────────────────────────

@dataclass
class ProjectCreated(DomainEvent):
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""


@dataclass
class ProjectUpdated(DomainEvent):
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class ProjectDeleted(DomainEvent):
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)


# ── Production Events ─────────────────────────────────────────────────────────

@dataclass
class ProductionStarted(DomainEvent):
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    render_job_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class RenderProgressUpdated(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    progress: float = 0.0
    stage: str = ""
    message: str = ""


@dataclass
class RenderCompleted(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    output_path: str = ""


@dataclass
class RenderFailed(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    error: str = ""


@dataclass
class ExportCompleted(DomainEvent):
    export_job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    format: str = ""
    output_path: str = ""


# ── Publishing Events ─────────────────────────────────────────────────────────

@dataclass
class PublishQueued(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class PublishScheduled(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    scheduled_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PublishStarted(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    platform: str = ""


@dataclass
class PublishProgressUpdated(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    progress: float = 0.0
    message: str = ""


@dataclass
class PublishCompleted(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    platform: str = ""
    platform_url: str = ""


@dataclass
class PublishFailed(DomainEvent):
    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    platform: str = ""
    error: str = ""
    will_retry: bool = False
