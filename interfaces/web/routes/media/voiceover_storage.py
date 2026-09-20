"""Voiceover upload to storage (Supabase + local fallback)."""
import logging
import uuid
from pathlib import Path
from typing import Dict

from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.directories import VOICEOVER_DIR

logger = logging.getLogger(__name__)


async def _upload_voiceover_to_storage(
    local_path: Path,
    project_id: str,
    content_type: str = "audio/webm",
) -> Dict[str, str]:
    """ارفع ملف التسجيل إلى Supabase Storage (مع fallback محلي)."""
    storage = SupabaseStorageAdapter()
    unique = f"{uuid.uuid4().hex}{local_path.suffix}"
    remote_path = f"voiceovers/{project_id}/{unique}"

    try:
        from application.services.production_service import (
            _upload_to_supabase, _build_public_url,
        )
        await _upload_to_supabase(
            storage=storage,
            local_path=local_path,
            remote_path=remote_path,
            content_type=content_type,
        )
        url = await _build_public_url(storage, remote_path)
        if url:
            return {
                "url": url,
                "path": remote_path,
                "media_id": unique,
            }
        logger.warning("Supabase upload returned no URL, falling back to local")
    except Exception as e:
        logger.warning(f"Supabase upload failed, keeping local: {e}")

    local_dest = VOICEOVER_DIR / f"{project_id}_{unique}"
    try:
        local_dest.write_bytes(local_path.read_bytes())
        url = f"/static/media/voiceovers/{local_dest.name}"
        return {
            "url": url,
            "path": str(local_dest),
            "media_id": unique,
        }
    except Exception as e:
        logger.exception(f"Local voiceover save failed: {e}")
        raise
