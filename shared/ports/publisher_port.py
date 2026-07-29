from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable, Optional
from datetime import datetime


@dataclass
class PlatformProfile:
    """Defines all constraints and capabilities for a publishing platform."""
    platform_name: str = ""
    display_name: str = ""
    max_duration: Optional[float] = None      # seconds
    max_file_size: Optional[int] = None        # bytes
    supported_formats: list[str] = field(default_factory=lambda: ["mp4"])
    supported_aspect_ratios: list[str] = field(default_factory=lambda: ["16:9"])
    thumbnail_required: bool = False
    thumbnail_min_width: int = 1280
    thumbnail_min_height: int = 720
    max_title_length: int = 255
    max_description_length: int = 5000
    max_tags: int = 30
    supports_scheduling: bool = False
    supports_chapters: bool = False
    supports_subtitles: bool = False


@dataclass
class PublishableContent:
    video_path: Path
    thumbnail_path: Optional[Path] = None
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy: str = "public"
    language: str = "en"
    extra: dict = field(default_factory=dict)


@dataclass
class AuthResult:
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    channel_info: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class UploadResult:
    success: bool
    platform_post_id: Optional[str] = None
    platform_url: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ScheduleResult:
    success: bool
    scheduled_at: Optional[datetime] = None
    error: Optional[str] = None


class PublisherPort(ABC):
    """
    Abstract contract for a publishing platform plugin.
    Every platform (YouTube, TikTok, etc.) implements this interface.
    Core never imports a concrete publisher — only this Port.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Unique identifier: 'youtube', 'tiktok', 'instagram', etc."""
        ...

    @abstractmethod
    def get_platform_profile(self) -> PlatformProfile:
        """Returns platform constraints used before export & upload."""
        ...

    @abstractmethod
    async def authenticate(self, credentials: dict) -> AuthResult:
        ...

    @abstractmethod
    async def validate_content(
        self,
        content: PublishableContent,
        profile: PlatformProfile,
    ) -> ValidationResult:
        ...

    @abstractmethod
    async def upload(
        self,
        content: PublishableContent,
        credentials: dict,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> UploadResult:
        ...

    @abstractmethod
    async def schedule_post(
        self,
        upload_result: UploadResult,
        credentials: dict,
        scheduled_at: datetime,
    ) -> ScheduleResult:
        ...
