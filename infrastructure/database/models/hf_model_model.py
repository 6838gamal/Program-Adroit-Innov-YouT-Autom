"""SQLAlchemy model for HuggingFace model registry."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, JSON, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.database.session import Base


class HFModelModel(Base):
    __tablename__ = "hf_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # HuggingFace model ID e.g. "facebook/mms-tts-ara"
    hf_model_id: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    # Display name (auto-fetched or user-set)
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Model type: tts | text-to-image | text-to-video
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # tags / languages etc from HF Hub
    tags: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    # Visibility in production studio
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Is this the active default for its type?
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    # Optional extra config (voice, seed, steps, etc.)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # HF Hub metadata cache
    hf_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hf_model_id": self.hf_model_id,
            "name": self.name,
            "model_type": self.model_type,
            "description": self.description,
            "tags": self.tags or [],
            "languages": self.languages or [],
            "is_enabled": self.is_enabled,
            "is_active": self.is_active,
            "config": self.config or {},
            "hf_metadata": self.hf_metadata or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
