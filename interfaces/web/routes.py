"""Jinja2 HTML page routes with multi-provider voice cloning."""
import uuid
import json
import logging
import tempfile
import asyncio
import subprocess
import hashlib
import base64
import shutil
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx

from fastapi import (
    APIRouter, Request, Depends, HTTPException,
    UploadFile, File, Form, BackgroundTasks
)
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent.parent / "templates")
)
router = APIRouter(tags=["web"])
logger = logging.getLogger(__name__)


# ============================================================
# DIAGNOSTIC HELPERS
# ============================================================

def _diag(msg: str) -> None:
    """Print + log a diagnostic message immediately."""
    print(msg, flush=True)
    logger.info(msg)


def _diag_err(msg: str, exc: Optional[BaseException] = None) -> None:
    """Print + log an error."""
    print(msg, flush=True)
    if exc is not None:
        logger.error(msg, exc_info=exc)
    else:
        logger.error(msg)


# ============================================================
# JINJA2 CUSTOM FILTERS
# ============================================================

def _format_duration(seconds) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_number(value) -> str:
    if value is None:
        return "0"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


templates.env.filters["format_duration"] = _format_duration
templates.env.filters["format_number"] = _format_number


# ============================================================
# HELPERS
# ============================================================

def get_supabase_config() -> dict:
    return {
        "url": settings.SUPABASE_URL,
        "public_key": settings.supabase_public_key_value,
        "bucket": settings.SUPABASE_BUCKET,
        "configured": settings.supabase_configured,
        "storage_type": settings.STORAGE_TYPE,
    }


async def _resolve_video_url(project) -> Optional[str]:
    video_url = getattr(project, "video_url", None)
    if not video_url:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            video_url = data.get("video_url")

    if video_url and isinstance(video_url, str) and video_url.startswith("http"):
        return video_url

    storage_path = getattr(project, "storage_path", None)
    if not storage_path:
        storage_path = getattr(project, "output_path", None)

    if not storage_path:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            storage_path = data.get("video_path") or data.get("storage_path")

    if not storage_path:
        alt = getattr(project, "result_url", None) or getattr(project, "output_url", None)
        if alt and isinstance(alt, str) and alt.startswith("http"):
            return alt

    if not storage_path:
        return video_url

    try:
        storage = SupabaseStorageAdapter()
        if hasattr(storage, "get_public_url"):
            public = await storage.get_public_url(storage_path)
            if public:
                return public
        if settings.supabase_configured:
            bucket = settings.SUPABASE_BUCKET
            base = settings.SUPABASE_URL.rstrip("/")
            return f"{base}/storage/v1/object/public/{bucket}/{storage_path.lstrip('/')}"
    except Exception as e:
        logger.warning(f"Failed to build video_url from storage_path: {e}")

    return video_url


async def _resolve_thumbnail_url(project) -> Optional[str]:
    thumb_url = getattr(project, "thumbnail_url", None)
    if not thumb_url:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            thumb_url = data.get("thumbnail")
    if thumb_url and isinstance(thumb_url, str) and thumb_url.startswith("http"):
        return thumb_url
    return thumb_url


# ============================================================
# DIRECTORIES
# ============================================================

VOICEOVER_DIR = Path(settings.MEDIA_DIR) / "voiceovers"
VOICEOVER_DIR.mkdir(parents=True, exist_ok=True)

CLONED_VOICES_DIR = Path(settings.MEDIA_DIR) / "cloned_voices"
CLONED_VOICES_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = CLONED_VOICES_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HF_VOICES_DIR = Path(settings.MEDIA_DIR) / "hf_voices"
HF_VOICES_DIR.mkdir(parents=True, exist_ok=True)

TALKING_HEADS_DIR = Path(settings.MEDIA_DIR) / "talking_heads"
TALKING_HEADS_DIR.mkdir(parents=True, exist_ok=True)

PROPERTY_ASSETS_DIR = Path(settings.MEDIA_DIR) / "property_assets"
PROPERTY_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

PROPERTY_VIDEOS_DIR = Path(settings.MEDIA_DIR) / "property_videos"
PROPERTY_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# ✅ مجلد الـ jobs المحلي (fallback)
JOBS_DIR = Path(settings.MEDIA_DIR) / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# ✅ مجلد الـ jobs داخل Supabase Storage
JOBS_STORAGE_PREFIX = "jobs"

VOICEOVER_MAX_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a",
    "audio/x-m4a", "audio/aac", "audio/flac",
    "video/webm",
}

# ذاكرات مؤقتة
CLONED_VOICE_CACHE: Dict[str, str] = {}
TALKING_HEAD_JOBS: Dict[str, Dict[str, Any]] = {}


# ============================================================
# ✅ JOB PERSISTENCE v2 — Supabase Storage + fallback محلي
# ============================================================

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
        # احذف الحقول الثقيلة
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
    """
    اقرأ حالة الـ job من Supabase Storage.
    """
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
                        logger.warning(f"Load job HTTP {r.status_code}: {r.text[:200]}")

            except Exception as e:
                logger.warning(f"Supabase load job failed: {e}")

        # Fallback إلى القرص المحلي
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
    job = TALKING_HEAD_JOBS.get(job_id) or await _load_job_from_storage(job_id) or {"id": job_id}
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


async def _get_audio_duration(file_path: Path) -> float:
    """احسب مدة ملف صوتي باستخدام ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip() or 0)
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return 0.0


async def _get_video_duration(file_path: Path) -> float:
    """احسب مدة ملف فيديو باستخدام ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        duration = float(stdout.decode().strip() or 0)
        return duration
    except Exception as e:
        logger.warning(f"ffprobe video failed: {e}")
        return 0.0


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


def _compute_text_hash(voice_id: str, text: str, settings_dict: dict) -> str:
    """احسب hash فريد للنص + الصوت + الإعدادات."""
    payload = f"{voice_id}|{text}|{json.dumps(settings_dict, sort_keys=True)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


# ============================================================
# 🔊 EDGE TTS
# ============================================================

async def _edge_tts_generate(
    text: str,
    voice: str = "ar-SA-HamedNeural",
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """توليد صوت عبر Edge TTS (Microsoft)."""
    try:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        if not audio_chunks:
            raise RuntimeError("Edge TTS returned no audio")

        return b"".join(audio_chunks)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Edge TTS غير مثبت. شغّل: pip install edge-tts",
        )


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

        logger.info(f"🎙️ Edge TTS: voice={voice}, chars={len(text)}")

        audio_bytes = await _edge_tts_generate(
            text=text, voice=voice,
            rate=rate, volume=volume, pitch=pitch,
        )

        out_name = f"edge_{uuid.uuid4().hex[:12]}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)
        url = f"/static/media/cloned_voices/{out_name}"

        logger.info(f"✅ Edge TTS: {out_name} ({duration:.2f}s)")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Edge TTS failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# 🎙️ HUGGINGFACE — XTTS v2
# ============================================================

async def _huggingface_clone_and_generate(
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

            async with httpx.AsyncClient(timeout=settings.HUGGINGFACE_TIMEOUT) as client:
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
                                logger.info(f"✅ HuggingFace success via {endpoint}")
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


@router.post("/api/voice/hf-clone")
async def huggingface_clone_voice(
    file: UploadFile = File(...),
    text: str = Form(...),
    language: str = Form("ar"),
    project_id: str = Form(""),
):
    """🎙️ استنساخ صوت + توليد نص عبر HuggingFace Spaces."""
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

        logger.info(f"🎙️ HF clone: text={len(text)}, lang={language}")

        audio_bytes = await _huggingface_clone_and_generate(
            reference_audio_path=tmp_wav,
            text=text,
            language=language,
        )

        out_name = f"hf_{uuid.uuid4().hex[:12]}.wav"
        tmp_out = HF_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)
        url = f"/static/media/hf_voices/{out_name}"

        logger.info(f"✅ HF clone: {out_name} ({duration:.2f}s)")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("HF clone failed")
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
# 🎙️ ELEVENLABS
# ============================================================

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


async def _elevenlabs_create_voice(
    audio_content: bytes, voice_name: str, description: str = "",
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


async def _elevenlabs_tts(
    text: str, voice_id: str, model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5, similarity_boost: float = 0.75,
    style: float = 0.0, speed: float = 1.0,
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


async def _elevenlabs_delete_voice(voice_id: str) -> bool:
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


# ============================================================
# 🎭 TALKING HEAD — D-ID
# ============================================================

DID_API_BASE = "https://api.d-id.com"


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
    # ── 1. جرّب Supabase ──
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

    # ── 2. جرّب Catbox ──
    try:
        _diag("🔄 Trying Catbox...")
        url = await _upload_to_catbox(content, filename)
        _diag(f"✅ Catbox upload: {url[:80]}...")
        return url
    except Exception as e:
        _diag_err(f"⚠️ Catbox failed: {e}", e)

    # ── 3. جرّب tmpfiles.org ──
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


async def _did_create_talk(
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


async def _did_get_talk_status(talk_id: str) -> Dict[str, Any]:
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


# ============================================================
# DASHBOARD
# ============================================================

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_db)):
    project_repo = SQLProjectRepository(session)
    job_repo = SQLRenderJobRepository(session)

    total_projects = await project_repo.count()
    recent_projects = await project_repo.list_all(limit=5)
    recent_jobs = await job_repo.list_recent(limit=5)

    return templates.TemplateResponse(request, "dashboard.html", {
        "total_projects": total_projects,
        "recent_projects": recent_projects,
        "recent_jobs": recent_jobs,
        "active_page": "dashboard",
        "supabase": get_supabase_config(),
    })


# ============================================================
# PROJECTS
# ============================================================

@router.get("/projects", response_class=HTMLResponse)
async def projects_page(
    request: Request,
    search: str = "",
    status: str = "",
    session: AsyncSession = Depends(get_db),
):
    repo = SQLProjectRepository(session)
    projects = await repo.list_all(
        limit=20, offset=0,
        search=search or None,
        status=status or None,
    )
    total = await repo.count(status=status or None)
    return templates.TemplateResponse(request, "projects/list.html", {
        "projects": projects,
        "total": total,
        "search": search,
        "status_filter": status,
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


@router.get("/projects/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    return templates.TemplateResponse(request, "projects/create.html", {
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


@router.get("/projects/{project_id}/timeline", response_class=HTMLResponse)
async def project_timeline(
    project_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLProjectRepository(session)
    project = await repo.get(uuid.UUID(project_id))
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    scenes = []
    try:
        if hasattr(project, "timeline") and project.timeline:
            tl = project.timeline
            for scene in (tl.scenes if hasattr(tl, "scenes") else []):
                scenes.append({
                    "id": str(scene.id),
                    "title": getattr(scene, "title", None) or f"مشهد {len(scenes)+1}",
                    "start_time": float(getattr(scene, "start_time", 0)),
                    "end_time": float(getattr(scene, "end_time", 0)),
                    "duration": float(getattr(scene, "duration", 0)),
                    "content": getattr(scene, "content", ""),
                })
    except Exception:
        pass

    if not scenes and project.script:
        paragraphs = [p.strip() for p in project.script.split("\n\n") if p.strip()]
        t = 0.0
        for i, para in enumerate(paragraphs):
            words = len(para.split())
            duration = max(words / 2.5, 2.0)
            scenes.append({
                "id": str(i),
                "title": f"مشهد {i+1}",
                "start_time": round(t, 2),
                "end_time": round(t + duration, 2),
                "duration": round(duration, 2),
                "content": para[:120],
            })
            t += duration

    voiceover_clips = []
    saved_voices = []
    if hasattr(project, "data") and isinstance(project.data, dict):
        voiceover_clips = [
            c for c in (project.data.get("clips") or [])
            if isinstance(c, dict) and c.get("type") == "audio"
        ]
        saved_voices = project.data.get("cloned_voices", []) or []

    return templates.TemplateResponse(request, "projects/timeline.html", {
        "project": project,
        "scenes": scenes,
        "scenes_json": json.dumps(scenes, ensure_ascii=False),
        "voiceover_clips": voiceover_clips,
        "saved_voices": saved_voices,
        "elevenlabs_configured": settings.elevenlabs_configured,
        "did_configured": settings.did_configured,
        "edge_tts_enabled": settings.EDGE_TTS_ENABLED,
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    project_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLProjectRepository(session)
    job_repo = SQLRenderJobRepository(session)
    project = await repo.get(uuid.UUID(project_id))
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    render_jobs = await job_repo.list_for_project(project.id)
    video_url = await _resolve_video_url(project)
    thumbnail_url = await _resolve_thumbnail_url(project)

    return templates.TemplateResponse(request, "projects/detail.html", {
        "project": project,
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "render_jobs": render_jobs,
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


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

        logger.info(f"🎙️ Unified voice: provider={provider}, chars={len(text)}")

        if provider == "elevenlabs":
            if not voice_id:
                return JSONResponse(
                    {"success": False, "error": "voice_id مطلوب لـ ElevenLabs"},
                    status_code=400,
                )
            try:
                audio_bytes = await _elevenlabs_tts(
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
            except HTTPException as e:
                logger.warning(f"ElevenLabs failed: {e.detail}, falling back to Edge TTS")
                provider = "edge_tts"

        if provider == "huggingface" and reference_audio:
            tmp_ref = None
            tmp_wav = None
            try:
                content = await reference_audio.read()
                if len(content) < 6 * 1024:
                    logger.warning("Reference too short, falling back to Edge TTS")
                    provider = "edge_tts"
                else:
                    suffix = Path(reference_audio.filename or "audio.webm").suffix.lower() or ".webm"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
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
                        audio_bytes = await _huggingface_clone_and_generate(
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
                logger.warning(f"HuggingFace failed: {e}, falling back to Edge TTS")
                provider = "edge_tts"
            finally:
                if tmp_ref and tmp_ref.exists():
                    tmp_ref.unlink(missing_ok=True)
                if tmp_wav and tmp_wav.exists():
                    tmp_wav.unlink(missing_ok=True)

        if provider == "edge_tts" or provider == "auto":
            rate_percent = int((speed - 1) * 100)
            rate_str = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"

            audio_bytes = await _edge_tts_generate(
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unified voice generation failed")
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
                voice_id = await _elevenlabs_create_voice(
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
            except HTTPException as e:
                logger.warning(f"ElevenLabs failed: {e.detail}")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Voice clone failed")
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
    try:
        if len(text) > 200:
            text = text[:200]

        audio_bytes = await _edge_tts_generate(
            text=text,
            voice=voice_id if voice_id.startswith("ar-") else "ar-SA-HamedNeural",
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Voice preview failed")
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
        rate_str = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"

        audio_bytes = await _edge_tts_generate(
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Generate with cache failed")
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

        audio_bytes = await _elevenlabs_tts(
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Voice generation failed")
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

    existing = next((v for v in saved_voices if v.get("voice_id") == voice_id), None)
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
        "display_name": payload.get("display_name", payload.get("name", "صوتي")),
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

    logger.info(f"✅ Voice saved: {voice_id} → project {project_id}")

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

    target = next((v for v in saved_voices if v.get("id") == voice_record_id), None)
    if not target:
        return JSONResponse({"error": "Voice not found"}, status_code=404)

    voice_id = target.get("voice_id")
    provider = target.get("provider", "")

    if voice_id and provider == "elevenlabs":
        try:
            await _elevenlabs_delete_voice(voice_id)
        except Exception as e:
            logger.warning(f"Failed to delete from ElevenLabs: {e}")

    data["cloned_voices"] = [v for v in saved_voices if v.get("id") != voice_record_id]
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

    target = next((v for v in saved_voices if v.get("id") == voice_record_id), None)
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
    filename = f"voices_{project_id[:8]}_{int(datetime.utcnow().timestamp())}.json"

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

    logger.info(f"📥 Imported {added} voices (skipped {skipped})")

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
                    headers={"xi-api-key": settings.elevenlabs_api_key_value},
                )
                if r.status_code == 200:
                    data = r.json()
                    elevenlabs_ok = True
                    elevenlabs_tier = data.get("subscription", {}).get("tier", "unknown")
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
            "supports_cloning": elevenlabs_tier in ["starter", "creator", "pro", "scale", "business"],
            "free_tier_note": "Free tier does NOT support voice cloning",
        },
        "did_talking_head": {
            "available": settings.did_configured,
            "free_tier_minutes": 5,
        },
    }


# ============================================================
# 🎭 TALKING HEAD ENDPOINTS
# ============================================================

@router.post("/api/talking-head/create")
async def create_talking_head(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    project_id: str = Form(""),
):
    """🎭 أنشئ فيديو talking head من صورة + صوت جاهز."""
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID غير مهيأ. أضف DID_API_KEY."},
                status_code=503,
            )

        img_content = await image.read()
        aud_content = await audio.read()

        if not img_content:
            return JSONResponse(
                {"success": False, "error": "الصورة فارغة"},
                status_code=400,
            )

        if not aud_content:
            return JSONResponse(
                {"success": False, "error": "الصوت فارغ"},
                status_code=400,
            )

        _diag(f"🎭 Talking Head (image+audio):")
        _diag(f"   Image: {len(img_content) / 1024:.1f} KB")
        _diag(f"   Audio: {len(aud_content) / 1024:.1f} KB")

        talk_id = await _did_create_talk(
            image_content=img_content,
            audio_content=aud_content,
            image_filename=image.filename or "image.jpg",
        )

        # ✅ احفظ في Supabase Storage
        await create_job_async(
            talk_id,
            project_id=project_id,
            status="created",
            result_url=None,
            error=None,
            kind="talking_head",
        )

        return {
            "success": True,
            "talk_id": talk_id,
            "status": "created",
            "message": "✅ تم إنشاء الفيديو. جاري المعالجة...",
        }

    except HTTPException as e:
        return JSONResponse(
            {"success": False, "error": e.detail},
            status_code=e.status_code,
        )
    except Exception as e:
        logger.exception("Talking head creation failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/talking-head/generate")
async def generate_talking_head(
    image: UploadFile = File(...),
    text: str = Form(...),
    voice_id: str = Form("ar-SA-HamedNeural"),
    use_edge_tts: str = Form("true"),
    language: str = Form("ar"),
    project_id: str = Form(""),
):
    """🎭 توليد فيديو ناطق من صورة + نص."""
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID غير مهيأ — أضف DID_API_KEY"},
                status_code=503,
            )

        text = text.strip()
        if not text:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(text) > settings.DID_MAX_TEXT_CHARS:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"النص طويل جداً ({len(text)} حرف). "
                        f"الحد الأقصى {settings.DID_MAX_TEXT_CHARS} حرف."
                    ),
                },
                status_code=400,
            )

        img_content = await image.read()
        if not img_content:
            return JSONResponse(
                {"success": False, "error": "الصورة فارغة"},
                status_code=400,
            )

        img_size_mb = len(img_content) / 1024 / 1024
        if img_size_mb > 5:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"الصورة كبيرة جداً ({img_size_mb:.1f} MB). "
                        f"الحد 5 MB. جرّب صورة أصغر."
                    ),
                },
                status_code=400,
            )

        _diag(f"🎭 Talking Head request:")
        _diag(f"   Text: {len(text)} chars")
        _diag(f"   Image: {img_size_mb:.2f} MB ({image.filename})")
        _diag(f"   Voice: {voice_id}")

        _diag(f"🎙️ Generating audio via Edge TTS...")

        try:
            audio_bytes = await _edge_tts_generate(
                text=text,
                voice=voice_id,
            )
        except Exception as e:
            _diag_err(f"❌ Edge TTS failed: {e}", e)
            return JSONResponse(
                {
                    "success": False,
                    "error": f"فشل توليد الصوت: {str(e)}",
                },
                status_code=500,
            )

        aud_size_mb = len(audio_bytes) / 1024 / 1024
        _diag(f"✅ Audio generated: {aud_size_mb:.2f} MB")

        if aud_size_mb > 10:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"الصوت المُولَّد كبير جداً ({aud_size_mb:.1f} MB). "
                        f"استخدم نصاً أقصر."
                    ),
                },
                status_code=400,
            )

        _diag(f"🎭 Creating talking head on D-ID...")

        try:
            talk_id = await _did_create_talk(
                image_content=img_content,
                audio_content=audio_bytes,
                image_filename=image.filename or "image.jpg",
            )
        except HTTPException as e:
            return JSONResponse(
                {
                    "success": False,
                    "error": e.detail,
                },
                status_code=e.status_code,
            )

        # ✅ احفظ في Supabase Storage
        await create_job_async(
            talk_id,
            project_id=project_id,
            status="created",
            text=text,
            voice_id=voice_id,
            provider="edge_tts",
            kind="talking_head",
        )

        _diag(f"✅ Talking head started: {talk_id}")

        return {
            "success": True,
            "talk_id": talk_id,
            "status": "created",
            "message": "✅ تم إنشاء الفيديو. جاري المعالجة...",
        }

    except HTTPException:
        raise
    except Exception as e:
        _diag_err(f"❌ Talking head failed: {e}", e)
        return JSONResponse(
            {
                "success": False,
                "error": f"خطأ غير متوقع: {str(e)}",
            },
            status_code=500,
        )


@router.get("/api/talking-head/status/{talk_id}")
async def get_talking_head_status(talk_id: str):
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID غير مهيأ"},
                status_code=503,
            )

        data = await _did_get_talk_status(talk_id)

        status = data.get("status", "unknown")
        result_url = data.get("result_url")
        error = data.get("error")
        duration = data.get("duration")

        if status == "done" and result_url and not duration:
            try:
                _diag(f"⏱️ Probing duration for {talk_id}...")

                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    headers = {"Range": "bytes=0-3145728"}
                    r = await client.get(result_url, headers=headers)
                    if r.status_code in (200, 206):
                        tmp = Path(tempfile.gettempdir()) / f"probe_{talk_id}.mp4"
                        tmp.write_bytes(r.content)
                        duration = await _get_video_duration(tmp)
                        tmp.unlink(missing_ok=True)
                        _diag(f"✅ Duration extracted: {duration:.2f}s")
            except Exception as e:
                _diag_err(f"⚠️ Failed to probe duration: {e}", e)

        # ✅ احفظ التحديث في Storage
        await update_job_async(
            talk_id,
            status=status,
            result_url=result_url,
            duration=duration,
            error=error,
        )

        return {
            "success": True,
            "talk_id": talk_id,
            "status": status,
            "result_url": result_url,
            "duration": duration,
            "error": error,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get status failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/talking-head/save/{project_id}")
async def save_talking_head_to_project(
    project_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    """🎭 حفظ Talking Head في المشروع."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    source_url = payload.get("video_url") or payload.get("result_url")
    if not source_url:
        return JSONResponse({"error": "video_url مطلوب"}, status_code=400)

    _diag(f"📥 Saving talking head: {source_url[:100]}...")

    video_bytes = None
    local_video_path = None

    try:
        _diag("⬇️ Downloading video from D-ID...")
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            r = await client.get(source_url)
            if r.status_code != 200:
                raise RuntimeError(f"Download failed: HTTP {r.status_code}")
            video_bytes = r.content
            _diag(f"✅ Downloaded: {len(video_bytes) / 1024 / 1024:.2f} MB")
    except Exception as e:
        _diag_err(f"❌ Failed to download video: {e}", e)
        return JSONResponse(
            {"success": False, "error": f"فشل تنزيل الفيديو من D-ID: {e}"},
            status_code=502,
        )

    if not video_bytes or len(video_bytes) < 10000:
        return JSONResponse(
            {"success": False, "error": "الفيديو المُنزَّل فارغ أو تالف"},
            status_code=502,
        )

    unique = uuid.uuid4().hex[:12]
    local_tmp = Path(tempfile.gettempdir()) / f"talking_head_{unique}.mp4"
    local_tmp.write_bytes(video_bytes)
    local_video_path = local_tmp

    real_duration = await _get_video_duration(local_tmp)
    _diag(f"⏱️ Real duration: {real_duration:.2f}s")

    permanent_url = None
    remote_path = None

    if settings.supabase_configured:
        try:
            from application.services.production_service import (
                _upload_to_supabase, _build_public_url,
            )

            storage = SupabaseStorageAdapter()
            remote_path = f"talking_heads/{project_id}/{unique}.mp4"

            await _upload_to_supabase(
                storage=storage,
                local_path=local_tmp,
                remote_path=remote_path,
                content_type="video/mp4",
            )
            permanent_url = await _build_public_url(storage, remote_path)
            _diag(f"✅ Uploaded to Supabase: {permanent_url[:80]}...")
        except Exception as e:
            _diag_err(f"⚠️ Supabase upload failed: {e}", e)

    if not permanent_url:
        local_dest = TALKING_HEADS_DIR / f"{project_id}_{unique}.mp4"
        local_dest.write_bytes(video_bytes)
        permanent_url = f"/static/media/talking_heads/{local_dest.name}"
        remote_path = str(local_dest)
        _diag(f"⚠️ Using local fallback: {permanent_url}")

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []

    clip_id = payload.get("id") or f"clip-{uuid.uuid4().hex[:12]}"

    new_clip = {
        "id": clip_id,
        "type": "video",
        "title": payload.get("title", "Talking Head"),
        "url": permanent_url,
        "src": permanent_url,
        "path": remote_path,
        "start": payload.get("start", 0),
        "duration": real_duration,
        "source": "talking_head",
        "text": payload.get("text", ""),
        "voice_id": payload.get("voice_id"),
        "image_url": payload.get("image_url"),
        "created_at": datetime.utcnow().isoformat(),
    }

    clips.append(new_clip)
    data["clips"] = clips

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    if local_video_path and local_video_path.exists():
        local_video_path.unlink(missing_ok=True)

    _diag(f"✅ Talking head saved: {clip_id} ({real_duration:.2f}s)")

    return {
        "success": True,
        "clip": new_clip,
        "message": "✅ تم الحفظ مع الرابط الدائم والمدة الحقيقية",
    }


@router.delete("/api/talking-head/delete/{talk_id}")
async def delete_talking_head(talk_id: str):
    """احذف talking head job."""
    if settings.did_configured:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.delete(
                    f"{DID_API_BASE}/talks/{talk_id}",
                    headers={"Authorization": settings.did_api_key_value},
                )
        except Exception as e:
            logger.warning(f"Failed to delete talk: {e}")

    if talk_id in TALKING_HEAD_JOBS:
        del TALKING_HEAD_JOBS[talk_id]

    try:
        job_file = JOBS_DIR / f"{talk_id}.json"
        if job_file.exists():
            job_file.unlink()
    except Exception:
        pass

    return {"success": True, "talk_id": talk_id}


@router.get("/api/talking-head/list")
async def list_talking_head_jobs():
    return {
        "success": True,
        "count": len(TALKING_HEAD_JOBS),
        "jobs": list(TALKING_HEAD_JOBS.values()),
    }


# ============================================================
# MEDIA — VOICEOVER CRUD
# ============================================================

@router.post("/api/media/upload-voiceover")
async def upload_voiceover(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    title: str = Form(""),
    script: str = Form(""),
    script_segments: str = Form("[]"),
    source: str = Form("recording"),
    start: float = Form(0.0),
    duration: float = Form(0.0),
    processed: str = Form("false"),
    processing_options: str = Form("{}"),
):
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )
        if len(content) > VOICEOVER_MAX_SIZE:
            return JSONResponse(
                {"success": False, "error": f"حجم الملف يتجاوز {VOICEOVER_MAX_SIZE // (1024*1024)}MB"},
                status_code=413,
            )

        content_type = file.content_type or "audio/webm"
        suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            if duration <= 0:
                duration = await _get_audio_duration(tmp_path)

            uploaded = await _upload_voiceover_to_storage(
                tmp_path, project_id, content_type
            )

            try:
                segments = json.loads(script_segments) if script_segments else []
            except json.JSONDecodeError:
                segments = []

            try:
                proc_opts = json.loads(processing_options) if processing_options else {}
            except json.JSONDecodeError:
                proc_opts = {}

            return {
                "success": True,
                "url": uploaded["url"],
                "path": uploaded["path"],
                "media_id": uploaded["media_id"],
                "duration": duration,
                "title": title,
                "script": script,
                "script_segments": segments,
                "source": source,
                "start": start,
                "processed": processed.lower() == "true",
                "processing_options": proc_opts,
            }
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Voiceover upload failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/media/transcribe")
async def transcribe_voiceover(
    file: UploadFile = File(...),
    language: str = Form("ar"),
    with_timestamps: str = Form("true"),
    model_size: str = Form("base"),
):
    """استخراج النص من ملف صوتي (Whisper)."""
    tmp_path = None
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        segments: List[Dict[str, Any]] = []
        full_text = ""
        detected_lang = language

        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments_gen, info = model.transcribe(
                str(tmp_path),
                language=language if language != "auto" else None,
                beam_size=5,
                vad_filter=True,
            )
            for seg in segments_gen:
                segments.append({
                    "text": seg.text.strip(),
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                })
            full_text = " ".join(s["text"] for s in segments).strip()
            detected_lang = getattr(info, "language", language) or language

        except ImportError:
            import whisper
            model = whisper.load_model(model_size)
            result = model.transcribe(
                str(tmp_path),
                language=language if language != "auto" else None,
                verbose=False,
            )
            if with_timestamps.lower() == "true":
                for seg in result.get("segments", []):
                    segments.append({
                        "text": seg["text"].strip(),
                        "start": round(float(seg["start"]), 3),
                        "end": round(float(seg["end"]), 3),
                    })
            full_text = result.get("text", "").strip()
            detected_lang = result.get("language", language) or language

        duration = segments[-1]["end"] if segments else 0.0

        return {
            "success": True,
            "text": full_text,
            "language": detected_lang,
            "segments": segments,
            "duration": duration,
        }

    except ImportError:
        return JSONResponse(
            {
                "success": False,
                "error": "Whisper غير مثبّت. شغّل: pip install faster-whisper",
            },
            status_code=500,
        )
    except Exception as e:
        logger.exception("Transcription failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@router.post("/api/media/process-audio")
async def process_audio_endpoint(
    file: UploadFile = File(...),
    options: str = Form("{}"),
):
    """معالجة الصوت بـ ffmpeg."""
    tmp_in = None
    tmp_out = None
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        try:
            opts = json.loads(options) if options else {}
        except json.JSONDecodeError:
            opts = {}

        normalize = opts.get("normalize", True)
        denoise = opts.get("denoise", False)
        trim_silence = opts.get("trim_silence", True)
        compress = opts.get("compress", False)
        target_lufs = float(opts.get("target_lufs", settings.AUDIO_TARGET_LUFS))

        suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_in = Path(tmp.name)

        tmp_out = tmp_in.with_name(f"processed_{uuid.uuid4().hex[:8]}.webm")

        filters = []
        if denoise:
            filters.append("afftdn=nf=-25")
        if trim_silence:
            filters.append(
                "silenceremove=start_periods=1:start_duration=0.1:"
                "start_threshold=-45dB:detection=peak,"
                "areverse,"
                "silenceremove=start_periods=1:start_duration=0.1:"
                "start_threshold=-45dB:detection=peak,"
                "areverse"
            )
        if compress:
            filters.append("acompressor=threshold=-18dB:ratio=3:attack=5:release=50")
        if normalize:
            filters.append(f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11")

        cmd = ["ffmpeg", "-y", "-i", str(tmp_in), "-vn", "-c:a", "libopus", "-b:a", "128k"]
        if filters:
            cmd += ["-af", ",".join(filters)]
        cmd.append(str(tmp_out))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {stderr.decode()[-500:]}")

        if not tmp_out.exists():
            raise RuntimeError("لم يتم إنشاء الملف المعالج")

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/webm",
            filename="processed.webm",
            headers={
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )

    except FileNotFoundError:
        return JSONResponse(
            {"success": False, "error": "ffmpeg غير مثبّت"},
            status_code=500,
        )
    except Exception as e:
        logger.exception("Audio processing failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )
    finally:
        if tmp_in:
            tmp_in.unlink(missing_ok=True)


# ============================================================
# VOICEOVER CRUD
# ============================================================

@router.get("/api/media/voiceover/{project_id}")
async def list_voiceovers(
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
    clips = data.get("clips", []) or []

    voiceovers = [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "url": c.get("url"),
            "start": c.get("start", 0),
            "duration": c.get("duration", 0),
            "script": c.get("script", ""),
            "script_segments": c.get("script_segments", []),
            "source": c.get("source", "unknown"),
            "voice_id": c.get("voice_id"),
            "processed": c.get("processed", False),
        }
        for c in clips
        if isinstance(c, dict) and c.get("type") == "audio"
    ]

    return {"success": True, "count": len(voiceovers), "voiceovers": voiceovers}


@router.delete("/api/media/voiceover/{project_id}/{clip_id}")
async def delete_voiceover(
    project_id: str,
    clip_id: str,
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
    clips = data.get("clips", []) or []

    target = next(
        (c for c in clips if isinstance(c, dict) and c.get("id") == clip_id),
        None,
    )
    if not target:
        return JSONResponse({"error": "Clip not found"}, status_code=404)

    path = target.get("path") or target.get("mediaId")
    if path and settings.supabase_configured:
        try:
            storage = SupabaseStorageAdapter()
            if hasattr(storage, "delete_file"):
                await storage.delete_file(path)
        except Exception as e:
            logger.warning(f"Failed to delete storage: {e}")

    local_path = target.get("path")
    if local_path and isinstance(local_path, str) and local_path.startswith("/"):
        try:
            p = Path(local_path)
            if p.exists() and p.is_file():
                p.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete local: {e}")

    data["clips"] = [c for c in clips if c.get("id") != clip_id]
    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "deleted_id": clip_id}


@router.patch("/api/media/voiceover/{project_id}/{clip_id}")
async def update_voiceover(
    project_id: str,
    clip_id: str,
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
    clips = data.get("clips", []) or []

    target = next(
        (c for c in clips if isinstance(c, dict) and c.get("id") == clip_id),
        None,
    )
    if not target:
        return JSONResponse({"error": "Clip not found"}, status_code=404)

    for field in ("title", "script", "script_segments", "start", "duration", "tts", "voice_id"):
        if field in payload:
            target[field] = payload[field]

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "clip": target}


@router.post("/api/media/voiceover/{project_id}")
async def add_voiceover_clip(
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

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []

    clip_id = payload.get("id") or f"clip-{uuid.uuid4().hex[:12]}"
    payload["id"] = clip_id
    payload.setdefault("type", "audio")

    clips.append(payload)
    data["clips"] = clips
    if hasattr(project, "data"):
        project.data = data    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "clip": payload}


# ============================================================
# MEDIA UPLOAD (عام)
# ============================================================

@router.post("/api/v1/storage/upload-media")
async def upload_media(
    file: UploadFile = File(...),
    project_id: str = Form(...),
):
    try:
        from application.services.production_service import (
            _upload_to_supabase, _build_public_url,
        )

        storage = SupabaseStorageAdapter()
        content = await file.read()

        if not content:
            return JSONResponse({"error": "الملف فارغ"}, status_code=400)

        suffix = Path(file.filename or "file").suffix.lower() or ".bin"
        unique = f"{uuid.uuid4().hex}{suffix}"
        remote_path = f"media/{project_id}/{unique}"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            content_type = file.content_type or "application/octet-stream"
            await _upload_to_supabase(
                storage=storage,
                local_path=tmp_path,
                remote_path=remote_path,
                content_type=content_type,
            )
            url = await _build_public_url(storage, remote_path)
            if not url:
                raise RuntimeError("فشل بناء الرابط")

            return {"url": url, "path": remote_path}
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Failed to upload media")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# ALIGN SCRIPT (Backward Compatible)
# ============================================================

@router.post("/api/media/align-script")
async def align_script_with_audio(
    file: UploadFile = File(...),
    script: str = Form(...),
    language: str = Form("ar"),
    voice_id: str = Form(""),
    project_id: str = Form(""),
):
    """🎙️ Voice Cloning — توافق مع الكود القديم."""
    if voice_id:
        return await generate_with_cloned_voice(
            voice_id=voice_id,
            script=script,
            project_id=project_id,
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=1.0,
            model_id=settings.ELEVENLABS_MODEL_ID,
        )

    return await generate_with_cache(
        voice_id="ar-SA-HamedNeural",
        script=script,
        project_id=project_id,
        use_cache="true",
        speed=1.0,
    )


# ============================================================
# ASSETS
# ============================================================

@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_asset_repository import SQLAssetRepository
    repo = SQLAssetRepository(session)
    assets = await repo.list_all(limit=50)
    total = await repo.count()

    supabase_files = []
    try:
        if settings.supabase_configured:
            storage = SupabaseStorageAdapter()
            supabase_files = await storage.list_files()
    except Exception as e:
        logger.warning(f"Failed to list Supabase files: {e}")

    return templates.TemplateResponse(request, "assets/library.html", {
        "assets": assets,
        "total": total,
        "supabase_files": supabase_files,
        "active_page": "assets",
        "supabase": get_supabase_config(),
    })


# ============================================================
# TEMPLATES
# ============================================================

@router.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    builtin_templates = [
        {
            "id": "short_video",
            "name": "فيديو قصير",
            "description": "قالب مناسب لفيديوهات قصيرة",
            "gradient": "from-blue-900 to-blue-700",
            "ratio": "16:9",
            "tags": ["تعليم", "عروض", "تسويق"],
            "quality": 4,
        },
        {
            "id": "reel",
            "name": "ريلز / شورتس",
            "description": "قالب عمودي للمنصات القصيرة",
            "gradient": "from-pink-900 to-purple-800",
            "ratio": "9:16",
            "tags": ["ريلز", "شورتس", "سوشيال"],
            "quality": 4,
        },
        {
            "id": "educational",
            "name": "تعليمي",
            "description": "قالب طويل للمحتوى التعليمي",
            "gradient": "from-emerald-900 to-teal-800",
            "ratio": "16:9",
            "tags": ["تعليم", "شرح", "درس"],
            "quality": 5,
        },
        {
            "id": "product",
            "name": "مراجعة منتج",
            "description": "قالب للمراجعات والعروض",
            "gradient": "from-amber-900 to-orange-800",
            "ratio": "16:9",
            "tags": ["مراجعة", "تقنية", "منتج"],
            "quality": 4,
        },
        {
            "id": "square",
            "name": "مربع",
            "description": "قالب مربع لـ Instagram/LinkedIn",
            "gradient": "from-slate-700 to-slate-600",
            "ratio": "1:1",
            "tags": ["إنستقرام", "لينكدإن"],
            "quality": 3,
        },
    ]
    return templates.TemplateResponse(request, "templates_page.html", {
        "builtin_templates": builtin_templates,
        "custom_templates": [],
        "active_page": "templates",
        "supabase": get_supabase_config(),
    })


# ============================================================
# VOICES
# ============================================================

@router.get("/voices", response_class=HTMLResponse)
async def voices_page(request: Request):
    voice_engines = [
        {
            "id": "edge_tts",
            "name": "Edge TTS (مجاني)",
            "provider": "Microsoft",
            "description": "أصوات احترافية جاهزة — بدون استنساخ",
            "languages": ["ar", "en", "fr", "de", "es", "+36"],
            "quality": 4,
            "available": settings.EDGE_TTS_ENABLED,
            "active": True,
        },
        {
            "id": "huggingface",
            "name": "HuggingFace XTTS",
            "provider": "HuggingFace Spaces",
            "description": "استنساخ صوتك — مجاني تماماً",
            "languages": ["ar", "en", "fr", "de", "es"],
            "quality": 4,
            "available": True,
            "active": False,
        },
        {
            "id": "elevenlabs",
            "name": "ElevenLabs",
            "provider": "ElevenLabs API",
            "description": "الأفضل جودة — مدفوع ($5/شهر)",
            "languages": ["ar", "en", "fr", "de", "es", "+10"],
            "quality": 5,
            "available": settings.elevenlabs_configured,
            "active": False,
        },
        {
            "id": "did_talking_head",
            "name": "D-ID Talking Head",
            "provider": "D-ID API",
            "description": "تحريك صورة الشخص",
            "languages": ["كل اللغات"],
            "quality": 5,
            "available": settings.did_configured,
            "active": settings.did_configured,
        },
    ]
    return templates.TemplateResponse(request, "voices.html", {
        "voice_engines": voice_engines,
        "active_voice": "Edge TTS (مجاني)",
        "active_page": "voices",
        "supabase": get_supabase_config(),
    })


# ============================================================
# RENDER QUEUE
# ============================================================

@router.get("/render-queue", response_class=HTMLResponse)
async def render_queue_page(request: Request, session: AsyncSession = Depends(get_db)):
    repo = SQLRenderJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return templates.TemplateResponse(request, "render/queue.html", {
        "jobs": jobs,
        "active_page": "render_queue",
        "supabase": get_supabase_config(),
    })


# ============================================================
# PUBLISHING QUEUE
# ============================================================

@router.get("/publishing-queue", response_class=HTMLResponse)
async def publishing_queue_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import SQLPublishingJobRepository
    repo = SQLPublishingJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return templates.TemplateResponse(request, "publishing/queue.html", {
        "jobs": jobs,
        "active_page": "publishing_queue",
        "supabase": get_supabase_config(),
    })


# ============================================================
# PLATFORMS
# ============================================================

@router.get("/platforms", response_class=HTMLResponse)
async def platforms_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import SQLAccountRepository
    repo = SQLAccountRepository(session)
    accounts = await repo.list_all()
    return templates.TemplateResponse(request, "publishing/platforms.html", {
        "accounts": accounts,
        "active_page": "platforms",
        "supabase": get_supabase_config(),
    })


# ============================================================
# SCHEDULES
# ============================================================

@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import (
        SQLPublishingJobRepository, SQLAccountRepository,
    )

    pub_repo = SQLPublishingJobRepository(session)
    acc_repo = SQLAccountRepository(session)

    all_jobs = await pub_repo.list_recent(limit=100)
    accounts = await acc_repo.list_all()

    scheduled_jobs = [j for j in all_jobs if j.status.value == "scheduled"]
    recent_published = [j for j in all_jobs if j.status.value in ("completed", "failed")][:20]

    project_repo = SQLProjectRepository(session)
    rendered_projects = await project_repo.list_all(limit=50, status="rendered")

    for job in scheduled_jobs + recent_published:
        job.project_title = None
        job.platform_name = getattr(job, "platform_name", "—")

    stats = {
        "scheduled": len(scheduled_jobs),
        "published_today": sum(
            1 for j in all_jobs
            if j.status.value == "completed"
            and j.created_at.date() == datetime.utcnow().date()
        ),
        "pending": sum(1 for j in all_jobs if j.status.value == "pending"),
        "failed": sum(1 for j in all_jobs if j.status.value == "failed"),
    }

    return templates.TemplateResponse(request, "schedules.html", {
        "stats": stats,
        "scheduled_jobs": scheduled_jobs,
        "recent_published": recent_published,
        "rendered_projects": rendered_projects,
        "accounts": accounts,
        "active_page": "schedules",
        "supabase": get_supabase_config(),
    })


# ============================================================
# ANALYTICS
# ============================================================

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_asset_repository import SQLAssetRepository
    from infrastructure.repositories.sql_publishing_repository import SQLPublishingJobRepository

    project_repo = SQLProjectRepository(session)
    job_repo = SQLRenderJobRepository(session)
    asset_repo = SQLAssetRepository(session)
    pub_repo = SQLPublishingJobRepository(session)

    total_projects = await project_repo.count()
    total_assets = await asset_repo.count()
    all_jobs = await job_repo.list_recent(limit=200)
    all_pub = await pub_repo.list_recent(limit=200)

    completed = sum(1 for j in all_jobs if j.status.value == "completed")
    failed = sum(1 for j in all_jobs if j.status.value == "failed")
    total_renders = len(all_jobs)
    success_rate = round(completed / total_renders * 100) if total_renders else 0

    kpis = [
        {"label": "إجمالي المشاريع", "value": total_projects, "trend": 0, "sub": "مشروع"},
        {"label": "عمليات الرندر", "value": total_renders, "trend": 0, "sub": "مهمة"},
        {"label": "نسبة النجاح", "value": f"{success_rate}%", "trend": 0, "sub": "رندر مكتمل"},
        {"label": "إجمالي الأصول", "value": total_assets, "trend": 0, "sub": "ملف"},
    ]

    status_colors = {
        "draft": "bg-slate-500", "in_production": "bg-amber-500",
        "rendered": "bg-green-500", "published": "bg-blue-500", "failed": "bg-red-500",
    }
    status_labels = {
        "draft": "مسودة", "in_production": "إنتاج",
        "rendered": "تم الرندر", "published": "منشور", "failed": "فشل",
    }
    projects_by_status = []
    for s in ["draft", "in_production", "rendered", "published", "failed"]:
        count = await project_repo.count(status=s)
        if count > 0:
            projects_by_status.append({
                "label": status_labels.get(s, s),
                "count": count,
                "color": status_colors.get(s, "bg-slate-500"),
            })

    render_stats = [
        {"label": "مكتمل", "value": completed, "color": "text-green-400"},
        {"label": "فاشل", "value": failed, "color": "text-red-400"},
        {"label": "جارٍ", "value": sum(1 for j in all_jobs if j.status.value == "processing"), "color": "text-amber-400"},
        {"label": "في الانتظار", "value": sum(1 for j in all_jobs if j.status.value in ("pending", "queued")), "color": "text-slate-300"},
    ]

    today = datetime.utcnow().date()
    publish_activity = []
    for delta in range(6, -1, -1):
        day = today - timedelta(days=delta)
        count = sum(1 for j in all_pub if j.created_at.date() == day)
        short = ["أح", "إث", "ثل", "أر", "خم", "جم", "سب"][day.weekday()]
        publish_activity.append({"label": short, "count": count})

    asset_type_meta = {
        "image":  ("صور",    "bg-blue-500",   "bg-blue-400"),
        "video":  ("فيديو",  "bg-purple-500", "bg-purple-400"),
        "audio":  ("صوت",    "bg-green-500",  "bg-green-400"),
        "font":   ("خطوط",   "bg-amber-500",  "bg-amber-400"),
        "logo":   ("شعارات", "bg-pink-500",   "bg-pink-400"),
        "other":  ("أخرى",   "bg-slate-500",  "bg-slate-400"),
    }
    all_assets = await asset_repo.list_all(limit=1000)
    type_counts: dict = {}
    for a in all_assets:
        t = a.type.value
        type_counts[t] = type_counts.get(t, 0) + 1
    asset_types = []
    for t, count in type_counts.items():
        meta = asset_type_meta.get(t, asset_type_meta["other"])
        asset_types.append({
            "label": meta[0], "count": count,
            "bar_color": meta[1], "dot_color": meta[2],
        })

    return templates.TemplateResponse(request, "analytics.html", {
        "kpis": kpis,
        "total_projects": total_projects,
        "total_assets": total_assets,
        "projects_by_status": projects_by_status,
        "render_stats": render_stats,
        "publish_activity": publish_activity,
        "asset_types": asset_types,
        "avg_render_time": None,
        "active_page": "analytics",
        "supabase": get_supabase_config(),
    })


# ============================================================
# LOGS
# ============================================================

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    now = datetime.utcnow()
    log_entries = [
        {"level": "INFO", "source": "main", "timestamp": now - timedelta(seconds=5), "message": "Platform started"},
        {"level": "INFO", "source": "system", "timestamp": now - timedelta(seconds=4), "message": "Database tables ready"},
        {"level": "INFO", "source": "plugins", "timestamp": now - timedelta(seconds=3), "message": "Plugins loaded"},
        {"level": "INFO", "source": "main", "timestamp": now - timedelta(seconds=1), "message": "Platform ready"},
    ]

    if settings.supabase_configured:
        log_entries.append({
            "level": "INFO", "source": "supabase", "timestamp": now,
            "message": f"Supabase configured: {settings.SUPABASE_URL}"
        })

    edge_ok = settings.EDGE_TTS_ENABLED
    log_entries.append({
        "level": "INFO" if edge_ok else "WARNING",
        "source": "voiceover", "timestamp": now,
        "message": f"Edge TTS: {'✅ متاح' if edge_ok else '❌ معطّل'}"
    })

    hf_ok = True
    log_entries.append({
        "level": "INFO" if hf_ok else "WARNING",
        "source": "voiceover", "timestamp": now,
        "message": f"HuggingFace XTTS: {'✅ متاح' if hf_ok else '❌ معطّل'}"
    })

    elevenlabs_ok = settings.elevenlabs_configured
    log_entries.append({
        "level": "INFO" if elevenlabs_ok else "WARNING",
        "source": "voiceover", "timestamp": now,
        "message": (
            f"ElevenLabs: {'✅ متاح' if elevenlabs_ok else '⚠️ غير مهيأ (سيعمل Edge TTS بدلاً منه)'}"
        )
    })

    did_ok = settings.did_configured
    log_entries.append({
        "level": "INFO" if did_ok else "WARNING",
        "source": "talking_head", "timestamp": now,
        "message": (
            f"D-ID Talking Head: {'✅ متاح' if did_ok else '❌ غير مهيأ (DID_API_KEY مفقود)'}"
        )
    })

    whisper_status = "غير مثبّت"
    try:
        import faster_whisper
        whisper_status = "faster-whisper ✅"
    except ImportError:
        try:
            import whisper
            whisper_status = "openai-whisper ✅"
        except ImportError:
            whisper_status = "❌ غير مثبّت"

    log_entries.append({
        "level": "INFO" if "✅" in whisper_status else "WARNING",
        "source": "voiceover", "timestamp": now,
        "message": f"Whisper: {whisper_status}"
    })

    import shutil as _shutil
    ffmpeg_ok = _shutil.which("ffmpeg") is not None
    log_entries.append({
        "level": "INFO" if ffmpeg_ok else "WARNING",
        "source": "voiceover", "timestamp": now,
        "message": f"FFmpeg: {'✅ متاح' if ffmpeg_ok else '❌ غير مثبّت'}"
    })

    cache_files = list(CACHE_DIR.glob("*.mp3"))
    cache_size = sum(f.stat().st_size for f in cache_files) / 1024 / 1024
    log_entries.append({
        "level": "INFO", "source": "voiceover", "timestamp": now,
        "message": f"Voice Cache: {len(cache_files)} files ({cache_size:.1f} MB)"
    })

    jobs_count = len(list(JOBS_DIR.glob("*.json"))) if JOBS_DIR.exists() else 0
    log_entries.append({
        "level": "INFO", "source": "property_video", "timestamp": now,
        "message": f"Local Jobs: {jobs_count} files"
    })

    log_entries.append({
        "level": "INFO", "source": "property_video", "timestamp": now,
        "message": f"Supabase Jobs Prefix: {JOBS_STORAGE_PREFIX}/ (bucket: {settings.SUPABASE_BUCKET})"
    })

    return templates.TemplateResponse(request, "logs.html", {
        "log_entries": log_entries,
        "active_page": "logs",
        "supabase": get_supabase_config(),
    })


# ============================================================
# HEALTH
# ============================================================

@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request, session: AsyncSession = Depends(get_db)):
    import platform
    import sys
    import shutil

    db_ok = True
    db_detail = "متصل"
    try:
        await session.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        db_ok = False
        db_detail = str(e)[:60]

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    media_ok = settings.MEDIA_DIR.exists()
    supabase_ok = settings.supabase_configured
    elevenlabs_ok = settings.elevenlabs_configured
    did_ok = settings.did_configured
    edge_ok = settings.EDGE_TTS_ENABLED

    whisper_ok = False
    whisper_detail = "غير مثبّت"
    try:
        import faster_whisper
        whisper_ok = True
        whisper_detail = "faster-whisper ✅"
    except ImportError:
        try:
            import whisper
            whisper_ok = True
            whisper_detail = "openai-whisper ✅"
        except ImportError:
            whisper_detail = "غير مثبّت"

    overall = "healthy" if (db_ok and media_ok and supabase_ok) else "degraded"

    components = [
        {
            "name": "قاعدة البيانات",
            "status": "ok" if db_ok else "error",
            "detail": db_detail,
        },
        {
            "name": "تخزين الملفات",
            "status": "ok" if media_ok else "error",
            "detail": str(settings.MEDIA_DIR) if media_ok else "المجلد غير موجود",
        },
        {
            "name": "Supabase Storage",
            "status": "ok" if supabase_ok else "error",
            "detail": "متصل" if supabase_ok else "غير مهيأ",
        },
        {
            "name": "Edge TTS (مجاني)",
            "status": "ok" if edge_ok else "degraded",
            "detail": "متاح ✅" if edge_ok else "معطّل",
        },
        {
            "name": "HuggingFace XTTS (مجاني)",
            "status": "ok",
            "detail": "متاح ✅ (استنساخ صوتك)",
        },
        {
            "name": "ElevenLabs (مدفوع)",
            "status": "ok" if elevenlabs_ok else "degraded",
            "detail": "متاح ✅" if elevenlabs_ok else "غير مهيأ (سيستخدم Edge TTS)",
        },
        {
            "name": "D-ID Talking Head",
            "status": "ok" if did_ok else "degraded",
            "detail": "متاح ✅" if did_ok else "غير مهيأ — أضف DID_API_KEY",
        },
        {
            "name": "FFmpeg",
            "status": "ok" if ffmpeg_ok else "degraded",
            "detail": "متاح" if ffmpeg_ok else "غير مثبت",
        },
        {
            "name": "Whisper (STT)",
            "status": "ok" if whisper_ok else "degraded",
            "detail": whisper_detail,
        },
        {
            "name": "Job Persistence (Supabase)",
            "status": "ok" if supabase_ok else "degraded",
            "detail": f"Storage: {JOBS_STORAGE_PREFIX}/",
        },
    ]

    system_info = [
        {"label": "Python", "value": sys.version.split()[0]},
        {"label": "Platform", "value": platform.system() + " " + platform.release()},
        {"label": "APP_NAME", "value": settings.APP_NAME},
        {"label": "APP_VERSION", "value": settings.APP_VERSION},
        {"label": "Supabase", "value": "✅ مهيأ" if supabase_ok else "❌ غير مهيأ"},
        {"label": "Edge TTS", "value": "✅ متاح" if edge_ok else "❌ معطّل"},
        {"label": "HuggingFace", "value": "✅ متاح"},
        {"label": "ElevenLabs", "value": "✅ متاح" if elevenlabs_ok else "❌ غير مهيأ"},
        {"label": "D-ID", "value": "✅ متاح" if did_ok else "❌ غير مهيأ"},
        {"label": "Whisper", "value": whisper_detail},
        {"label": "FFmpeg", "value": "✅ متاح" if ffmpeg_ok else "❌ غير مثبّت"},
        {"label": "Jobs Storage", "value": JOBS_STORAGE_PREFIX},
    ]

    return templates.TemplateResponse(request, "health.html", {
        "overall_status": overall,
        "last_check": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "components": components,
        "plugins": {},
        "system_info": system_info,
        "active_page": "health",
        "supabase": get_supabase_config(),
    })


# ============================================================
# MODELS
# ============================================================

@router.get("/models", response_class=HTMLResponse)
async def models_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_hf_model_repository import SQLHFModelRepository
    repo = SQLHFModelRepository(session)
    all_models = await repo.list_all()
    return templates.TemplateResponse(request, "models.html", {
        "models": [m.to_dict() for m in all_models],
        "active_page": "models",
        "supabase": get_supabase_config(),
    })


# ============================================================
# SETTINGS
# ============================================================

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {
        "settings": {
            "app_name": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "debug": settings.DEBUG,
            "media_dir": str(settings.MEDIA_DIR),
            "storage_type": settings.STORAGE_TYPE,
            "supabase_configured": settings.supabase_configured,
            "elevenlabs_configured": settings.elevenlabs_configured,
            "did_configured": settings.did_configured,
            "edge_tts_enabled": settings.EDGE_TTS_ENABLED,
        },
        "active_page": "settings",
        "supabase": get_supabase_config(),
    })


# ============================================================
# SUPABASE CONFIG
# ============================================================

@router.get("/api/supabase/config")
async def get_supabase_config_api():
    return {
        "url": settings.SUPABASE_URL,
        "public_key": settings.supabase_public_key_value,
        "bucket": settings.SUPABASE_BUCKET,
        "configured": settings.supabase_configured,
        "storage_type": settings.STORAGE_TYPE,
    }


@router.get("/api/supabase/status")
async def get_supabase_status():
    try:
        if not settings.supabase_configured:
            return {"status": "not_configured"}
        storage = SupabaseStorageAdapter()
        await storage.list_files(prefix="", limit=1)
        return {
            "status": "connected",
            "url": settings.SUPABASE_URL,
            "bucket": settings.SUPABASE_BUCKET,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================
# DEBUG ENDPOINTS
# ============================================================

@router.get("/api/debug/project/{project_id}")
async def debug_project(project_id: str, session: AsyncSession = Depends(get_db)):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []
    saved_voices = data.get("cloned_voices", []) or []

    return {
        "project_id": project_id,
        "title": project.title,
        "data_keys": list(data.keys()),
        "clips_count": len(clips),
        "saved_voices_count": len(saved_voices),
        "saved_voices": saved_voices,
    }


@router.get("/api/debug/talking-head/jobs")
async def debug_talking_head_jobs():
    return {
        "success": True,
        "count": len(TALKING_HEAD_JOBS),
        "jobs": list(TALKING_HEAD_JOBS.values()),
        "local_files": len(list(JOBS_DIR.glob("*.json"))) if JOBS_DIR.exists() else 0,
        "storage_prefix": JOBS_STORAGE_PREFIX,
    }


@router.get("/api/debug/jobs/list")
async def debug_jobs_list():
    """اعرض كل الـ jobs المحفوظة محلياً."""
    jobs = []
    if JOBS_DIR.exists():
        for f in JOBS_DIR.glob("*.json"):
            try:
                jobs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return {
        "success": True,
        "count": len(jobs),
        "jobs": jobs,
        "storage_prefix": JOBS_STORAGE_PREFIX,
    }


@router.get("/api/debug/voiceovers/{project_id}")
async def debug_voiceovers(project_id: str, session: AsyncSession = Depends(get_db)):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []
    saved_voices = data.get("cloned_voices", []) or []

    audio_clips = [c for c in clips if isinstance(c, dict) and c.get("type") == "audio"]
    video_clips = [c for c in clips if isinstance(c, dict) and c.get("type") == "video"]

    cache_files = list(CACHE_DIR.glob("*.mp3"))
    cache_size_mb = sum(f.stat().st_size for f in cache_files) / 1024 / 1024

    return {
        "project_id": project_id,
        "audio_clips_count": len(audio_clips),
        "video_clips_count": len(video_clips),
        "saved_voices_count": len(saved_voices),
        "saved_voices": saved_voices,
        "edge_tts_available": settings.EDGE_TTS_ENABLED,
        "huggingface_available": True,
        "elevenlabs_available": settings.elevenlabs_configured,
        "did_available": settings.did_configured,
        "cache_stats": {
            "files": len(cache_files),
            "size_mb": round(cache_size_mb, 2),
        },
    }


# ============================================================
# 🏠 PROPERTY VIDEO — مولّد فيديو العقارات
# ============================================================

class PropertyVideoRequest(BaseModel):
    """نموذج طلب توليد فيديو عقاري."""
    project_id: str
    title: str = ""
    property_type: str = "apartment"
    price: Optional[float] = None
    currency: str = "SAR"
    city: str = ""
    district: str = ""
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    features: List[str] = []
    whatsapp: str = ""
    images: List[Dict[str, Any]] = []
    duration_per_image: float = 4.5
    style: str = "modern"

    # ✅ خيارات اختيارية
    voiceover_enabled: bool = True
    voiceover_voice: str = "ar-SA-HamedNeural"

    show_price: bool = True
    show_location: bool = True
    show_area: bool = True
    show_contact: bool = True


# ─────────────────────────────────────────────────────────
# رفع صور العقار
# ─────────────────────────────────────────────────────────

@router.post("/api/property/upload-image")
async def upload_property_image(
    file: UploadFile = File(...),
    project_id: str = Form(...),
):
    """يرفع صورة عقار ويُرجع رابطها الدائم + المسار."""
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        if len(content) > 10 * 1024 * 1024:
            return JSONResponse(
                {"success": False, "error": "حجم الصورة > 10MB"},
                status_code=413,
            )

        suffix = Path(file.filename or "image.jpg").suffix.lower() or ".jpg"
        unique = f"{uuid.uuid4().hex}{suffix}"
        remote_path = f"property_assets/{project_id}/{unique}"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            if settings.supabase_configured:
                try:
                    from application.services.production_service import (
                        _upload_to_supabase, _build_public_url,
                    )
                    storage = SupabaseStorageAdapter()

                    await _upload_to_supabase(
                        storage=storage,
                        local_path=tmp_path,
                        remote_path=remote_path,
                        content_type=file.content_type or "image/jpeg",
                    )
                    url = await _build_public_url(storage, remote_path)

                    if url:
                        return {
                            "success": True,
                            "url": url,
                            "path": remote_path,
                            "size": len(content),
                        }
                except Exception as e:
                    logger.warning(f"Supabase image upload failed: {e}")

            local_dest = PROPERTY_ASSETS_DIR / f"{project_id}_{unique}"
            local_dest.write_bytes(content)

            return {
                "success": True,
                "url": f"/static/media/property_assets/{local_dest.name}",
                "path": str(local_dest),
                "size": len(content),
                "local": True,
            }

        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Property image upload failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ─────────────────────────────────────────────────────────
# بدء التوليد
# ─────────────────────────────────────────────────────────

@router.post("/api/property/generate")
async def generate_property_video(
    payload: PropertyVideoRequest,
    session: AsyncSession = Depends(get_db),
):
    """
    🏠 يبدأ توليد فيديو عقاري في الخلفية.

    ✅ يستخدم create_job_async (يحفظ في Supabase Storage)
    ✅ يستخدم asyncio.create_task (أكثر موثوقية)
    """
    try:
        project_uuid = uuid.UUID(payload.project_id)
    except ValueError:
        return JSONResponse(
            {"success": False, "error": "Invalid project_id"},
            status_code=400,
        )

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse(
            {"success": False, "error": "Project not found"},
            status_code=404,
        )

    if not payload.images:
        return JSONResponse(
            {"success": False, "error": "أضف صورة واحدة على الأقل"},
            status_code=400,
        )

    job_id = f"prop_{uuid.uuid4().hex[:12]}"

    # ✅ احفظ في Supabase Storage فوراً
    await create_job_async(
        job_id,
        project_id=payload.project_id,
        status="queued",
        progress=0.0,
        stage="queued",
        video_url=None,
        path=None,
        duration=0.0,
        error=None,
        kind="property_video",
    )

    # ✅ ابدأ المهمة في الخلفية
    asyncio.create_task(_run_property_video_job(job_id, payload.model_dump()))

    _diag(f"🏠 Property video queued: {job_id}")
    _diag(f"   voiceover_enabled: {payload.voiceover_enabled}")
    _diag(f"   show_price: {payload.show_price}")
    _diag(f"   show_location: {payload.show_location}")
    _diag(f"   show_area: {payload.show_area}")
    _diag(f"   show_contact: {payload.show_contact}")

    return {
        "success": True,
        "job_id": job_id,
        "status": "queued",
        "message": "✅ جاري التوليد في الخلفية...",
    }


# ─────────────────────────────────────────────────────────
# حالة التوليد
# ─────────────────────────────────────────────────────────

@router.get("/api/property/status/{job_id}")
async def get_property_video_status(job_id: str):
    """
    يرجع حالة job توليد العقار.
    ✅ يقرأ من الذاكرة أو Supabase Storage.
    ✅ يكشف jobs الميتة (restart) ويعلّمها failed.
    """
    job = await get_job_async(job_id)
    if not job:
        return JSONResponse(
            {"success": False, "error": "Job not found"},
            status_code=404,
        )

    # ✅ إذا الـ job في حالة running/queued لكن قديم جداً (>5 دقائق)، اعتبره فشل
    if job.get("status") in ("running", "queued"):
        updated = job.get("_updated_at") or job.get("created_at")
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                age_seconds = (datetime.utcnow() - updated_dt.replace(tzinfo=None)).total_seconds()
                if age_seconds > 300:  # 5 دقائق
                    _diag(f"⚠️ Job {job_id} قديم ({age_seconds:.0f}s) — mark as failed")
                    await update_job_async(
                        job_id,
                        status="failed",
                        error="انتهت المهمة (restart الخادم قبل الإكمال)",
                    )
                    job = await get_job_async(job_id)
            except Exception:
                pass

    return {
        "success": True,
        **job,
    }


# ─────────────────────────────────────────────────────────
# حفظ الـ clip في المشروع
# ─────────────────────────────────────────────────────────

@router.post("/api/property/save/{project_id}")
async def save_property_video_to_project(
    project_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    """يحفظ الفيديو المولَّد في project.data["clips"]."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    video_url = payload.get("video_url")
    if not video_url:
        return JSONResponse({"error": "video_url مطلوب"}, status_code=400)

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []

    clip_id = payload.get("id") or f"clip-{uuid.uuid4().hex[:12]}"

    new_clip = {
        "id": clip_id,
        "type": "video",
        "title": payload.get("title", "فيديو عقاري"),
        "url": video_url,
        "src": video_url,
        "path": payload.get("path"),
        "start": payload.get("start", 0),
        "duration": payload.get("duration", 0),
        "source": "property_video",
        "property_meta": payload.get("property_meta", {}),
        "created_at": datetime.utcnow().isoformat(),
    }

    clips.append(new_clip)
    data["clips"] = clips

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {
        "success": True,
        "clip": new_clip,
        "message": "✅ تم إضافة الفيديو العقاري للمشروع",
    }


# ─────────────────────────────────────────────────────────
# التنفيذ في الخلفية
# ─────────────────────────────────────────────────────────

async def _run_property_video_job(job_id: str, payload: Dict[str, Any]) -> None:
    """
    ينفّذ توليد الفيديو العقاري كاملاً في الخلفية.

    ✅ يستخدم update_job_async (يحفظ في Supabase Storage)
    ✅ يدعم: بدون صوت، بدون نصوص، أو الاثنين
    """
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"prop_{job_id}_"))

        try:
            images = payload.get("images", [])
            duration_per_image = float(payload.get("duration_per_image", 4.5))
            voice = payload.get("voiceover_voice", "ar-SA-HamedNeural")

            voiceover_enabled = payload.get("voiceover_enabled", True)

            overlay_enabled = any([
                payload.get("show_price", True),
                payload.get("show_location", True),
                payload.get("show_area", True),
                payload.get("show_contact", True),
            ])

            _diag(f"🏠 Property job {job_id}:")
            _diag(f"   voiceover_enabled = {voiceover_enabled}")
            _diag(f"   overlay_enabled   = {overlay_enabled}")
            _diag(f"   images            = {len(images)}")

            # ═══ 1. motion clips ═══
            await update_job_async(job_id, status="running", stage="motion", progress=0.05)

            motion_clips: List[Path] = []

            for idx, img in enumerate(images):
                img_path_str = img.get("path") or img.get("local_path")
                motion = img.get("motion", "auto")

                img_path: Optional[Path] = None

                if img_path_str and not str(img_path_str).startswith("http"):
                    p = Path(str(img_path_str))
                    if p.exists():
                        img_path = p

                if img_path is None:
                    img_url = img.get("url", "")
                    if img_url.startswith("http"):
                        try:
                            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
                                r = await c.get(img_url)
                                if r.status_code == 200:
                                    suffix = Path(img_url.split("?")[0]).suffix or ".jpg"
                                    dl_path = tmp_dir / f"img_{idx}{suffix}"
                                    dl_path.write_bytes(r.content)
                                    img_path = dl_path
                        except Exception as e:
                            _diag_err(f"⚠️ Failed to download image {idx}: {e}", e)

                if img_path is None or not img_path.exists():
                    _diag(f"⚠️ Skipping missing image {idx}")
                    continue

                clip_path = tmp_dir / f"motion_{idx:03d}.mp4"

                await _render_motion_clip(
                    image_path=img_path,
                    output_path=clip_path,
                    duration=duration_per_image,
                    motion=motion,
                )

                motion_clips.append(clip_path)

                if len(images) > 0:
                    await update_job_async(
                        job_id,
                        progress=0.05 + (idx + 1) / len(images) * 0.4,
                    )

            if not motion_clips:
                raise RuntimeError("لم يتم توليد أي مقطع — تحقق من الصور")

            # ═══ 2. concat ═══
            await update_job_async(job_id, stage="concat", progress=0.5)

            stitched = tmp_dir / "stitched.mp4"
            await _concat_video_clips(motion_clips, stitched, tmp_dir)

            # ═══ 3. voiceover (اختياري) ═══
            voiceover_path: Optional[Path] = None

            if voiceover_enabled:
                await update_job_async(job_id, stage="voiceover", progress=0.6)

                voiceover_text = _build_property_script(payload)

                try:
                    audio_bytes = await _edge_tts_generate(
                        text=voiceover_text,
                        voice=voice,
                    )
                    voiceover_path = tmp_dir / "voiceover.mp3"
                    voiceover_path.write_bytes(audio_bytes)
                    _diag(f"🎙️ Voiceover generated ({len(audio_bytes)} bytes)")
                except Exception as e:
                    _diag_err(f"⚠️ Voiceover failed, continuing without it: {e}", e)
                    voiceover_path = None
            else:
                _diag("🔇 Voiceover disabled — skipping TTS")
                await update_job_async(job_id, stage="voiceover", progress=0.6)

            # ═══ 4. text overlays (اختياري) ═══
            with_text = tmp_dir / "with_text.mp4"

            if overlay_enabled:
                await update_job_async(job_id, stage="text", progress=0.75)

                await _add_property_text_overlays(
                    input_video=stitched,
                    payload=payload,
                    output=with_text,
                    tmp_dir=tmp_dir,
                )
            else:
                _diag("📝 Text overlays disabled — skipping")
                shutil.copy(stitched, with_text)
                await update_job_async(job_id, stage="text", progress=0.75)

            # ═══ 5. audio mix ═══
            await update_job_async(job_id, stage="audio", progress=0.85)

            final_video = tmp_dir / "final.mp4"

            if voiceover_path and voiceover_path.exists():
                await _attach_voiceover(
                    video_path=with_text,
                    voiceover_path=voiceover_path,
                    output=final_video,
                )
            else:
                shutil.copy(with_text, final_video)

            # ═══ 6. upload ═══
            await update_job_async(job_id, stage="upload", progress=0.92)

            project_id = payload.get("project_id", "unknown")
            unique = uuid.uuid4().hex[:12]
            remote_path = f"property_videos/{project_id}/{unique}.mp4"

            final_url: Optional[str] = None

            if settings.supabase_configured:
                try:
                    from application.services.production_service import (
                        _upload_to_supabase, _build_public_url,
                    )
                    storage = SupabaseStorageAdapter()

                    await _upload_to_supabase(
                        storage=storage,
                        local_path=final_video,
                        remote_path=remote_path,
                        content_type="video/mp4",
                    )
                    final_url = await _build_public_url(storage, remote_path)
                except Exception as e:
                    _diag_err(f"⚠️ Supabase upload failed: {e}", e)

            if not final_url:
                local_dest = PROPERTY_VIDEOS_DIR / f"{project_id}_{unique}.mp4"
                shutil.copy(final_video, local_dest)
                final_url = f"/static/media/property_videos/{local_dest.name}"
                remote_path = str(local_dest)

            real_duration = await _get_video_duration(final_video)

            # ✅ حفظ النتيجة النهائية في Supabase Storage
            await update_job_async(
                job_id,
                status="done",
                stage="done",
                progress=1.0,
                video_url=final_url,
                path=remote_path,
                duration=real_duration,
                property_meta={
                    "title": payload.get("title"),
                    "price": payload.get("price"),
                    "currency": payload.get("currency"),
                    "city": payload.get("city"),
                    "district": payload.get("district"),
                    "property_type": payload.get("property_type"),
                },
            )

            _diag(f"✅ Property video done: {final_url} ({real_duration:.2f}s)")

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        _diag_err(f"❌ Property video job failed: {e}", e)
        await update_job_async(job_id, status="failed", error=str(e))


# ─────────────────────────────────────────────────────────
# FFmpeg Helpers
# ─────────────────────────────────────────────────────────

async def _render_motion_clip(
    image_path: Path,
    output_path: Path,
    duration: float,
    motion: str = "auto",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> None:
    """يولّد مقطع فيديو من صورة بحركة Pan/Zoom."""
    if motion == "auto":
        motion = random.choice([
            "zoom_in", "zoom_out", "pan_left",
            "pan_right", "pan_up", "pan_down",
            "diagonal", "cinematic",
        ])

    frames = max(1, int(duration * fps))
    lw, lh = width * 2, height * 2

    base = (
        f"scale={lw}:{lh}:force_original_aspect_ratio=increase,"
        f"crop={lw}:{lh},"
    )

    motion_map = {
        "zoom_in": (
            f"zoompan=z='min(1.20,1+0.20*on/{frames})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "zoom_out": (
            f"zoompan=z='max(1.0,1.20-0.20*on/{frames})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_left": (
            f"zoompan=z='1.10':x='(iw-iw/zoom)*on/{frames}':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_right": (
            f"zoompan=z='1.10':x='(iw-iw/zoom)*(1-on/{frames})':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_up": (
            f"zoompan=z='1.10':x='iw/2-(iw/zoom/2)':"
            f"y='(ih-ih/zoom)*on/{frames}':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_down": (
            f"zoompan=z='1.10':x='iw/2-(iw/zoom/2)':"
            f"y='(ih-ih/zoom)*(1-on/{frames})':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "diagonal": (
            f"zoompan=z='1.05+0.10*on/{frames}':"
            f"x='(iw-iw/zoom)*on/{frames}':"
            f"y='(ih-ih/zoom)*(1-on/{frames})':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "cinematic": (
            f"zoompan=z='1.02+0.08*sin(on/{frames}*PI/2)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
    }

    vf = base + motion_map.get(motion, motion_map["zoom_in"])

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        "-t", str(duration),
        "-r", str(fps),
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"motion render failed: {stderr.decode(errors='ignore')[-500:]}"
        )


async def _concat_video_clips(
    clips: List[Path],
    output: Path,
    tmp_dir: Path,
) -> None:
    """يدمج مقاطع الفيديو."""
    concat_file = tmp_dir / "concat.txt"

    with concat_file.open("w", encoding="utf-8") as f:
        for clip in clips:
            safe = str(clip.absolute()).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"concat failed: {stderr.decode(errors='ignore')[-500:]}"
        )


def _format_price_ar(price, currency: str = "SAR") -> str:
    """يُنسّق السعر بالعربي."""
    if not price:
        return ""
    symbol = {
        "SAR": "ريال",
        "AED": "درهم",
        "EGP": "جنيه",
        "USD": "$",
        "EUR": "€",
    }.get(currency, currency)
    try:
        price = float(price)
    except (TypeError, ValueError):
        return str(price)
    if price >= 1_000_000:
        v = f"{price / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{v} مليون {symbol}"
    if price >= 1_000:
        return f"{price / 1_000:.0f} ألف {symbol}"
    return f"{price:,.0f} {symbol}"


def _build_property_script(payload: Dict[str, Any]) -> str:
    """يبني نص التعليق الصوتي بالعربي."""
    type_map = {
        "land": "أرض", "villa": "فيلا", "apartment": "شقة",
        "building": "مبنى", "facade": "واجهة", "room": "غرفة",
        "hall": "صالة", "street": "موقع",
    }
    t = type_map.get(payload.get("property_type", ""), "عقار")

    parts: List[str] = []

    city = payload.get("city", "")
    district = payload.get("district", "")

    if district and city:
        parts.append(f"نقدم لكم {t} مميزة في حي {district} بمدينة {city}.")
    elif city:
        parts.append(f"نقدم لكم {t} مميزة في مدينة {city}.")
    else:
        parts.append(f"نقدم لكم {t} مميزة للبيع.")

    specs: List[str] = []
    if payload.get("area_sqm"):
        specs.append(f"مساحة {payload['area_sqm']:g} متر مربع")
    if payload.get("bedrooms"):
        specs.append(f"{payload['bedrooms']} غرف نوم")
    if payload.get("bathrooms"):
        specs.append(f"{payload['bathrooms']} دورات مياه")

    if specs:
        parts.append("تتميز بـ " + "، ".join(specs) + ".")

    features = payload.get("features", [])
    if features:
        parts.append("وتشمل " + "، ".join(features[:5]) + ".")

    price = payload.get("price")
    if price:
        parts.append(
            f"السعر {_format_price_ar(price, payload.get('currency', 'SAR'))}."
        )

    wa = payload.get("whatsapp", "")
    if wa:
        digits = " ".join(c for c in wa if c.isdigit())
        parts.append(f"للتواصل والاستفسار، اتصل على {digits}.")
    else:
        parts.append("للتواصل والاستفسار، راسلنا في التعليقات.")

    return " ".join(parts)


def _find_arabic_font() -> Optional[str]:
    """يبحث عن خط عربي متاح."""
    candidates = [
        "fonts/Cairo-Bold.ttf",
        "static/fonts/Cairo-Bold.ttf",
        "fonts/NotoNaskhArabic-Bold.ttf",
        "static/fonts/NotoNaskhArabic-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


async def _add_property_text_overlays(
    input_video: Path,
    payload: Dict[str, Any],
    output: Path,
    tmp_dir: Path,
) -> None:
    """يضيف النصوص العربية على الفيديو."""

    if not any([
        payload.get("show_price", True),
        payload.get("show_location", True),
        payload.get("show_area", True),
        payload.get("show_contact", True),
    ]):
        _diag("📝 All text overlays disabled — skipping")
        shutil.copy(input_video, output)
        return

    font = _find_arabic_font()
    if not font:
        _diag("⚠️ No Arabic font found — skipping text overlays")
        shutil.copy(input_video, output)
        return

    type_map = {
        "land": "أرض", "villa": "فيلا", "apartment": "شقة",
        "building": "مبنى", "facade": "واجهة", "room": "غرفة",
        "hall": "صالة", "street": "موقع",
    }
    t = type_map.get(payload.get("property_type", ""), "عقار")

    title = payload.get("title") or f"{t} للبيع"
    location = " - ".join(filter(None, [
        payload.get("district", ""),
        payload.get("city", ""),
    ]))
    price = _format_price_ar(
        payload.get("price"),
        payload.get("currency", "SAR"),
    ) if payload.get("show_price", True) else ""

    details_parts: List[str] = []
    if payload.get("show_area", True):
        if payload.get("area_sqm"):
            details_parts.append(f"{payload['area_sqm']:g} م²")
        if payload.get("bedrooms"):
            details_parts.append(f"{payload['bedrooms']} غرف")

    details = "   ".join(details_parts)
    contact = payload.get("whatsapp", "") if payload.get("show_contact", True) else ""

    def _write_text(name: str, text: str) -> str:
        p = tmp_dir / f"txt_{name}.txt"
        p.write_text(text, encoding="utf-8")
        return str(p)

    filters: List[str] = []

    if title:
        f = _write_text("title", title)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=64:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw=20:"
            f"x=(w-text_w)/2:y=h*0.08"
        )

    if location and payload.get("show_location", True):
        f = _write_text("loc", location)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=42:fontcolor=white:"
            f"box=1:boxcolor=black@0.4:boxborderw=14:"
            f"x=(w-text_w)/2:y=h*0.17"
        )

    if price:
        f = _write_text("price", price)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=72:fontcolor=black:"
            f"box=1:boxcolor=white@0.9:boxborderw=24:"
            f"x=(w-text_w)/2:y=h*0.72"
        )

    if details:
        f = _write_text("details", details)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=36:fontcolor=white:"
            f"box=1:boxcolor=black@0.5:boxborderw=16:"
            f"x=(w-text_w)/2:y=h*0.85"
        )

    if contact:
        f = _write_text("contact", contact)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=38:fontcolor=white:"
            f"box=1:boxcolor=black@0.7:boxborderw=18:"
            f"x=(w-text_w)/2:y=h*0.92"
        )

    if not filters:
        shutil.copy(input_video, output)
        return

    vf = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"text overlay failed: {stderr.decode(errors='ignore')[-500:]}"
        )


async def _attach_voiceover(
    video_path: Path,
    voiceover_path: Path,
    output: Path,
) -> None:
    """يدمج التعليق الصوتي مع الفيديو."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(voiceover_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"voiceover attach failed: {stderr.decode(errors='ignore')[-500:]}"
        )
