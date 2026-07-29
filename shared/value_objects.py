from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AspectRatio(str, Enum):
    LANDSCAPE_16_9 = "16:9"
    VERTICAL_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    PORTRAIT_4_5 = "4:5"
    CINEMATIC_21_9 = "21:9"


class VideoFormat(str, Enum):
    MP4 = "mp4"
    MOV = "mov"
    AVI = "avi"
    GIF = "gif"
    WEBM = "webm"


class TrackType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    MUSIC = "music"
    SUBTITLE = "subtitle"
    ANIMATION = "animation"
    OVERLAY = "overlay"
    LOGO = "logo"


class LayerType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    TEXT = "text"
    SUBTITLE = "subtitle"
    LOGO = "logo"
    OVERLAY = "overlay"
    AUDIO = "audio"
    MUSIC = "music"
    ANIMATION = "animation"


class AssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FONT = "font"
    ICON = "icon"
    LOGO = "logo"
    TRANSITION = "transition"
    ANIMATION = "animation"
    BACKGROUND = "background"
    STICKER = "sticker"
    OVERLAY = "overlay"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    IN_PRODUCTION = "in_production"
    RENDERED = "rendered"
    PUBLISHED = "published"
    FAILED = "failed"


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublishStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int

    @classmethod
    def hd(cls) -> "Resolution":
        return cls(1920, 1080)

    @classmethod
    def vertical_hd(cls) -> "Resolution":
        return cls(1080, 1920)

    @classmethod
    def square(cls) -> "Resolution":
        return cls(1080, 1080)

    @property
    def aspect_ratio(self) -> AspectRatio:
        ratio = self.width / self.height
        if abs(ratio - 16 / 9) < 0.01:
            return AspectRatio.LANDSCAPE_16_9
        elif abs(ratio - 9 / 16) < 0.01:
            return AspectRatio.VERTICAL_9_16
        elif abs(ratio - 1.0) < 0.01:
            return AspectRatio.SQUARE_1_1
        elif abs(ratio - 4 / 5) < 0.01:
            return AspectRatio.PORTRAIT_4_5
        return AspectRatio.LANDSCAPE_16_9

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height}

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class BrandColors:
    primary: str = "#3B82F6"
    secondary: str = "#1E40AF"
    accent: str = "#F59E0B"
    text: str = "#FFFFFF"
    background: str = "#000000"

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "text": self.text,
            "background": self.background,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BrandColors":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
