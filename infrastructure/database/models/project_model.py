import uuid
from datetime import datetime
from sqlalchemy import String, Text, JSON, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.database.session import Base
from shared.value_objects import ProjectStatus


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    script: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[dict] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(50), default=ProjectStatus.DRAFT.value)
    template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    logo_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    brand_colors: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
