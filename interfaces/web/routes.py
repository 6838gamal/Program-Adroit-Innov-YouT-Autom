"""Jinja2 HTML page routes with modern Supabase configuration."""
import uuid
import json
import logging
import tempfile
import asyncio
import subprocess
import hashlib
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import (
    APIRouter, Request, Depends, HTTPException,
    UploadFile, File, Form, BackgroundTasks
)
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
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
# 🎙️ VOICEOVER HELPERS
# ============================================================

VOICEOVER_DIR = Path(settings.MEDIA_DIR) / "voiceovers"
VOICEOVER_DIR.mkdir(parents=True, exist_ok=True)

CLONED_VOICES_DIR = Path(settings.MEDIA_DIR) / "cloned_voices"
CLONED_VOICES_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = CLONED_VOICES_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 🎭 Talking Head
TALKING_HEADS_DIR = Path(settings.MEDIA_DIR) / "talking_heads"
TALKING_HEADS_DIR.mkdir(parents=True, exist_ok=True)

VOICEOVER_MAX_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a",
    "audio/x-m4a", "audio/aac", "audio/flac",
    "video/webm",
}

# تخزين مؤقت
CLONED_VOICE_CACHE: Dict[str, str] = {}
TALKING_HEAD_JOBS: Dict[str, Dict[str, Any]] = {}


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


# ============================================================
# 🎙️ ELEVENLABS — Voice Cloning Helpers
# ============================================================

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


async def _elevenlabs_create_voice(
    audio_content: bytes,
    voice_name: str,
    description: str = "Cloned via dashboard",
) -> str:
    """أنشئ voice clone في ElevenLabs."""
    import httpx

    if not settings.elevenlabs_configured:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY غير مُعرّف في الإعدادات",
        )

    api_key = settings.elevenlabs_api_key_value
    headers = {"xi-api-key": api_key}

    files = {
        "files": ("sample.mp3", audio_content, "audio/mpeg"),
    }
    data = {
        "name": voice_name,
        "description": description,
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{ELEVENLABS_API_BASE}/voices/add",
            headers=headers,
            files=files,
            data=data,
        )

        if r.status_code != 200:
            error_text = r.text[:400]
            logger.error(f"ElevenLabs voice creation failed: {error_text}")
            raise HTTPException(
                status_code=r.status_code,
                detail=f"فشل إنشاء الصوت: {error_text}",
            )

        result = r.json()
        voice_id = result.get("voice_id")
        if not voice_id:
            raise HTTPException(
                status_code=500,
                detail="لم يتم إرجاع voice_id من ElevenLabs",
            )

        logger.info(f"✅ ElevenLabs voice created: {voice_id}")
        return voice_id


async def _elevenlabs_tts(
    text: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.0,
    speed: float = 1.0,
) -> bytes:
    """حوّل النص إلى صوت باستخدام voice clone."""
    import httpx

    if not settings.elevenlabs_configured:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY غير مُعرّف",
        )

    api_key = settings.elevenlabs_api_key_value
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }

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
            headers=headers,
            json=payload,
        )

        if r.status_code != 200:
            error_text = r.text[:400]
            logger.error(f"ElevenLabs TTS failed: {error_text}")
            raise HTTPException(
                status_code=r.status_code,
                detail=f"فشل توليد الصوت: {error_text}",
            )

        return r.content


async def _elevenlabs_delete_voice(voice_id: str) -> bool:
    """احذف voice clone من ElevenLabs."""
    import httpx

    if not settings.elevenlabs_configured:
        return False

    api_key = settings.elevenlabs_api_key_value
    headers = {"xi-api-key": api_key}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(
                f"{ELEVENLABS_API_BASE}/voices/{voice_id}",
                headers=headers,
            )
            return r.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to delete voice {voice_id}: {e}")
        return False


def _compute_text_hash(voice_id: str, text: str, settings_dict: dict) -> str:
    """احسب hash فريد للنص + الصوت + الإعدادات."""
    payload = f"{voice_id}|{text}|{json.dumps(settings_dict, sort_keys=True)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


# ============================================================
# 🎭 TALKING HEAD — D-ID API Helpers
# ============================================================

DID_API_BASE = "https://api.d-id.com"


async def _did_create_talk(
    image_content: bytes,
    audio_content: bytes,
    image_filename: str = "image.jpg",
) -> str:
    """
    أنشئ فيديو talking head من صورة + صوت.
    يعيد: talk_id
    """
    import httpx

    if not settings.did_configured:
        raise HTTPException(
            status_code=503,
            detail="D-ID API غير مهيأ. أضف DID_API_KEY.",
        )

    api_key = settings.did_api_key_value

    # حوّل إلى base64
    img_b64 = base64.b64encode(image_content).decode()
    aud_b64 = base64.b64encode(audio_content).decode()

    # اكتشف نوع الصورة
    suffix = Path(image_filename).suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")

    payload = {
        "source_url": f"data:{mime};base64,{img_b64}",
        "script": {
            "type": "audio",
            "audio_url": f"data:audio/mpeg;base64,{aud_b64}",
        },
        "config": {
            "stitch": True,
            "pad_audio": 0.0,
        },
    }

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{DID_API_BASE}/talks",
            headers=headers,
            json=payload,
        )

        if r.status_code not in (200, 201):
            error_text = r.text[:500]
            logger.error(f"D-ID talk creation failed: {error_text}")
            raise HTTPException(
                status_code=r.status_code,
                detail=f"فشل إنشاء الفيديو: {error_text}",
            )

        result = r.json()
        talk_id = result.get("id")
        if not talk_id:
            raise HTTPException(
                status_code=500,
                detail="لم يتم إرجاع talk_id من D-ID",
            )

        logger.info(f"✅ D-ID talk created: {talk_id}")
        return talk_id


async def _did_get_talk_status(talk_id: str) -> Dict[str, Any]:
    """احصل على حالة الـ talk."""
    import httpx

    if not settings.did_configured:
        raise HTTPException(status_code=503, detail="D-ID API غير مهيأ")

    api_key = settings.did_api_key_value
    headers = {"Authorization": api_key}

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{DID_API_BASE}/talks/{talk_id}",
            headers=headers,
        )

        if r.status_code != 200:
            error_text = r.text[:500]
            logger.error(f"D-ID get status failed: {error_text}")
            raise HTTPException(
                status_code=r.status_code,
                detail=f"فشل جلب الحالة: {error_text}",
            )

        return r.json()


async def _did_delete_talk(talk_id: str) -> bool:
    """احذف talk من D-ID."""
    import httpx

    if not settings.did_configured:
        return False

    api_key = settings.did_api_key_value
    headers = {"Authorization": api_key}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(
                f"{DID_API_BASE}/talks/{talk_id}",
                headers=headers,
            )
            return r.status_code in (200, 204)
    except Exception as e:
        logger.warning(f"Failed to delete talk {talk_id}: {e}")
        return False


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

    # Build scenes
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

    # اجلب مقاطع الصوت + الأصوات المحفوظة
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
# 🎙️ VOICEOVER STUDIO — APIs
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
    """رفع تسجيل صوتي مخصص + النص المُزامن."""
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )
        if len(content) > VOICEOVER_MAX_SIZE:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"حجم الملف يتجاوز {VOICEOVER_MAX_SIZE // (1024*1024)}MB",
                },
                status_code=413,
            )

        content_type = file.content_type or "audio/webm"
        suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        if content_type not in ALLOWED_AUDIO_TYPES:
            logger.warning(f"Unexpected audio type: {content_type}, suffix={suffix}")

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

            logger.info(
                f"✅ Voiceover uploaded: {uploaded['url']} "
                f"(duration={duration:.2f}s, segments={len(segments)})"
            )

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
    """استخراج النص من ملف صوتي باستخدام Whisper."""
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

        logger.info(
            f"🎬 Transcribing {file.filename} (lang={language}, model={model_size})"
        )

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

        logger.info(
            f"✅ Transcription done: {len(segments)} segments, "
            f"lang={detected_lang}, duration={duration:.2f}s"
        )

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
                "error": (
                    "Whisper غير مثبّت. شغّل:\n"
                    "  pip install faster-whisper\n"
                    "أو:\n"
                    "  pip install openai-whisper"
                ),
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


# ============================================================
# 🎙️ VOICE CLONING — ElevenLabs
# ============================================================

@router.post("/api/voice/clone")
async def clone_user_voice(
    file: UploadFile = File(...),
    name: str = Form("MyVoice"),
    project_id: str = Form(""),
    description: str = Form(""),
):
    """🎙️ استنسخ صوت المستخدم من تسجيل."""
    try:
        if not settings.elevenlabs_configured:
            return JSONResponse(
                {
                    "success": False,
                    "error": "خدمة استنساخ الصوت غير مهيأة. أضف ELEVENLABS_API_KEY.",
                },
                status_code=503,
            )

        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        if len(content) < 30 * 1024:
            return JSONResponse(
                {
                    "success": False,
                    "error": "التسجيل قصير جداً. الحد الأدنى ~30 ثانية.",
                },
                status_code=400,
            )

        if len(content) > 25 * 1024 * 1024:
            return JSONResponse(
                {"success": False, "error": "الملف كبير جداً (الحد 25MB)"},
                status_code=413,
            )

        voice_name = f"{name}_{uuid.uuid4().hex[:6]}"

        logger.info(
            f"🎙️ Creating voice clone: {voice_name} ({len(content)} bytes)"
        )

        voice_id = await _elevenlabs_create_voice(
            audio_content=content,
            voice_name=voice_name,
            description=description or "Cloned via Voiceover Studio",
        )

        cache_key = f"{project_id}:{name}" if project_id else name
        CLONED_VOICE_CACHE[cache_key] = voice_id

        return {
            "success": True,
            "voice_id": voice_id,
            "name": voice_name,
            "original_name": name,
            "project_id": project_id,
            "message": "✅ تم استنساخ الصوت بنجاح. يمكنك الآن توليد النص بصوتك.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Voice cloning failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


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
    """🎙️ ولّد الصوت من النص باستخدام voice clone."""
    try:
        if not settings.elevenlabs_configured:
            return JSONResponse(
                {"success": False, "error": "خدمة ElevenLabs غير مهيأة"},
                status_code=503,
            )

        script = script.strip()
        if not script:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(script) > settings.ELEVENLABS_MAX_CHARS:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"النص طويل جداً (الحد {settings.ELEVENLABS_MAX_CHARS})",
                },
                status_code=400,
            )

        logger.info(
            f"🎙️ TTS: voice_id={voice_id[:12]}..., "
            f"chars={len(script)}, speed={speed}"
        )

        audio_bytes = await _elevenlabs_tts(
            text=script,
            voice_id=voice_id,
            model_id=model_id,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            speed=speed,
        )

        out_name = f"cloned_{uuid.uuid4().hex[:12]}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)

        url = None
        if project_id and settings.supabase_configured:
            try:
                from application.services.production_service import (
                    _upload_to_supabase, _build_public_url,
                )
                storage = SupabaseStorageAdapter()
                remote_path = f"cloned_voices/{project_id}/{out_name}"
                await _upload_to_supabase(
                    storage=storage,
                    local_path=tmp_out,
                    remote_path=remote_path,
                    content_type="audio/mpeg",
                )
                url = await _build_public_url(storage, remote_path)
            except Exception as e:
                logger.warning(f"Supabase upload failed: {e}")

        if not url:
            url = f"/static/media/cloned_voices/{out_name}"

        logger.info(
            f"✅ Voice generated: {out_name} ({len(audio_bytes)} bytes, {duration:.2f}s)"
        )

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/mpeg",
            filename=out_name,
            headers={
                "X-Cloned-URL": url,
                "X-Duration": str(round(duration, 2)),
                "X-Voice-ID": voice_id,
                "X-Script-Length": str(len(script)),
                "Access-Control-Expose-Headers":
                    "X-Cloned-URL, X-Duration, X-Voice-ID, X-Script-Length",
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
# 💾 MP3 CACHE — تجنّب إعادة التوليد
# ============================================================

@router.post("/api/voice/generate-cached")
async def generate_with_cache(
    voice_id: str = Form(...),
    script: str = Form(...),
    project_id: str = Form(""),
    stability: float = Form(0.5),
    similarity_boost: float = Form(0.75),
    style: float = Form(0.0),
    speed: float = Form(1.0),
    model_id: str = Form(""),
    use_cache: str = Form("true"),
):
    """
    توليد الصوت مع Cache:
      1. احسب hash للنص + الإعدادات
      2. ابحث في cache
      3. إذا وُجد → أعد الملف المحفوظ (بدون ElevenLabs)
      4. إذا لم يوجد → ولّد واحفظ
    """
    try:
        if not settings.elevenlabs_configured:
            return JSONResponse(
                {"success": False, "error": "ElevenLabs غير مهيأ"},
                status_code=503,
            )

        script = script.strip()
        if not script:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(script) > settings.ELEVENLABS_MAX_CHARS:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"النص طويل جداً (الحد {settings.ELEVENLABS_MAX_CHARS})",
                },
                status_code=400,
            )

        model_id = model_id or settings.ELEVENLABS_MODEL_ID
        settings_dict = {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "speed": speed,
            "model_id": model_id,
        }

        text_hash = _compute_text_hash(voice_id, script, settings_dict)

        # ── 1. ابحث في Cache ──
        cached_file = CACHE_DIR / f"{text_hash}.mp3"

        if use_cache.lower() == "true" and cached_file.exists():
            logger.info(f"💾 Cache HIT: {text_hash}")
            duration = await _get_audio_duration(cached_file)
            url = f"/static/media/cloned_voices/cache/{cached_file.name}"

            return FileResponse(
                path=str(cached_file),
                media_type="audio/mpeg",
                filename=f"cached_{text_hash}.mp3",
                headers={
                    "X-Cloned-URL": url,
                    "X-Duration": str(round(duration, 2)),
                    "X-Voice-ID": voice_id,
                    "X-Script-Length": str(len(script)),
                    "X-Cache-Hit": "true",
                    "X-Text-Hash": text_hash,
                    "Access-Control-Expose-Headers":
                        "X-Cloned-URL, X-Duration, X-Voice-ID, X-Script-Length, X-Cache-Hit, X-Text-Hash",
                },
            )

        # ── 2. لم يوجد → ولّد عبر ElevenLabs ──
        logger.info(f"🎙️ Cache MISS: {text_hash} → ElevenLabs")

        audio_bytes = await _elevenlabs_tts(
            text=script,
            voice_id=voice_id,
            model_id=model_id,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            speed=speed,
        )

        cached_file.write_bytes(audio_bytes)

        out_name = f"cloned_{text_hash}.mp3"
        tmp_out = CLONED_VOICES_DIR / out_name
        if not tmp_out.exists():
            tmp_out.write_bytes(audio_bytes)

        duration = await _get_audio_duration(tmp_out)

        url = None
        if project_id and settings.supabase_configured:
            try:
                from application.services.production_service import (
                    _upload_to_supabase, _build_public_url,
                )
                storage = SupabaseStorageAdapter()
                remote_path = f"cloned_voices/{project_id}/{out_name}"
                await _upload_to_supabase(
                    storage=storage,
                    local_path=tmp_out,
                    remote_path=remote_path,
                    content_type="audio/mpeg",
                )
                url = await _build_public_url(storage, remote_path)
            except Exception as e:
                logger.warning(f"Supabase upload failed: {e}")

        if not url:
            url = f"/static/media/cloned_voices/{out_name}"

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/mpeg",
            filename=out_name,
            headers={
                "X-Cloned-URL": url,
                "X-Duration": str(round(duration, 2)),
                "X-Voice-ID": voice_id,
                "X-Script-Length": str(len(script)),
                "X-Cache-Hit": "false",
                "X-Text-Hash": text_hash,
                "Access-Control-Expose-Headers":
                    "X-Cloned-URL, X-Duration, X-Voice-ID, X-Script-Length, X-Cache-Hit, X-Text-Hash",
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
# ▶️ VOICE PREVIEW — معاينة سريعة
# ============================================================

@router.post("/api/voice/preview")
async def preview_saved_voice(
    voice_id: str = Form(...),
    text: str = Form("مرحباً، هذا اختبار لصوتي."),
):
    """معاينة سريعة لصوت محفوظ."""
    try:
        if not settings.elevenlabs_configured:
            return JSONResponse(
                {"success": False, "error": "ElevenLabs غير مهيأ"},
                status_code=503,
            )

        if len(text) > 200:
            text = text[:200]

        audio_bytes = await _elevenlabs_tts(
            text=text,
            voice_id=voice_id,
            model_id=settings.ELEVENLABS_MODEL_ID,
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=1.0,
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
# 📋 LIST CLONES from ElevenLabs
# ============================================================

@router.get("/api/voice/clones")
async def list_cloned_voices():
    """اعرض الأصوات المُستنسخة من ElevenLabs."""
    import httpx

    if not settings.elevenlabs_configured:
        return {"success": False, "error": "غير مهيأ", "voices": []}

    try:
        api_key = settings.elevenlabs_api_key_value
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{ELEVENLABS_API_BASE}/voices",
                headers={"xi-api-key": api_key},
            )
            if r.status_code != 200:
                return {"success": False, "voices": []}

            data = r.json()
            voices = [
                {
                    "voice_id": v["voice_id"],
                    "name": v["name"],
                    "category": v.get("category", ""),
                    "description": v.get("description", ""),
                }
                for v in data.get("voices", [])
                if v.get("category") == "cloned"
            ]
            return {"success": True, "count": len(voices), "voices": voices}
    except Exception as e:
        return {"success": False, "error": str(e), "voices": []}


@router.delete("/api/voice/clones/{voice_id}")
async def delete_cloned_voice(voice_id: str):
    """احذف voice clone من ElevenLabs."""
    success = await _elevenlabs_delete_voice(voice_id)
    if success:
        for k, v in list(CLONED_VOICE_CACHE.items()):
            if v == voice_id:
                del CLONED_VOICE_CACHE[k]
    return {"success": success}


# ============================================================
# 💾 SAVED VOICES — حفظ أصوات المستخدم في المشروع
# ============================================================

@router.get("/api/voice/saved/{project_id}")
async def list_saved_voices(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    """اعرض الأصوات المحفوظة في المشروع."""
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
    """احفظ voice_id في المشروع."""
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
        "provider": "elevenlabs",
        "created_at": datetime.utcnow().isoformat(),
        "preview_url": payload.get("preview_url"),
        "description": payload.get("description", ""),
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
    """احذف صوت محفوظ من المشروع (والـ ElevenLabs)."""
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
    if voice_id:
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
    """حدّث اسم الصوت المحفوظ."""
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
# 📤 EXPORT / 📥 IMPORT — نسخة احتياطية للأصوات
# ============================================================

@router.get("/api/voice/export/{project_id}")
async def export_project_voices(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    """صدّر كل الأصوات المحفوظة في المشروع كملف JSON."""
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
        "provider": "elevenlabs",
        "voices_count": len(saved_voices),
        "voices": saved_voices,
        "metadata": {
            "app": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "model_id": settings.ELEVENLABS_MODEL_ID,
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
    """استورد الأصوات من ملف JSON."""
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
            voice.setdefault("provider", "elevenlabs")
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
            voice.setdefault("provider", "elevenlabs")
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
# 💾 CACHE MANAGEMENT
# ============================================================

@router.get("/api/voice/cache/stats")
async def get_cache_stats():
    """إحصائيات الـ cache."""
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
    """امسح كل الـ cache."""
    deleted = 0
    for f in CACHE_DIR.glob("*.mp3"):
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete {f}: {e}")

    return {"success": True, "deleted": deleted}


# ============================================================
# 🎭 TALKING HEAD — D-ID
# ============================================================

@router.post("/api/talking-head/create")
async def create_talking_head(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    project_id: str = Form(""),
):
    """
    🎭 أنشئ فيديو talking head من صورة + صوت.

    Args:
        image: صورة الشخص (وجه واضح، jpg/png)
        audio: الصوت (mp3/wav)
        project_id: المشروع

    Returns:
        {success: true, talk_id: "...", status: "created"}
    """
    try:
        if not settings.did_configured:
            return JSONResponse(
                {
                    "success": False,
                    "error": "D-ID API غير مهيأ. أضف DID_API_KEY.",
                },
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

        if len(img_content) > 10 * 1024 * 1024:
            return JSONResponse(
                {"success": False, "error": "الصورة كبيرة جداً (الحد 10MB)"},
                status_code=413,
            )

        if len(aud_content) > 100 * 1024 * 1024:
            return JSONResponse(
                {"success": False, "error": "الصوت كبير جداً (الحد 100MB)"},
                status_code=413,
            )

        logger.info(
            f"🎭 Creating talking head: "
            f"image={len(img_content)} bytes, "
            f"audio={len(aud_content)} bytes"
        )

        talk_id = await _did_create_talk(
            image_content=img_content,
            audio_content=aud_content,
            image_filename=image.filename or "image.jpg",
        )

        TALKING_HEAD_JOBS[talk_id] = {
            "id": talk_id,
            "project_id": project_id,
            "status": "created",
            "created_at": datetime.utcnow().isoformat(),
            "result_url": None,
            "error": None,
        }

        return {
            "success": True,
            "talk_id": talk_id,
            "status": "created",
            "message": "✅ تم إنشاء الفيديو. جاري المعالجة...",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Talking head creation failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.get("/api/talking-head/status/{talk_id}")
async def get_talking_head_status(talk_id: str):
    """
    احصل على حالة معالجة الفيديو.

    Returns:
        {success: true, status: "created"|"started"|"done"|"error", result_url: "..."}
    """
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID API غير مهيأ"},
                status_code=503,
            )

        data = await _did_get_talk_status(talk_id)

        status = data.get("status", "unknown")
        result_url = data.get("result_url")
        error = data.get("error")

        if talk_id in TALKING_HEAD_JOBS:
            TALKING_HEAD_JOBS[talk_id].update({
                "status": status,
                "result_url": result_url,
                "error": error,
            })

        return {
            "success": True,
            "talk_id": talk_id,
            "status": status,
            "result_url": result_url,
            "error": error,
            "progress": data.get("progress"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get talking head status failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/talking-head/generate")
async def generate_talking_head_from_text(
    image: UploadFile = File(...),
    text: str = Form(...),
    voice_id: str = Form(""),
    language: str = Form("ar"),
    project_id: str = Form(""),
):
    """
    🎭 نسخة مُحسّنة: صورة + نص → فيديو.

    يقوم بـ:
      1. توليد الصوت من النص (ElevenLabs)
      2. إنشاء talking head (D-ID)

    Args:
        image: صورة الشخص
        text: النص
        voice_id: voice_id من ElevenLabs
        language: اللغة
        project_id: المشروع

    Returns:
        {success: true, talk_id: "..."}
    """
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID API غير مهيأ"},
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
                    "error": f"النص طويل جداً (الحد {settings.DID_MAX_TEXT_CHARS} حرف)",
                },
                status_code=400,
            )

        img_content = await image.read()
        if not img_content:
            return JSONResponse(
                {"success": False, "error": "الصورة فارغة"},
                status_code=400,
            )

        # ── 1. ولّد الصوت من النص ──
        audio_bytes = None

        if voice_id and settings.elevenlabs_configured:
            logger.info(f"🎙️ Using ElevenLabs voice: {voice_id}")
            audio_bytes = await _elevenlabs_tts(
                text=text,
                voice_id=voice_id,
                model_id=settings.ELEVENLABS_MODEL_ID,
                stability=0.5,
                similarity_boost=0.75,
                style=0.0,
                speed=1.0,
            )
        else:
            return JSONResponse(
                {
                    "success": False,
                    "error": "يجب توفير voice_id أو تفعيل ElevenLabs",
                },
                status_code=400,
            )

        if not audio_bytes:
            return JSONResponse(
                {"success": False, "error": "فشل توليد الصوت"},
                status_code=500,
            )

        # ── 2. أنشئ talking head ──
        logger.info(f"🎭 Creating talking head from image + generated audio")

        talk_id = await _did_create_talk(
            image_content=img_content,
            audio_content=audio_bytes,
            image_filename=image.filename or "image.jpg",
        )

        TALKING_HEAD_JOBS[talk_id] = {
            "id": talk_id,
            "project_id": project_id,
            "status": "created",
            "text": text,
            "voice_id": voice_id,
            "created_at": datetime.utcnow().isoformat(),
            "result_url": None,
            "error": None,
        }

        return {
            "success": True,
            "talk_id": talk_id,
            "status": "created",
            "message": "✅ تم إنشاء الفيديو. جاري المعالجة...",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Generate talking head failed")
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
    """
    احفظ فيديو talking head في المشروع (كـ clip).
    """
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
        "title": payload.get("title", "Talking Head"),
        "url": video_url,
        "start": payload.get("start", 0),
        "duration": payload.get("duration", 5),
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

    logger.info(f"✅ Talking head saved to project: {clip_id}")

    return {
        "success": True,
        "clip": new_clip,
        "message": "✅ تم حفظ الفيديو في المشروع",
    }


@router.delete("/api/talking-head/delete/{talk_id}")
async def delete_talking_head(talk_id: str):
    """احذف talking head job من D-ID."""
    success = await _did_delete_talk(talk_id)
    if talk_id in TALKING_HEAD_JOBS:
        del TALKING_HEAD_JOBS[talk_id]
    return {"success": success, "talk_id": talk_id}


@router.get("/api/talking-head/list")
async def list_talking_head_jobs():
    """اعرض قائمة talking head jobs النشطة."""
    return {
        "success": True,
        "count": len(TALKING_HEAD_JOBS),
        "jobs": list(TALKING_HEAD_JOBS.values()),
    }


# ============================================================
# 🎚️ AUDIO PROCESSING — FFmpeg
# ============================================================

@router.post("/api/media/process-audio")
async def process_audio_endpoint(
    file: UploadFile = File(...),
    options: str = Form("{}"),
):
    """معالجة الصوت باستخدام ffmpeg."""
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

        cmd = [
            "ffmpeg", "-y",
            "-i", str(tmp_in),
            "-vn",
            "-c:a", "libopus",
            "-b:a", "128k",
        ]
        if filters:
            cmd += ["-af", ",".join(filters)]
        cmd.append(str(tmp_out))

        logger.info(f"🎚️ Processing audio with filters: {filters}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode()[-800:]
            logger.error(f"ffmpeg failed: {error_msg}")
            raise RuntimeError(f"ffmpeg error: {error_msg}")

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
            {
                "success": False,
                "error": "ffmpeg غير مثبّت على الخادم.",
            },
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
# 🎯 ALIGN SCRIPT — Voice Cloning (Backward Compatible)
# ============================================================

@router.post("/api/media/align-script")
async def align_script_with_audio(
    file: UploadFile = File(...),
    script: str = Form(...),
    language: str = Form("ar"),
    voice_id: str = Form(""),
    project_id: str = Form(""),
):
    """🎙️ Voice Cloning — النص المكتوب بصوت المستخدم."""
    try:
        if not settings.elevenlabs_configured:
            return JSONResponse(
                {
                    "success": False,
                    "error": "خدمة استنساخ الصوت غير مهيأة. أضف ELEVENLABS_API_KEY.",
                },
                status_code=503,
            )

        if voice_id:
            logger.info(f"🎙️ Using existing voice: {voice_id}")
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

        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        if len(content) < 30 * 1024:
            return JSONResponse(
                {
                    "success": False,
                    "error": "التسجيل قصير جداً. سجّل 30 ثانية على الأقل.",
                },
                status_code=400,
            )

        voice_name = f"AutoVoice_{uuid.uuid4().hex[:6]}"

        logger.info(f"🎙️ Auto-cloning voice from upload ({len(content)} bytes)")

        new_voice_id = await _elevenlabs_create_voice(
            audio_content=content,
            voice_name=voice_name,
            description="Auto-cloned from upload",
        )

        if project_id:
            CLONED_VOICE_CACHE[project_id] = new_voice_id

        return await generate_with_cloned_voice(
            voice_id=new_voice_id,
            script=script,
            project_id=project_id,
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=1.0,
            model_id=settings.ELEVENLABS_MODEL_ID,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Align script failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


# ============================================================
# 🎙️ VOICEOVER — CRUD
# ============================================================

@router.get("/api/media/voiceover/{project_id}")
async def list_voiceovers(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    """اعرض جميع مقاطع الصوت في مشروع."""
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
            "tts": c.get("tts"),
            "fileName": c.get("fileName"),
            "layerId": c.get("layerId"),
            "processed": c.get("processed", False),
            "processingOptions": c.get("processingOptions"),
            "voice_id": c.get("voice_id"),
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
    """احذف مقطع صوتي + ملفه من التخزين."""
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
            logger.warning(f"Failed to delete storage file: {e}")

    local_path = target.get("path")
    if local_path and isinstance(local_path, str) and local_path.startswith("/"):
        try:
            p = Path(local_path)
            if p.exists() and p.is_file():
                p.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete local file: {e}")

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
    """حدّث بيانات مقطع صوتي."""
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
    """أضف مقطع صوتي/فيديو جديد إلى المشروع."""
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
        project.data = data
    if hasattr(repo, "update"):
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
    """رفع ملف وسائط عام إلى Supabase Storage."""
    try:
        from application.services.production_service import (
            _upload_to_supabase,
            _build_public_url,
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

            logger.info(f"📤 Uploading media: {file.filename} → {remote_path}")

            await _upload_to_supabase(
                storage=storage,
                local_path=tmp_path,
                remote_path=remote_path,
                content_type=content_type,
            )

            url = await _build_public_url(storage, remote_path)
            if not url:
                raise RuntimeError("فشل بناء الرابط العام")

            return {"url": url, "path": remote_path}
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Failed to upload media")
        return JSONResponse({"error": str(e)}, status_code=500)


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
            "description": "قالب مناسب لفيديوهات قصيرة من 30 ثانية إلى 3 دقائق",
            "gradient": "from-blue-900 to-blue-700",
            "ratio": "16:9",
            "tags": ["تعليم", "عروض", "تسويق"],
            "quality": 4,
        },
        {
            "id": "reel",
            "name": "ريلز / شورتس",
            "description": "قالب عمودي لمنصات TikTok وInstagram Reels وYouTube Shorts",
            "gradient": "from-pink-900 to-purple-800",
            "ratio": "9:16",
            "tags": ["ريلز", "شورتس", "سوشيال"],
            "quality": 4,
        },
        {
            "id": "educational",
            "name": "تعليمي",
            "description": "قالب طويل للمحتوى التعليمي والشرح التفصيلي",
            "gradient": "from-emerald-900 to-teal-800",
            "ratio": "16:9",
            "tags": ["تعليم", "شرح", "درس"],
            "quality": 5,
        },
        {
            "id": "product",
            "name": "مراجعة منتج",
            "description": "قالب متخصص للمراجعات والعروض التقديمية",
            "gradient": "from-amber-900 to-orange-800",
            "ratio": "16:9",
            "tags": ["مراجعة", "تقنية", "منتج"],
            "quality": 4,
        },
        {
            "id": "square",
            "name": "مربع",
            "description": "قالب مربع لمنصات Instagram وLinkedIn",
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
            "id": "elevenlabs",
            "name": "ElevenLabs Voice Cloning",
            "provider": "ElevenLabs API",
            "description": "استنسخ صوتك من تسجيل 30 ثانية، ثم ولّد أي نص بصوتك.",
            "languages": ["ar", "en", "fr", "de", "es", "it", "pt", "pl", "tr", "ru", "nl", "cs", "zh", "ja", "ko", "hi"],
            "quality": 5,
            "available": settings.elevenlabs_configured,
            "active": settings.elevenlabs_configured,
        },
        {
            "id": "did_talking_head",
            "name": "D-ID Talking Head",
            "provider": "D-ID API",
            "description": "حوّل صورة شخص إلى فيديو ناطق باستخدام AI.",
            "languages": ["كل اللغات"],
            "quality": 5,
            "available": settings.did_configured,
            "active": settings.did_configured,
        },
        {
            "id": "silent",
            "name": "Silent",
            "provider": "Built-in",
            "description": "لا يولّد صوتاً. مفيد للفيديوهات الصامتة.",
            "languages": ["كل اللغات"],
            "quality": 1,
            "available": True,
            "active": False,
        },
    ]
    return templates.TemplateResponse(request, "voices.html", {
        "voice_engines": voice_engines,
        "active_voice": "ElevenLabs Voice Cloning" if settings.elevenlabs_configured else "Silent",
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
        SQLPublishingJobRepository,
        SQLAccountRepository,
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
        "draft": "bg-slate-500",
        "in_production": "bg-amber-500",
        "rendered": "bg-green-500",
        "published": "bg-blue-500",
        "failed": "bg-red-500",
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
        {"level": "INFO",    "source": "main",    "timestamp": now - timedelta(seconds=5),  "message": "Platform started successfully"},
        {"level": "INFO",    "source": "system",  "timestamp": now - timedelta(seconds=4),  "message": "Database tables ready"},
        {"level": "INFO",    "source": "plugins", "timestamp": now - timedelta(seconds=3),  "message": "Plugins loaded"},
        {"level": "INFO",    "source": "main",    "timestamp": now - timedelta(seconds=1),  "message": "Platform ready"},
    ]

    if settings.supabase_configured:
        log_entries.append({
            "level": "INFO",
            "source": "supabase",
            "timestamp": now,
            "message": f"Supabase configured: {settings.SUPABASE_URL}"
        })

    elevenlabs_ok = settings.elevenlabs_configured
    log_entries.append({
        "level": "INFO" if elevenlabs_ok else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": (
            f"ElevenLabs Voice Cloning: "
            f"{'✅ متاح' if elevenlabs_ok else '❌ غير مهيأ (ELEVENLABS_API_KEY مفقود)'}"
        )
    })

    did_ok = settings.did_configured
    log_entries.append({
        "level": "INFO" if did_ok else "WARNING",
        "source": "talking_head",
        "timestamp": now,
        "message": (
            f"D-ID Talking Head: "
            f"{'✅ متاح' if did_ok else '❌ غير مهيأ (DID_API_KEY مفقود)'}"
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
        "source": "voiceover",
        "timestamp": now,
        "message": f"Whisper engine: {whisper_status}"
    })

    import shutil
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    log_entries.append({
        "level": "INFO" if ffmpeg_ok else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": f"FFmpeg: {'✅ متاح' if ffmpeg_ok else '❌ غير مثبّت'}"
    })

    cache_files = list(CACHE_DIR.glob("*.mp3"))
    cache_size = sum(f.stat().st_size for f in cache_files) / 1024 / 1024
    log_entries.append({
        "level": "INFO",
        "source": "voiceover",
        "timestamp": now,
        "message": f"Voice Cache: {len(cache_files)} files ({cache_size:.1f} MB)"
    })

    return templates.TemplateResponse(request, "logs.html", {
        "log_entries": log_entries,
        "active_page": "logs",
        "supabase": get_supabase_config(),
    })


# ============================================================
# SYSTEM HEALTH
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
            "name": "ElevenLabs Voice Cloning",
            "status": "ok" if elevenlabs_ok else "degraded",
            "detail": "متاح ✅" if elevenlabs_ok else "غير مهيأ — أضف ELEVENLABS_API_KEY",
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
    ]

    system_info = [
        {"label": "Python",       "value": sys.version.split()[0]},
        {"label": "Platform",     "value": platform.system() + " " + platform.release()},
        {"label": "APP_NAME",     "value": settings.APP_NAME},
        {"label": "APP_VERSION",  "value": settings.APP_VERSION},
        {"label": "Supabase",     "value": "✅ مهيأ" if supabase_ok else "❌ غير مهيأ"},
        {"label": "ElevenLabs",   "value": "✅ متاح" if elevenlabs_ok else "❌ غير مهيأ"},
        {"label": "D-ID",         "value": "✅ متاح" if did_ok else "❌ غير مهيأ"},
        {"label": "Whisper",      "value": whisper_detail},
        {"label": "FFmpeg",       "value": "✅ متاح" if ffmpeg_ok else "❌ غير مثبّت"},
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
# MODEL LIBRARY
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
            "exports_dir": str(settings.EXPORTS_DIR),
            "temp_dir": str(settings.TEMP_DIR),
            "storage_type": settings.STORAGE_TYPE,
            "supabase_configured": settings.supabase_configured,
            "elevenlabs_configured": settings.elevenlabs_configured,
            "did_configured": settings.did_configured,
        },
        "active_page": "settings",
        "supabase": get_supabase_config(),
    })


# ============================================================
# SUPABASE CONFIGURATION API
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
            "bucket": settings.SUPABASE_BUCKET
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================
# 🔍 DEBUG ENDPOINTS
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
        "clips_summary": [
            {
                "id": c.get("id"),
                "type": c.get("type"),
                "source": c.get("source"),
                "title": c.get("title"),
            }
            for c in clips if isinstance(c, dict)
        ],
    }


@router.get("/api/debug/talking-head/jobs")
async def debug_talking_head_jobs():
    """اعرض talking head jobs النشطة."""
    return {
        "success": True,
        "count": len(TALKING_HEAD_JOBS),
        "jobs": list(TALKING_HEAD_JOBS.values()),
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
        "elevenlabs_available": settings.elevenlabs_configured,
        "did_available": settings.did_configured,
        "cache_stats": {
            "files": len(cache_files),
            "size_mb": round(cache_size_mb, 2),
        },
    }
