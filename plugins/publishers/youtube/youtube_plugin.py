"""
YouTube Publisher Plugin.
Implements PublisherPort for YouTube using the YouTube Data API v3.
Credentials should be an OAuth2 token dict.
"""
import logging
from datetime import datetime
from typing import Callable, Awaitable

from shared.ports.publisher_port import (
    PublisherPort,
    PlatformProfile,
    PublishableContent,
    AuthResult,
    ValidationResult,
    UploadResult,
    ScheduleResult,
)

logger = logging.getLogger(__name__)


class YouTubePublisherPlugin(PublisherPort):
    """
    YouTube publishing plugin.
    MVP: validates content and simulates upload (real OAuth2 upload in Phase 2).
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def platform_name(self) -> str:
        return "youtube"

    def get_platform_profile(self) -> PlatformProfile:
        return PlatformProfile(
            platform_name="youtube",
            display_name="YouTube",
            max_duration=43200.0,          # 12 hours
            max_file_size=128 * 1024**3,    # 128 GB
            supported_formats=["mp4", "mov", "avi", "webm"],
            supported_aspect_ratios=["16:9", "9:16", "1:1"],
            thumbnail_required=False,
            thumbnail_min_width=1280,
            thumbnail_min_height=720,
            max_title_length=100,
            max_description_length=5000,
            max_tags=500,
            supports_scheduling=True,
            supports_chapters=True,
            supports_subtitles=True,
        )

    async def authenticate(self, credentials: dict) -> AuthResult:
        """Validate that credentials contain required OAuth2 fields."""
        if not credentials.get("access_token"):
            return AuthResult(success=False, error="Missing access_token in credentials")

        return AuthResult(
            success=True,
            access_token=credentials["access_token"],
            channel_info=credentials.get("channel_info", {}),
        )

    async def validate_content(
        self,
        content: PublishableContent,
        profile: PlatformProfile,
    ) -> ValidationResult:
        errors = []
        warnings = []

        if not content.title:
            errors.append("Title is required")
        elif len(content.title) > profile.max_title_length:
            errors.append(f"Title exceeds {profile.max_title_length} characters")

        if len(content.description) > profile.max_description_length:
            errors.append(f"Description exceeds {profile.max_description_length} characters")

        if len(content.tags) > profile.max_tags:
            warnings.append(f"Only first {profile.max_tags} tags will be used")

        if not content.video_path.exists():
            errors.append(f"Video file not found: {content.video_path}")

        if content.video_path.exists():
            file_size = content.video_path.stat().st_size
            if profile.max_file_size and file_size > profile.max_file_size:
                errors.append("Video file exceeds maximum file size for YouTube")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    async def upload(
        self,
        content: PublishableContent,
        credentials: dict,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> UploadResult:
        """
        MVP: Simulates upload. Real implementation requires google-auth + googleapiclient.
        Replace this method body with actual YouTube API calls when OAuth is configured.
        """
        await progress_callback(10.0, "Connecting to YouTube")

        if not credentials.get("access_token"):
            return UploadResult(success=False, error="No access token — please connect your YouTube account")

        await progress_callback(50.0, "Uploading video")
        # TODO: Implement real upload via googleapiclient.discovery
        # youtube = build("youtube", "v3", credentials=...)
        # request = youtube.videos().insert(...)

        await progress_callback(90.0, "Processing")

        # Return a simulated result for MVP
        simulated_id = f"sim_{content.title[:10].replace(' ', '_')}"
        return UploadResult(
            success=True,
            platform_post_id=simulated_id,
            platform_url=f"https://youtube.com/watch?v={simulated_id}",
            metadata={"simulated": True},
        )

    async def schedule_post(
        self,
        upload_result: UploadResult,
        credentials: dict,
        scheduled_at: datetime,
    ) -> ScheduleResult:
        """Schedule a previously uploaded (but private) video to go public."""
        if not upload_result.platform_post_id:
            return ScheduleResult(success=False, error="No video ID to schedule")

        # TODO: youtube.videos().update() with publishAt
        return ScheduleResult(success=True, scheduled_at=scheduled_at)
