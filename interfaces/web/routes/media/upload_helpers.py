"""Upload helpers: Catbox, tmpfiles, Supabase for D-ID."""
import logging
import tempfile
import uuid
from pathlib import Path

import httpx
from fastapi import HTTPException

from config.settings import settings
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.diagnostics import _diag, _diag_err

logger = logging.getLogger(__name__)


async def _upload_to_catbox(content: bytes, filename: str) -> str:
    """ارفع ملف إلى catbox.moe — خدمة مجانية بدون تسجيل."""
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        files = {"fileToUpload": (filename, content)}
        data = {"reqtype": "fileupload"}

        r = await client.post(
            "https://catbox.moe/user/api.php",
            files=files,
            data=data,
        )

        if r.status_code != 200:
            raise RuntimeError(f"Catbox upload failed: HTTP {r.status_code}")

        url = r.text.strip()

        if not url.startswith("http"):
            raise RuntimeError(f"Catbox invalid response: {url[:100]}")

        return url


async def _upload_media_for_did(
    content: bytes,
    filename: str,
    content_type: str,
) -> str:
    """ارفع ملف إلى خدمة عامة للحصول على رابط URL."""
    if settings.supabase_configured:
        try:
            from application.services.production_service import (
                _upload_to_supabase, _build_public_url,
            )

            storage = SupabaseStorageAdapter()
            unique = uuid.uuid4().hex[:12]
            suffix = Path(filename).suffix.lower() or ".bin"
            remote_path = f"talking_heads/{unique}{suffix}"

            tmp_path = Path(tempfile.gettempdir()) / f"did_{unique}{suffix}"
            tmp_path.write_bytes(content)

            try:
                await _upload_to_supabase(
                    storage=storage,
                    local_path=tmp_path,
                    remote_path=remote_path,
                    content_type=content_type,
                )
                url = await _build_public_url(storage, remote_path)
                if url and url.startswith("http"):
                    _diag(f"✅ Supabase upload: {url[:80]}...")
                    return url
            finally:
                tmp_path.unlink(missing_ok=True)

        except Exception as e:
            _diag_err(f"⚠️ Supabase upload failed: {e}", e)

    try:
        _diag("🔄 Trying Catbox...")
        url = await _upload_to_catbox(content, filename)
        _diag(f"✅ Catbox upload: {url[:80]}...")
        return url
    except Exception as e:
        _diag_err(f"⚠️ Catbox failed: {e}", e)

    try:
        _diag("🔄 Trying tmpfiles.org...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": (filename, content, content_type)}
            r = await client.post(
                "https://tmpfiles.org/api/v1/upload",
                files=files,
            )
            if r.status_code == 200:
                data = r.json()
                url = data.get("data", {}).get("url", "")
                if url:
                    direct = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    _diag(f"✅ tmpfiles upload: {direct[:80]}...")
                    return direct
    except Exception as e:
        _diag_err(f"⚠️ tmpfiles failed: {e}", e)

    raise HTTPException(
        status_code=500,
        detail=(
            "❌ فشل رفع الملفات إلى خدمة عامة.\n"
            "الحلول:\n"
            "1. تحقق من إعدادات Supabase\n"
            "2. أو حاول لاحقاً (قد تكون الخدمات مشغولة)"
        ),
    )
