import uuid
from pathlib import Path
from typing import Optional
from shared.base_entity import BaseEntity
from shared.value_objects import AssetType


class Asset(BaseEntity):
    """Represents a media asset (image, video, audio, font, etc.)."""

    def __init__(
        self,
        name: str,
        type: AssetType,
        file_path: str,
        file_size: int = 0,
        mime_type: str = "",
        duration: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        tags: Optional[list[str]] = None,
        category_id: Optional[uuid.UUID] = None,
        project_id: Optional[uuid.UUID] = None,
        metadata: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.name = name
        self.type = type
        self.file_path = file_path
        self.file_size = file_size
        self.mime_type = mime_type
        self.duration = duration
        self.width = width
        self.height = height
        self.tags: list[str] = tags or []
        self.category_id = category_id
        self.project_id = project_id
        self.is_global = project_id is None
        self.metadata: dict = metadata or {}

    @property
    def resolved_path(self) -> Path:
        return Path(self.file_path)

    @property
    def is_video(self) -> bool:
        return self.type == AssetType.VIDEO

    @property
    def is_audio(self) -> bool:
        return self.type in (AssetType.AUDIO,)

    @property
    def is_image(self) -> bool:
        return self.type in (AssetType.IMAGE, AssetType.LOGO, AssetType.ICON,
                              AssetType.BACKGROUND, AssetType.STICKER, AssetType.OVERLAY)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.type.value,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "tags": self.tags,
            "category_id": str(self.category_id) if self.category_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "is_global": self.is_global,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
