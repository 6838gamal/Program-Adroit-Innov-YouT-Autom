"""Job persistence: memory + disk + Supabase Storage."""
import json
import logging
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from config.settings import settings
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.directories import JOBS_DIR, JOBS_STORAGE_PREFIX
from .state import TALKING_HEAD_JOBS

logger = logging.getLogger(__name__)


def _save_job_to_disk(job_id: str, data: Dict[str, Any]) -> None:
    """احفظ حالة الـ job على القرص المحلي (fallback)."""
    try:
        data["_updated_at"] = datetime.utcnow().isoformat()
        path = JOBS_DIR / f"{job_id}.json"

        data_clean = {
            k: v for k, v in data.items()
            if k not in ("images", "image_urls", "raw_images", "_background_task")
        }

        path.write_text(
            json.dumps(data_clean, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save job {job_id} to disk: {e}")


def _load_job_from_disk(job_id: str) -> Optional[Dict[str, Any]]:
    """اقرأ حالة الـ job من القرص."""
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load job {job_id} from disk: {e}")
        return None


async def _save_job_to_storage(job_id: str, data: Dict[str, Any]) -> None:
    """
    احفظ حالة الـ job في Supabase Storage (JSON file).
    يبقى بعد restart لأن Storage دائم.
    """
    try:
        data_clean = {
            k: v for k, v in data.items()
            if k not in ("images", "image_urls", "raw_images", "_background_task")
        }
        data_clean["_updated_at"] = datetime.utcnow().isoformat()

        json_bytes = json.dumps(
            data_clean, ensure_ascii=False, default=str
        ).encode("utf-8")

        if settings.supabase_configured:
            try:
                from application.services.production_service import (
                    _upload_to_supabase,
                )

                storage = SupabaseStorageAdapter()
                remote_path = f"{JOBS_STORAGE_PREFIX}/{job_id}.json"

                tmp_path = Path(tempfile.gettempdir()) / f"job_{job_id}.json"
                tmp_path.write_bytes(json_bytes)

                try:
                    await _upload_to_supabase(
                        storage=storage,
                        local_path=tmp_path,
                        remote_path=remote_path,
                        content_type="application/json",
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)

            except Exception as e:
                logger.warning(f"Supabase save job failed: {e}")
                _save_job_to_disk(job_id, data_clean)
        else:
            _save_job_to_disk(job_id, data_clean)

    except Exception as e:
        logger.warning(f"Failed to save job {job_id}: {e}")


async def _load_job_from_storage(job_id: str) -> Optional[Dict[str, Any]]:
    """اقرأ حالة الـ job من Supabase Storage."""
    try:
        if settings.supabase_configured:
            try:
                bucket = settings.SUPABASE_BUCKET
                base_url = settings.SUPABASE_URL.rstrip("/")
                public_key = settings.supabase_public_key_value

                url = (
                    f"{base_url}/storage/v1/object/"
                    f"{bucket}/{JOBS_STORAGE_PREFIX}/{job_id}.json"
                )

                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        url,
                        headers={
                            "apikey": public_key,
                            "Authorization": f"Bearer {public_key}",
                        },
                    )
                    if r.status_code == 200:
                        return r.json()
                    elif r.status_code != 404:
                        logger.warning(
                            f"Load job HTTP {r.status_code}: {r.text[:200]}"
                        )

            except Exception as e:
                logger.warning(f"Supabase load job failed: {e}")

        return _load_job_from_disk(job_id)

    except Exception as e:
        logger.warning(f"Failed to load job {job_id}: {e}")
        return None


async def get_job_async(job_id: str) -> Optional[Dict[str, Any]]:
    """اقرأ من الذاكرة أولاً، ثم من Storage."""
    if job_id in TALKING_HEAD_JOBS:
        return TALKING_HEAD_JOBS[job_id]

    job = await _load_job_from_storage(job_id)
    if job:
        TALKING_HEAD_JOBS[job_id] = job
    return job


async def update_job_async(job_id: str, **kwargs) -> None:
    """حدّث job في الذاكرة + Storage."""
    job = (
        TALKING_HEAD_JOBS.get(job_id)
        or await _load_job_from_storage(job_id)
        or {"id": job_id}
    )
    job.update(kwargs)
    TALKING_HEAD_JOBS[job_id] = job
    await _save_job_to_storage(job_id, job)


async def create_job_async(job_id: str, **initial) -> None:
    """أنشئ job جديد واحفظه في Storage."""
    job = {
        "id": job_id,
        "created_at": datetime.utcnow().isoformat(),
        **initial,
    }
    TALKING_HEAD_JOBS[job_id] = job
    await _save_job_to_storage(job_id, job)
