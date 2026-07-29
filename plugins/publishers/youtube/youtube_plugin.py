"""
YouTube Publisher Plugin — Real OAuth2 + YouTube Data API v3 upload.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Callable, Awaitable, Optional

from shared.ports.publisher_port import (
    PublisherPort, PlatformProfile, PublishableContent,
    AuthResult, ValidationResult, UploadResult, ScheduleResult,
)

logger = logging.getLogger(__name__)

# ── OAuth2 scopes needed ──────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# YouTube privacy options
PRIVACY_OPTIONS = {"public", "unlisted", "private"}


class YouTubePublisherPlugin(PublisherPort):
    """
    Full YouTube integration using OAuth2 + YouTube Data API v3.

    Credential flow:
      1. Front-end redirects user to /oauth/youtube/start
      2. Google redirects back to /oauth/youtube/callback?code=...
      3. Code is exchanged for access_token + refresh_token
      4. Tokens stored encrypted in PublisherAccount.credentials_encrypted
      5. On upload, tokens are refreshed automatically if expired
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._client_id     = os.environ.get("YOUTUBE_CLIENT_ID", "")
        self._client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")

    @property
    def platform_name(self) -> str:
        return "youtube"

    def get_platform_profile(self) -> PlatformProfile:
        return PlatformProfile(
            platform_name="youtube",
            display_name="YouTube",
            max_duration=43200.0,
            max_file_size=128 * 1024 ** 3,
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

    # ─── OAuth helpers ────────────────────────────────────────────────────────

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def build_oauth_flow(self, redirect_uri: str):
        """Build a google_auth_oauthlib Flow object."""
        from google_auth_oauthlib.flow import Flow
        client_config = {
            "web": {
                "client_id":     self._client_id,
                "client_secret": self._client_secret,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }
        flow = Flow.from_client_config(client_config, scopes=SCOPES)
        flow.redirect_uri = redirect_uri
        return flow

    def get_authorization_url(self, redirect_uri: str) -> tuple[str, str]:
        """Return (authorization_url, state) for the OAuth2 redirect."""
        flow = self.build_oauth_flow(redirect_uri)
        url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return url, state

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for tokens. Returns credential dict."""
        flow = self.build_oauth_flow(redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "access_token":  creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri":     creds.token_uri,
            "client_id":     creds.client_id,
            "client_secret": creds.client_secret,
            "scopes":        list(creds.scopes or []),
            "expiry":        creds.expiry.isoformat() if creds.expiry else None,
        }

    def _build_credentials(self, cred_dict: dict):
        """Reconstruct google.oauth2.credentials.Credentials from stored dict."""
        from google.oauth2.credentials import Credentials
        expiry = None
        if cred_dict.get("expiry"):
            try:
                expiry = datetime.fromisoformat(cred_dict["expiry"])
            except Exception:
                pass
        return Credentials(
            token=cred_dict.get("access_token"),
            refresh_token=cred_dict.get("refresh_token"),
            token_uri=cred_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=cred_dict.get("client_id") or self._client_id,
            client_secret=cred_dict.get("client_secret") or self._client_secret,
            scopes=cred_dict.get("scopes", SCOPES),
            expiry=expiry,
        )

    def _get_channel_info(self, credentials) -> dict:
        """Fetch channel info from YouTube API."""
        try:
            from googleapiclient.discovery import build
            yt = build("youtube", "v3", credentials=credentials)
            resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
            items = resp.get("items", [])
            if items:
                ch = items[0]
                return {
                    "channel_id":    ch["id"],
                    "channel_title": ch["snippet"]["title"],
                    "subscribers":   ch["statistics"].get("subscriberCount", "0"),
                    "thumbnail":     ch["snippet"]["thumbnails"].get("default", {}).get("url", ""),
                }
        except Exception as e:
            logger.warning("Could not fetch channel info: %s", e)
        return {}

    # ─── PublisherPort interface ───────────────────────────────────────────────

    async def authenticate(self, credentials: dict) -> AuthResult:
        """
        Validate an OAuth2 credential dict obtained from exchange_code().
        Used when saving an account after the OAuth callback.
        """
        if not credentials.get("access_token"):
            return AuthResult(
                success=False,
                error="لا يوجد access_token. يرجى إتمام خطوات ربط حساب يوتيوب عبر OAuth2.",
            )

        # Optionally verify by fetching channel info
        try:
            creds_obj = self._build_credentials(credentials)
            loop = asyncio.get_event_loop()
            channel_info = await loop.run_in_executor(None, self._get_channel_info, creds_obj)
        except Exception as e:
            logger.warning("Auth verification skipped: %s", e)
            channel_info = {}

        return AuthResult(
            success=True,
            access_token=credentials["access_token"],
            refresh_token=credentials.get("refresh_token"),
            channel_info=channel_info,
        )

    async def validate_content(
        self,
        content: PublishableContent,
        profile: PlatformProfile,
    ) -> ValidationResult:
        errors, warnings = [], []
        if not content.title:
            errors.append("العنوان مطلوب")
        elif len(content.title) > profile.max_title_length:
            errors.append(f"العنوان يتجاوز {profile.max_title_length} حرف")
        if len(content.description) > profile.max_description_length:
            errors.append(f"الوصف يتجاوز {profile.max_description_length} حرف")
        if len(content.tags) > profile.max_tags:
            warnings.append(f"سيتم استخدام أول {profile.max_tags} وسم فقط")
        if not content.video_path.exists():
            errors.append(f"ملف الفيديو غير موجود: {content.video_path}")
        elif profile.max_file_size:
            if content.video_path.stat().st_size > profile.max_file_size:
                errors.append("حجم الفيديو يتجاوز الحد الأقصى لـ YouTube (128 GB)")
        if content.privacy not in PRIVACY_OPTIONS:
            warnings.append(f"خيار الخصوصية '{content.privacy}' غير معروف، سيُستخدم 'public'")
        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    async def upload(
        self,
        content: PublishableContent,
        credentials: dict,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> UploadResult:
        """Upload a video to YouTube using resumable upload."""
        if not credentials.get("access_token"):
            return UploadResult(
                success=False,
                error="لا يوجد access_token — يرجى ربط حساب يوتيوب أولاً.",
            )

        await progress_callback(5.0, "التحقق من بيانات الاعتماد")

        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from googleapiclient.errors import HttpError
            import httplib2

            creds_obj = self._build_credentials(credentials)

            # Refresh token if needed
            if creds_obj.expired and creds_obj.refresh_token:
                from google.auth.transport.requests import Request
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, creds_obj.refresh, Request())

            await progress_callback(10.0, "الاتصال بـ YouTube")

            loop = asyncio.get_event_loop()

            def _do_upload():
                yt = build("youtube", "v3", credentials=creds_obj)

                body = {
                    "snippet": {
                        "title":       content.title[:100],
                        "description": content.description[:5000],
                        "tags":        content.tags[:500],
                        "categoryId":  "22",  # People & Blogs (default)
                    },
                    "status": {
                        "privacyStatus":          content.privacy or "public",
                        "selfDeclaredMadeForKids": False,
                    },
                }

                media = MediaFileUpload(
                    str(content.video_path),
                    chunksize=10 * 1024 * 1024,  # 10 MB chunks
                    resumable=True,
                )

                request = yt.videos().insert(
                    part=",".join(body.keys()),
                    body=body,
                    media_body=media,
                )

                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        pct = 10 + status.progress() * 85
                        # Can't await inside sync; just log
                        logger.info("Upload progress: %.1f%%", pct)

                return response

            await progress_callback(15.0, "جارٍ الرفع إلى YouTube…")
            response = await loop.run_in_executor(None, _do_upload)

            video_id  = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Upload thumbnail if provided
            if content.thumbnail_path and content.thumbnail_path.exists():
                await progress_callback(95.0, "رفع الصورة المصغرة")
                def _upload_thumbnail():
                    from googleapiclient.http import MediaFileUpload as MF
                    yt = build("youtube", "v3", credentials=creds_obj)
                    yt.thumbnails().set(
                        videoId=video_id,
                        media_body=MF(str(content.thumbnail_path)),
                    ).execute()
                try:
                    await loop.run_in_executor(None, _upload_thumbnail)
                except Exception as e:
                    logger.warning("Thumbnail upload failed: %s", e)

            await progress_callback(100.0, "اكتمل الرفع")
            logger.info("Uploaded to YouTube: %s", video_url)

            return UploadResult(
                success=True,
                platform_post_id=video_id,
                platform_url=video_url,
                metadata={"snippet": response.get("snippet", {})},
            )

        except Exception as e:
            logger.error("YouTube upload failed: %s", e, exc_info=True)
            return UploadResult(success=False, error=str(e))

    async def schedule_post(
        self,
        upload_result: UploadResult,
        credentials: dict,
        scheduled_at: datetime,
    ) -> ScheduleResult:
        """Set a private video to go public at scheduled_at (YouTube scheduled publish)."""
        if not upload_result.platform_post_id:
            return ScheduleResult(success=False, error="لا يوجد video_id للجدولة")
        try:
            from googleapiclient.discovery import build

            creds_obj = self._build_credentials(credentials)
            loop = asyncio.get_event_loop()

            def _schedule():
                yt = build("youtube", "v3", credentials=creds_obj)
                yt.videos().update(
                    part="status",
                    body={
                        "id": upload_result.platform_post_id,
                        "status": {
                            "privacyStatus": "private",
                            "publishAt": scheduled_at.isoformat() + "Z",
                        },
                    },
                ).execute()

            await loop.run_in_executor(None, _schedule)
            return ScheduleResult(success=True, scheduled_at=scheduled_at)
        except Exception as e:
            return ScheduleResult(success=False, error=str(e))
