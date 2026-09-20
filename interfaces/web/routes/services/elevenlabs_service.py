"""ElevenLabs voice cloning + TTS service."""
import logging

import httpx
from fastapi import HTTPException

from config.settings import settings

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


async def elevenlabs_create_voice(
    audio_content: bytes,
    voice_name: str,
    description: str = "",
) -> str:
    if not settings.elevenlabs_configured:
        raise HTTPException(status_code=503, detail="ElevenLabs غير مهيأ")

    api_key = settings.elevenlabs_api_key_value
    headers = {"xi-api-key": api_key}

    files = {"files": ("sample.mp3", audio_content, "audio/mpeg")}
    data = {"name": voice_name, "description": description}

    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{ELEVENLABS_API_BASE}/voices/add",
            headers=headers, files=files, data=data,
        )

        if r.status_code != 200:
            error_text = r.text[:500]
            logger.error(f"ElevenLabs failed: {error_text}")

            user_message = "فشل إنشاء الصوت"

            try:
                error_data = r.json()
                err_detail = error_data.get("detail", {})
                err_code = err_detail.get("code", "")
                err_msg = err_detail.get("message", "")

                if "paid_plan_required" in err_code or "voice cloning" in err_msg.lower():
                    user_message = (
                        "💳 ElevenLabs يتطلب خطة مدفوعة ($5/شهر) للاستنساخ.\n\n"
                        "الحلول:\n"
                        "1. استخدم Edge TTS (مجاني - أصوات جاهزة)\n"
                        "2. أو HuggingFace (مجاني - استنساخ صوتك)\n"
                        "3. أو رقّي ElevenLabs"
                    )
                elif "voices_write" in err_msg:
                    user_message = (
                        "🔑 مفتاح API لا يملك صلاحية voices_write.\n"
                        "أضفها من: https://elevenlabs.io/app/settings/api-keys"
                    )
                else:
                    user_message = f"❌ {err_msg or error_text}"
            except Exception:
                user_message = f"❌ {error_text}"

            raise HTTPException(status_code=r.status_code, detail=user_message)

        return r.json().get("voice_id")


async def elevenlabs_tts(
    text: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.0,
    speed: float = 1.0,
) -> bytes:
    if not settings.elevenlabs_configured:
        raise HTTPException(status_code=503, detail="ElevenLabs غير مهيأ")

    api_key = settings.elevenlabs_api_key_value
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        },
    }
    if speed != 1.0:
        payload["voice_settings"]["speed"] = speed

    async with httpx.AsyncClient(timeout=240.0) as client:
        r = await client.post(
            f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
            headers=headers, json=payload,
        )
        if r.status_code != 200:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"فشل التوليد: {r.text[:300]}",
            )
        return r.content


async def elevenlabs_delete_voice(voice_id: str) -> bool:
    if not settings.elevenlabs_configured:
        return False

    api_key = settings.elevenlabs_api_key_value
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(
                f"{ELEVENLABS_API_BASE}/voices/{voice_id}",
                headers={"xi-api-key": api_key},
            )
            return r.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to delete voice {voice_id}: {e}")
        return False
