"""Voice endpoints: Edge TTS, HuggingFace, ElevenLabs, cache, saved voices, import/export, providers."""
import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository

from ..core.directories import (
    CACHE_DIR,
    CLONED_VOICES_DIR,
    HF_VOICES_DIR,
)
from ..core.hashing import _compute_text_hash
from ..media.ffmpeg_helpers import _get_audio_duration
from ..services.edge_tts_service import edge_tts_generate
from ..services.elevenlabs_service import (
    ELEVENLABS_API_BASE,
    elevenlabs_create_voice,
    elevenlabs_delete_voice,
    elevenlabs_tts,
)
from ..services.huggingface_service import huggingface_clone_and_generate

router = APIRouter()


# ============================================================
# 🔊 EDGE TTS
# ============================================================

@router.get("/api/voice/edge-voices")
async def list_edge_voices():
    """اعرض أصوات Edge TTS المتاحة."""
    return {
        "success": True,
        "count": len(settings.EDGE_TTS_ARABIC_VOICES),
        "voices": settings.EDGE_TTS_ARABIC_VOICES,
    }


@router.post("/api/voice/edge-generate")
async def edge_tts_generate_endpoint(
    text: str = Form(...),
    voice: str = Form("ar-SA-HamedNeural"),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz"),
    project_id: str = Form(""),
):
    """🎙️ Edge TTS — مجاني تماماً."""
    try:
        text = text.strip()
        if not text:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(text) > settings.EDGE_TTS_MAX_CHARS:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"النص طويل جداً (الحد {settings.EDGE_TTS_MAX_CHARS})",
                },
                status_code=400,
            )

        logger_msg = f"🎙️ Edge TTS: voice={voice}, chars={len(text)}"
        print(logger_msg, flush=True)

        audio_bytes = await edge_tts_generate(
            text=text, voice=voice,
            rate=rate, volume=volume, pitch=pitch,
        )

        out_name = f"edge_{uuid.uuid4().hex[:12]}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)
        url = f"/static/media/cloned_voices/{out_name}"

        print(f"✅ Edge TTS: {out_name} ({duration:.2f}s)", flush=True)

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/mpeg",
            filename=out_name,
            headers={
                "X-Cloned-URL": url,
                "X-Duration": str(round(duration, 2)),
                "X-Voice-ID": voice,
                "X-Provider": "edge_tts",
                "X-Script-Length": str(len(text)),
                "Access-Control-Expose-Headers":
                    "X-Cloned-URL, X-Duration, X-Voice-ID, X-Provider, X-Script-Length",
            },
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Edge TTS failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# 🎙️ HUGGINGFACE — XTTS v2
# ============================================================

@router.post("/api/voice/hf-clone")
async def huggingface_clone_voice(
    file: UploadFile = File(...),
    text: str = Form(...),
    language: str = Form("ar"),
    project_id: str = Form(""),
):
    """🎙️ استنساخ صوت + توليد نص عبر HuggingFace Spaces."""
    import asyncio

    tmp_ref = None
    tmp_wav = None
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        if len(content) < 6 * 1024:
            return JSONResponse(
                {
                    "success": False,
                    "error": "التسجيل قصير جداً. الحد الأدنى ~6 ثواني.",
                },
                status_code=400,
            )

        text = text.strip()
        if not text:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(text) > settings.HUGGINGFACE_MAX_CHARS:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"النص طويل جداً (الحد {settings.HUGGINGFACE_MAX_CHARS})",
                },
                status_code=400,
            )

        suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_ref = Path(tmp.name)

        tmp_wav = tmp_ref.with_suffix(".wav")
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", str(tmp_ref),
            "-ar", "22050", "-ac", "1",
            "-c:a", "pcm_s16le", str(tmp_wav),
        ]
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if not tmp_wav.exists():
            raise RuntimeError("فشل تحويل الصوت")

        print(
            f"🎙️ HF clone: text={len(text)}, lang={language}",
            flush=True,
        )

        audio_bytes = await huggingface_clone_and_generate(
            reference_audio_path=tmp_wav,
            text=text,
            language=language,
        )

        out_name = f"hf_{uuid.uuid4().hex[:12]}.wav"
        tmp_out = HF_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)
        url = f"/static/media/hf_voices/{out_name}"

        print(f"✅ HF clone: {out_name} ({duration:.2f}s)", flush=True)

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/wav",
            filename=out_name,
            headers={
                "X-Cloned-URL": url,
                "X-Duration": str(round(duration, 2)),
                "X-Provider": "huggingface",
                "X-Script-Length": str(len(text)),
                "Access-Control-Expose-Headers":
                    "X-Cloned-URL, X-Duration, X-Provider, X-Script-Length",
            },
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("HF clone failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )
    finally:
        if tmp_ref and tmp_ref.exists():
            tmp_ref.unlink(missing_ok=True)
        if tmp_wav and tmp_wav.exists():
            tmp_wav.unlink(missing_ok=True)


# ============================================================
# 🎯 UNIFIED VOICE GENERATION
# ============================================================

@router.post("/api/voice/generate-unified")
async def generate_voice_unified(
    provider: str = Form("auto"),
    text: str = Form(...),
    reference_audio: Optional[UploadFile] = File(None),
    voice_id: str = Form(""),
    edge_voice: str = Form("ar-SA-HamedNeural"),
    language: str = Form("ar"),
    project_id: str = Form(""),
    speed: float = Form(1.0),
):
    """🎙️ توليد صوت موحد — يختار المزود تلقائياً."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    try:
        text = text.strip()
        if not text:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if provider == "auto":
            if voice_id and settings.elevenlabs_configured:
                provider = "elevenlabs"
            elif reference_audio:
                provider = "huggingface"
            else:
                provider = "edge_tts"

        logger.info(
            f"🎙️ Unified voice: provider={provider}, chars={len(text)}"
        )

        if provider == "elevenlabs":
            if not voice_id:
                return JSONResponse(
                    {"success": False, "error": "voice_id مطلوب لـ ElevenLabs"},
                    status_code=400,
                )
            try:
                audio_bytes = await elevenlabs_tts(
                    text=text, voice_id=voice_id, speed=speed,
                )
                out_name = f"el_{uuid.uuid4().hex[:12]}.mp3"
                tmp_out = CLONED_VOICES_DIR / out_name
                tmp_out.write_bytes(audio_bytes)
                duration = await _get_audio_duration(tmp_out)

                return FileResponse(
                    path=str(tmp_out),
                    media_type="audio/mpeg",
                    filename=out_name,
                    headers={
                        "X-Cloned-URL": f"/static/media/cloned_voices/{out_name}",
                        "X-Duration": str(round(duration, 2)),
                        "X-Provider": "elevenlabs",
                        "X-Voice-ID": voice_id,
                        "Access-Control-Expose-Headers":
                            "X-Cloned-URL, X-Duration, X-Provider, X-Voice-ID",
                    },
                )
            except Exception as e:
                logger.warning(
                    f"ElevenLabs failed: {e}, falling back to Edge TTS"
                )
                provider = "edge_tts"

        if provider == "huggingface" and reference_audio:
            tmp_ref = None
            tmp_wav = None
            try:
                content = await reference_audio.read()
                if len(content) < 6 * 1024:
                    logger.warning(
                        "Reference too short, falling back to Edge TTS"
                    )
                    provider = "edge_tts"
                else:
                    suffix = (
                        Path(reference_audio.filename or "audio.webm")
                        .suffix.lower() or ".webm"
                    )
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=suffix
                    ) as tmp:
                        tmp.write(content)
                        tmp_ref = Path(tmp.name)

                    tmp_wav = tmp_ref.with_suffix(".wav")
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", str(tmp_ref),
                        "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le",
                        str(tmp_wav),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()

                    if tmp_wav.exists():
                        audio_bytes = await huggingface_clone_and_generate(
                            reference_audio_path=tmp_wav,
                            text=text,
                            language=language,
                        )
                        out_name = f"hf_{uuid.uuid4().hex[:12]}.wav"
                        tmp_out = HF_VOICES_DIR / out_name
                        tmp_out.write_bytes(audio_bytes)
                        duration = await _get_audio_duration(tmp_out)

                        return FileResponse(
                            path=str(tmp_out),
                            media_type="audio/wav",
                            filename=out_name,
                            headers={
                                "X-Cloned-URL": f"/static/media/hf_voices/{out_name}",
                                "X-Duration": str(round(duration, 2)),
                                "X-Provider": "huggingface",
                                "Access-Control-Expose-Headers":
                                    "X-Cloned-URL, X-Duration, X-Provider",
                            },
                        )
            except Exception as e:
                logger.warning(
                    f"HuggingFace failed: {e}, falling back to Edge TTS"
                )
                provider = "edge_tts"
            finally:
                if tmp_ref and tmp_ref.exists():
                    tmp_ref.unlink(missing_ok=True)
                if tmp_wav and tmp_wav.exists():
                    tmp_wav.unlink(missing_ok=True)

        if provider == "edge_tts" or provider == "auto":
            rate_percent = int((speed - 1) * 100)
            rate_str = (
                f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"
            )

            audio_bytes = await edge_tts_generate(
                text=text,
                voice=edge_voice,
                rate=rate_str,
            )

            out_name = f"edge_{uuid.uuid4().hex[:12]}.mp3"
            tmp_out = CLONED_VOICES_DIR / out_name
            tmp_out.write_bytes(audio_bytes)
            duration = await _get_audio_duration(tmp_out)

            return FileResponse(
                path=str(tmp_out),
                media_type="audio/mpeg",
                filename=out_name,
                headers={
                    "X-Cloned-URL": f"/static/media/cloned_voices/{out_name}",
                    "X-Duration": str(round(duration, 2)),
                    "X-Provider": "edge_tts",
                    "X-Voice-ID": edge_voice,
                    "Access-Control-Expose-Headers":
                        "X-Cloned-URL, X-Duration, X-Provider, X-Voice-ID",
                },
            )

        return JSONResponse(
            {"success": False, "error": f"مزود غير معروف: {provider}"},
            status_code=400,
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(
            "Unified voice generation failed"
        )
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# VOICE CLONE
# ============================================================

@router.post("/api/voice/clone")
async def clone_user_voice(
    file: UploadFile = File(...),
    name: str = Form("MyVoice"),
    project_id: str = Form(""),
    description: str = Form(""),
):
    """🎙️ استنساخ صوت — يختار المزود تلقائياً."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        if len(content) < 6 * 1024:
            return JSONResponse(
                {"success": False, "error": "التسجيل قصير جداً (~6 ثواني على الأقل)"},
                status_code=400,
            )

        if settings.elevenlabs_configured:
            try:
                voice_id = await elevenlabs_create_voice(
                    audio_content=content,
                    voice_name=f"{name}_{uuid.uuid4().hex[:6]}",
                    description=description,
                )
                return {
                    "success": True,
                    "voice_id": voice_id,
                    "name": name,
                    "provider": "elevenlabs",
                    "message": "✅ تم الاستنساخ عبر ElevenLabs",
                }
            except Exception as e:
                logger.warning(f"ElevenLabs failed: {e}")

        return {
            "success": True,
            "voice_id": f"hf_temp_{uuid.uuid4().hex[:8]}",
            "name": name,
            "provider": "huggingface",
            "temporary": True,
            "message": (
                "✅ HuggingFace جاهز للاستنساخ.\n"
                "⚠️ HuggingFace لا يحفظ الأصوات.\n\n"
                "💡 للحصول على حفظ دائم، رقّي ElevenLabs إلى خطة Starter."
            ),
        }

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Voice clone failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# VOICE PREVIEW
# ============================================================

@router.post("/api/voice/preview")
async def preview_saved_voice(
    voice_id: str = Form(...),
    text: str = Form("مرحباً، هذا اختبار لصوتي."),
):
    """معاينة سريعة لصوت محفوظ (Edge TTS)."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        if len(text) > 200:
            text = text[:200]

        audio_bytes = await edge_tts_generate(
            text=text,
            voice=(
                voice_id if voice_id.startswith("ar-")
                else "ar-SA-HamedNeural"
            ),
        )

        out_name = f"preview_{uuid.uuid4().hex[:10]}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/mpeg",
            filename=out_name,
            headers={
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
            },
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Voice preview failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# GENERATE-CACHED (Edge TTS)
# ============================================================

@router.post("/api/voice/generate-cached")
async def generate_with_cache(
    voice_id: str = Form("ar-SA-HamedNeural"),
    script: str = Form(...),
    project_id: str = Form(""),
    use_cache: str = Form("true"),
    speed: float = Form(1.0),
):
    """توليد صوت مع Cache — يستخدم Edge TTS."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        script = script.strip()
        if not script:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(script) > settings.EDGE_TTS_MAX_CHARS:
            return JSONResponse(
                {"success": False, "error": "النص طويل جداً"},
                status_code=400,
            )

        cache_key = _compute_text_hash(voice_id, script, {"speed": speed})
        cached_file = CACHE_DIR / f"{cache_key}.mp3"

        if use_cache.lower() == "true" and cached_file.exists():
            logger.info(f"💾 Cache HIT: {cache_key}")
            duration = await _get_audio_duration(cached_file)
            url = f"/static/media/cloned_voices/cache/{cached_file.name}"

            return FileResponse(
                path=str(cached_file),
                media_type="audio/mpeg",
                filename=f"cached_{cache_key}.mp3",
                headers={
                    "X-Cloned-URL": url,
                    "X-Duration": str(round(duration, 2)),
                    "X-Voice-ID": voice_id,
                    "X-Cache-Hit": "true",
                    "X-Provider": "edge_tts",
                    "Access-Control-Expose-Headers":
                        "X-Cloned-URL, X-Duration, X-Voice-ID, X-Cache-Hit, X-Provider",
                },
            )

        rate_percent = int((speed - 1) * 100)
        rate_str = (
            f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"
        )

        audio_bytes = await edge_tts_generate(
            text=script,
            voice=voice_id,
            rate=rate_str,
        )

        cached_file.write_bytes(audio_bytes)

        out_name = f"edge_{cache_key}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        if not tmp_out.exists():
            tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)
        url = f"/static/media/cloned_voices/{out_name}"

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/mpeg",
            filename=out_name,
            headers={
                "X-Cloned-URL": url,
                "X-Duration": str(round(duration, 2)),
                "X-Voice-ID": voice_id,
                "X-Cache-Hit": "false",
                "X-Provider": "edge_tts",
                "Access-Control-Expose-Headers":
                    "X-Cloned-URL, X-Duration, X-Voice-ID, X-Cache-Hit, X-Provider",
            },
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(
            "Generate with cache failed"
        )
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# OLD GENERATE (توافق)
# ============================================================

@router.post("/api/voice/generate")
async def generate_with_cloned_voice(
    voice_id: str = Form(...),
    script: str = Form(...),
    project_id: str = Form(""),
    stability: float = Form(0.5),
    similarity_boost: float = Form(0.75),
    style: float = Form(0.0),
    speed: float = Form(1.0),
    model_id: str = Form("eleven_multilingual_v2"),
):
    """توليد صوت (توافق مع الكود القديم)."""
    import logging
    logger = logging.getLogger(__name__)

    if voice_id.startswith(("ar-", "en-", "fr-", "de-", "es-")):
        return await generate_with_cache(
            voice_id=voice_id,
            script=script,
            project_id=project_id,
            use_cache="true",
            speed=speed,
        )

    try:
        if not settings.elevenlabs_configured:
            return await generate_with_cache(
                voice_id="ar-SA-HamedNeural",
                script=script,
                project_id=project_id,
                use_cache="true",
                speed=speed,
            )

        audio_bytes = await elevenlabs_tts(
            text=script, voice_id=voice_id,
            model_id=model_id, stability=stability,
            similarity_boost=similarity_boost,
            style=style, speed=speed,
        )

        out_name = f"cloned_{uuid.uuid4().hex[:12]}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)
        duration = await _get_audio_duration(tmp_out)

        url = f"/static/media/cloned_voices/{out_name}"

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/mpeg",
            filename=out_name,
            headers={
                "X-Cloned-URL": url,
                "X-Duration": str(round(duration, 2)),
                "X-Voice-ID": voice_id,
                "X-Provider": "elevenlabs",
                "Access-Control-Expose-Headers":
                    "X-Cloned-URL, X-Duration, X-Voice-ID, X-Provider",
            },
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Voice generation failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# SAVED VOICES — CRUD
# ============================================================

@router.get("/api/voice/saved/{project_id}")
async def list_saved_voices(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    saved_voices = data.get("cloned_voices", []) or []

    return {
        "success": True,
        "count": len(saved_voices),
        "voices": saved_voices,
    }


@router.post("/api/voice/saved/{project_id}")
async def save_voice_to_project(
    project_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    voice_id = payload.get("voice_id")
    if not voice_id:
        return JSONResponse({"error": "voice_id مطلوب"}, status_code=400)

    data = getattr(project, "data", None) or {}
    saved_voices = data.get("cloned_voices", []) or []

    existing = next(
        (v for v in saved_voices if v.get("voice_id") == voice_id), None
    )
    if existing:
        return {
            "success": True,
            "voice": existing,
            "message": "الصوت محفوظ مسبقاً",
        }

    new_voice = {
        "id": f"voice-{uuid.uuid4().hex[:12]}",
        "voice_id": voice_id,
        "name": payload.get("name", "My Voice"),
        "display_name": payload.get(
            "display_name", payload.get("name", "صوتي")
        ),
        "provider": payload.get("provider", "huggingface"),
        "created_at": datetime.utcnow().isoformat(),
        "preview_url": payload.get("preview_url"),
        "description": payload.get("description", ""),
        "temporary": payload.get("temporary", False),
    }

    saved_voices.append(new_voice)
    data["cloned_voices"] = saved_voices

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    import logging
    logging.getLogger(__name__).info(
        f"✅ Voice saved: {voice_id} → project {project_id}"
    )

    return {
        "success": True,
        "voice": new_voice,
        "message": "✅ تم حفظ الصوت في المشروع",
    }


@router.delete("/api/voice/saved/{project_id}/{voice_record_id}")
async def delete_saved_voice(
    project_id: str,
    voice_record_id: str,
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    saved_voices = data.get("cloned_voices", []) or []

    target = next(
        (v for v in saved_voices if v.get("id") == voice_record_id), None
    )
    if not target:
        return JSONResponse({"error": "Voice not found"}, status_code=404)

    voice_id = target.get("voice_id")
    provider = target.get("provider", "")

    if voice_id and provider == "elevenlabs":
        try:
            await elevenlabs_delete_voice(voice_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to delete from ElevenLabs: {e}"
            )

    data["cloned_voices"] = [
        v for v in saved_voices if v.get("id") != voice_record_id
    ]
    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {
        "success": True,
        "deleted_id": voice_record_id,
        "voice_id": voice_id,
    }


@router.patch("/api/voice/saved/{project_id}/{voice_record_id}")
async def update_saved_voice(
    project_id: str,
    voice_record_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    saved_voices = data.get("cloned_voices", []) or []

    target = next(
        (v for v in saved_voices if v.get("id") == voice_record_id), None
    )
    if not target:
        return JSONResponse({"error": "Voice not found"}, status_code=404)

    for field in ("display_name", "description"):
        if field in payload:
            target[field] = payload[field]

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "voice": target}


# ============================================================
# EXPORT / IMPORT
# ============================================================

@router.get("/api/voice/export/{project_id}")
async def export_project_voices(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    saved_voices = data.get("cloned_voices", []) or []

    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "project_id": project_id,
        "project_title": project.title,
        "provider": settings.VOICE_CLONING_PROVIDER,
        "voices_count": len(saved_voices),
        "voices": saved_voices,
        "metadata": {
            "app": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
        },
    }

    content = json.dumps(export_data, ensure_ascii=False, indent=2)
    filename = (
        f"voices_{project_id[:8]}_{int(datetime.utcnow().timestamp())}.json"
    )

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/api/voice/import/{project_id}")
async def import_project_voices(
    project_id: str,
    file: UploadFile = File(...),
    merge: str = Form("true"),
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    content = await file.read()
    try:
        import_data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return JSONResponse(
            {"success": False, "error": f"ملف JSON غير صالح: {e}"},
            status_code=400,
        )

    incoming_voices = import_data.get("voices", [])
    if not isinstance(incoming_voices, list):
        return JSONResponse(
            {"success": False, "error": "بنية الملف غير صحيحة"},
            status_code=400,
        )

    data = getattr(project, "data", None) or {}
    existing_voices = data.get("cloned_voices", []) or []

    added = 0
    skipped = 0

    if merge.lower() == "true":
        existing_ids = {v.get("voice_id") for v in existing_voices}

        for voice in incoming_voices:
            if not isinstance(voice, dict):
                continue
            v_id = voice.get("voice_id")
            if not v_id or v_id in existing_ids:
                skipped += 1
                continue

            voice.setdefault("id", f"voice-{uuid.uuid4().hex[:12]}")
            voice.setdefault("provider", "huggingface")
            voice.setdefault("created_at", datetime.utcnow().isoformat())
            voice.setdefault("imported_at", datetime.utcnow().isoformat())
            voice["imported"] = True

            existing_voices.append(voice)
            existing_ids.add(v_id)
            added += 1
    else:
        new_list = []
        for voice in incoming_voices:
            if not isinstance(voice, dict):
                continue
            voice.setdefault("id", f"voice-{uuid.uuid4().hex[:12]}")
            voice.setdefault("provider", "huggingface")
            voice.setdefault("created_at", datetime.utcnow().isoformat())
            voice["imported"] = True
            new_list.append(voice)
            added += 1

        existing_voices = new_list

    data["cloned_voices"] = existing_voices

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    import logging
    logging.getLogger(__name__).info(
        f"📥 Imported {added} voices (skipped {skipped})"
    )

    return {
        "success": True,
        "added": added,
        "skipped": skipped,
        "total": len(existing_voices),
        "message": f"✅ تم استيراد {added} صوت (تم تخطي {skipped})",
    }


# ============================================================
# CACHE MANAGEMENT
# ============================================================

@router.get("/api/voice/cache/stats")
async def get_cache_stats():
    files = list(CACHE_DIR.glob("*.mp3"))
    total_size = sum(f.stat().st_size for f in files)

    return {
        "success": True,
        "files": len(files),
        "total_size": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "cache_dir": str(CACHE_DIR),
    }


@router.delete("/api/voice/cache/clear")
async def clear_cache():
    import logging
    logger = logging.getLogger(__name__)

    deleted = 0
    for f in CACHE_DIR.glob("*.mp3"):
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete {f}: {e}")

    return {"success": True, "deleted": deleted}


# ============================================================
# PROVIDERS INFO
# ============================================================

@router.get("/api/voice/providers")
async def get_voice_providers():
    """اعرض المزودين المتاحين."""
    return {
        "success": True,
        "providers": [
            {
                "id": "edge_tts",
                "name": "Edge TTS (مجاني)",
                "description": "أصوات احترافية جاهزة — بدون استنساخ",
                "available": settings.EDGE_TTS_ENABLED,
                "requires_key": False,
                "supports_cloning": False,
                "languages": ["ar", "en", "fr", "de", "es", "+36 more"],
            },
            {
                "id": "huggingface",
                "name": "HuggingFace XTTS (مجاني)",
                "description": "استنساخ صوتك — مجاني تماماً",
                "available": True,
                "requires_key": False,
                "supports_cloning": True,
                "note": "قد يكون بطيئاً (2-5 دقائق) وقد يفشل عند الازدحام",
            },
            {
                "id": "elevenlabs",
                "name": "ElevenLabs (مدفوع)",
                "description": "الأفضل جودة — يحتاج خطة $5/شهر",
                "available": settings.elevenlabs_configured,
                "requires_key": True,
                "supports_cloning": True,
                "note": "الخطة المجانية لا تدعم الاستنساخ",
            },
            {
                "id": "did_talking_head",
                "name": "D-ID Talking Head",
                "description": "تحريك صورة الشخص",
                "available": settings.did_configured,
                "requires_key": True,
                "supports_cloning": False,
            },
        ],
    }


@router.get("/api/voice/check-permissions")
async def check_permissions():
    """تحقق من حالة كل مزود."""
    elevenlabs_ok = False
    elevenlabs_tier = None

    if settings.elevenlabs_configured:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{ELEVENLABS_API_BASE}/user",
                    headers={
                        "xi-api-key": settings.elevenlabs_api_key_value
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    elevenlabs_ok = True
                    elevenlabs_tier = data.get(
                        "subscription", {}
                    ).get("tier", "unknown")
        except Exception:
            pass

    return {
        "success": True,
        "edge_tts": {
            "available": settings.EDGE_TTS_ENABLED,
            "free": True,
            "supports_cloning": False,
        },
        "huggingface": {
            "available": True,
            "free": True,
            "supports_cloning": True,
            "space_url": settings.HUGGINGFACE_SPACE_URL,
        },
        "elevenlabs": {
            "available": elevenlabs_ok,
            "tier": elevenlabs_tier,
            "supports_cloning": elevenlabs_tier in [
                "starter", "creator", "pro", "scale", "business"
            ],
            "free_tier_note": "Free tier does NOT support voice cloning",
        },
        "did_talking_head": {
            "available": settings.did_configured,
            "free_tier_minutes": 5,
        },
    }
