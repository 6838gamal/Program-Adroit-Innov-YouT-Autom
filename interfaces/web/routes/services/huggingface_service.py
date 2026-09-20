"""HuggingFace XTTS v2 service — free voice cloning."""
import logging
from pathlib import Path

import httpx
from fastapi import HTTPException

from config.settings import settings

logger = logging.getLogger(__name__)


async def huggingface_clone_and_generate(
    reference_audio_path: Path,
    text: str,
    language: str = "ar",
) -> bytes:
    """استنساخ صوت + توليد نص عبر HuggingFace Space."""
    spaces_to_try = [
        settings.HUGGINGFACE_SPACE_URL,
        settings.HUGGINGFACE_SPACE_URL_FALLBACK,
    ]

    last_error = None

    for space_url in spaces_to_try:
        try:
            logger.info(f"🎙️ Trying HuggingFace Space: {space_url}")

            async with httpx.AsyncClient(
                timeout=settings.HUGGINGFACE_TIMEOUT
            ) as client:
                with open(reference_audio_path, "rb") as f:
                    ref_audio_bytes = f.read()

                files = {
                    "audio_prompt": ("reference.wav", ref_audio_bytes, "audio/wav"),
                }
                data = {
                    "text": text,
                    "language": language,
                }

                for endpoint in ["/api/predict", "/run/predict", "/api/queue/join"]:
                    try:
                        r = await client.post(
                            f"{space_url.rstrip('/')}{endpoint}",
                            files=files,
                            data=data,
                        )
                        if r.status_code == 200:
                            audio_data = r.content
                            if len(audio_data) > 1000:
                                logger.info(
                                    f"✅ HuggingFace success via {endpoint}"
                                )
                                return audio_data
                    except Exception as e:
                        logger.debug(f"Endpoint {endpoint} failed: {e}")
                        continue

        except Exception as e:
            last_error = str(e)
            logger.warning(f"Space {space_url} failed: {e}")
            continue

    raise HTTPException(
        status_code=503,
        detail=(
            f"فشل الاتصال بـ HuggingFace Spaces.\n"
            f"آخر خطأ: {last_error}\n\n"
            "الحلول:\n"
            "1. جرّب مرة أخرى (قد يكون Space مزدحماً)\n"
            "2. استخدم Edge TTS بدلاً منه (بدون استنساخ)"
        ),
    )
