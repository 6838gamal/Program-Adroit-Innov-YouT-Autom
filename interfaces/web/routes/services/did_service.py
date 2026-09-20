"""D-ID Talking Head service."""
import logging
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import HTTPException

from config.settings import settings

from ..core.diagnostics import _diag, _diag_err
from ..media.upload_helpers import _upload_media_for_did

logger = logging.getLogger(__name__)

DID_API_BASE = "https://api.d-id.com"


async def did_create_talk(
    image_content: bytes,
    audio_content: bytes,
    image_filename: str = "image.jpg",
) -> str:
    """🎭 إنشاء فيديو talking head من صورة + صوت."""
    if not settings.did_configured:
        raise HTTPException(
            status_code=503,
            detail="D-ID API غير مهيأ. أضف DID_API_KEY.",
        )

    img_size_mb = len(image_content) / 1024 / 1024
    aud_size_mb = len(audio_content) / 1024 / 1024

    _diag(f"🖼️  Image: {img_size_mb:.2f} MB")
    _diag(f"🔊 Audio: {aud_size_mb:.2f} MB")

    if img_size_mb > 5:
        raise HTTPException(
            status_code=400,
            detail=f"الصورة كبيرة جداً ({img_size_mb:.2f} MB). الحد 5 MB.",
        )

    if aud_size_mb > 10:
        raise HTTPException(
            status_code=400,
            detail=f"الصوت كبير جداً ({aud_size_mb:.2f} MB). استخدم نصاً أقصر.",
        )

    suffix = Path(image_filename).suffix.lower()
    if suffix not in [".jpg", ".jpeg", ".png", ".webp"]:
        suffix = ".jpg"

    img_filename = f"image{suffix}"
    img_content_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")

    aud_filename = "audio.mp3"
    aud_content_type = "audio/mpeg"

    _diag("📤 Uploading image to public host...")
    img_url = await _upload_media_for_did(
        image_content, img_filename, img_content_type
    )

    _diag("📤 Uploading audio to public host...")
    aud_url = await _upload_media_for_did(
        audio_content, aud_filename, aud_content_type
    )

    _diag(f"✅ Public URLs ready:")
    _diag(f"   🖼️  {img_url}")
    _diag(f"   🔊 {aud_url}")

    payload = {
        "source_url": img_url,
        "script": {
            "type": "audio",
            "audio_url": aud_url,
        },
        "config": {
            "stitch": True,
            "pad_audio": 0.0,
        },
    }

    headers = {
        "Authorization": settings.did_api_key_value,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    _diag(f"🎭 Sending request to D-ID...")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            r = await client.post(
                f"{DID_API_BASE}/talks",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="انتهت مهلة الاتصال بـ D-ID.",
            )
        except Exception as e:
            _diag_err(f"❌ D-ID request failed: {e}", e)
            raise HTTPException(
                status_code=502,
                detail=f"فشل الاتصال بـ D-ID: {str(e)}",
            )

    _diag(f"📡 D-ID response: status={r.status_code}")

    if r.status_code not in (200, 201):
        error_text = r.text[:800]
        user_message = f"D-ID error ({r.status_code})"

        try:
            error_data = r.json()
            err_detail = error_data.get("description") or error_data.get("message")
            if err_detail:
                user_message = f"❌ D-ID: {err_detail}"
        except Exception:
            user_message = f"❌ D-ID ({r.status_code}): {error_text}"

        if r.status_code == 400:
            user_message += (
                "\n\n💡 تحقق من:\n"
                "• الصورة: واضحة، وجه مباشر، < 5 MB\n"
                "• النص: < 1000 حرف\n"
                "• الرابط: يبدأ بـ https"
            )
        elif r.status_code == 401:
            user_message = "🔑 مفتاح D-ID غير صالح."
        elif r.status_code == 402:
            user_message = "💳 انتهى رصيدك في D-ID."
        elif r.status_code == 429:
            user_message = "⏱️ تجاوزت الحد المسموح."

        raise HTTPException(
            status_code=r.status_code,
            detail=user_message,
        )

    try:
        result = r.json()
    except Exception as e:
        _diag_err(f"❌ Failed to parse success JSON: {e}", e)
        raise HTTPException(
            status_code=500,
            detail="D-ID أعاد رداً غير متوقع.",
        )

    talk_id = result.get("id")

    if not talk_id:
        raise HTTPException(
            status_code=500,
            detail="D-ID لم يُرجع talk_id.",
        )

    _diag(f"✅ D-ID talk created: {talk_id}")

    return talk_id


async def did_get_talk_status(talk_id: str) -> Dict[str, Any]:
    if not settings.did_configured:
        raise HTTPException(status_code=503, detail="D-ID غير مهيأ")

    api_key = settings.did_api_key_value
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{DID_API_BASE}/talks/{talk_id}",
            headers={"Authorization": api_key},
        )
        if r.status_code != 200:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"فشل الحالة: {r.text[:300]}",
            )
        return r.json()
