"""Helper functions for Supabase config + URL resolution."""
import logging
from typing import Optional

from config.settings import settings
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

logger = logging.getLogger(__name__)


def get_supabase_config() -> dict:
    return {
        "url": settings.SUPABASE_URL,
        "public_key": settings.supabase_public_key_value,
        "bucket": settings.SUPABASE_BUCKET,
        "configured": settings.supabase_configured,
        "storage_type": settings.STORAGE_TYPE,
    }


async def _resolve_video_url(project) -> Optional[str]:
    """
    يبني public URL للفيديو من:
    1) video_url مباشر (إذا كان http)
    2) storage_path / video_path (إذا كان Supabase key — ليس مسار محلي)
    3) result_url / output_url
    """
    # 1) video_url مباشر
    video_url = getattr(project, "video_url", None)
    if not video_url:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            video_url = data.get("video_url")

    if video_url and isinstance(video_url, str) and video_url.startswith("http"):
        return video_url

    # 2) storage_path (من project أو data)
    storage_path = getattr(project, "storage_path", None)
    if not storage_path:
        storage_path = getattr(project, "output_path", None)

    if not storage_path:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            candidate = data.get("video_path") or data.get("storage_path")
            # ⭐ تجاهل المسارات المحلية (media/...)
            if candidate and not str(candidate).startswith("media/"):
                storage_path = candidate

    # 3) result_url / output_url
    if not storage_path:
        alt = getattr(project, "result_url", None) or getattr(project, "output_url", None)
        if alt and isinstance(alt, str) and alt.startswith("http"):
            return alt

    if not storage_path:
        return video_url

    # 4) بناء URL من storage_path
    try:
        storage = SupabaseStorageAdapter()
        if hasattr(storage, "get_public_url"):
            public = await storage.get_public_url(storage_path)
            if public:
                return public

        if settings.supabase_configured:
            bucket = settings.SUPABASE_BUCKET
            base = settings.SUPABASE_URL.rstrip("/")
            return (
                f"{base}/storage/v1/object/public/"
                f"{bucket}/{storage_path.lstrip('/')}"
            )
    except Exception as e:
        logger.warning(f"Failed to build video_url from storage_path: {e}")

    return video_url


async def _resolve_thumbnail_url(project) -> Optional[str]:
    """
    يبني public URL للـ thumbnail من:
    1) thumbnail_url مباشر (إذا كان http)
    2) data.thumbnail
    """
    thumb_url = getattr(project, "thumbnail_url", None)
    if not thumb_url:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            thumb_url = data.get("thumbnail")

    if thumb_url and isinstance(thumb_url, str) and thumb_url.startswith("http"):
        return thumb_url

    # إذا كان thumbnail مسار محلي → تجاهله
    if thumb_url and isinstance(thumb_url, str) and thumb_url.startswith("media/"):
        # ⭐ حاول بناء URL من Supabase
        try:
            storage = SupabaseStorageAdapter()
            # استخرج اسم الملف
            from pathlib import Path
            filename = Path(thumb_url).name
            storage_key = f"thumbnails/{filename}"
            public = await storage.get_url(storage_key)
            if public:
                return public
        except Exception as e:
            logger.warning(f"Failed to resolve thumbnail: {e}")
        return None

    return thumb_url
