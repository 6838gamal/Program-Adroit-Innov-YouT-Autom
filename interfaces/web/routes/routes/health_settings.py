"""Health, models, settings, and Supabase endpoints."""
import logging
import platform
import shutil
import sys

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.config_helpers import get_supabase_config
from ..core.directories import JOBS_STORAGE_PREFIX
from ..core.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# HEALTH
# ============================================================

@router.get("/health", response_class=HTMLResponse)
async def health_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    db_ok = True
    db_detail = "متصل"
    try:
        from sqlalchemy import text as _sql_text
        await session.execute(_sql_text("SELECT 1"))
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
        import faster_whisper  # noqa
        whisper_ok = True
        whisper_detail = "faster-whisper ✅"
    except ImportError:
        try:
            import whisper  # noqa
            whisper_ok = True
            whisper_detail = "openai-whisper ✅"
        except ImportError:
            whisper_detail = "غير مثبّت"

    overall = (
        "healthy" if (db_ok and media_ok and supabase_ok) else "degraded"
    )

    components = [
        {
            "name": "قاعدة البيانات",
            "status": "ok" if db_ok else "error",
            "detail": db_detail,
        },
        {
            "name": "تخزين الملفات",
            "status": "ok" if media_ok else "error",
            "detail": (
                str(settings.MEDIA_DIR)
                if media_ok else "المجلد غير موجود"
            ),
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
            "detail": (
                "متاح ✅" if elevenlabs_ok
                else "غير مهيأ (سيستخدم Edge TTS)"
            ),
        },
        {
            "name": "D-ID Talking Head",
            "status": "ok" if did_ok else "degraded",
            "detail": (
                "متاح ✅" if did_ok else "غير مهيأ — أضف DID_API_KEY"
            ),
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
        {
            "label": "Platform",
            "value": platform.system() + " " + platform.release(),
        },
        {"label": "APP_NAME", "value": settings.APP_NAME},
        {"label": "APP_VERSION", "value": settings.APP_VERSION},
        {
            "label": "Supabase",
            "value": "✅ مهيأ" if supabase_ok else "❌ غير مهيأ",
        },
        {
            "label": "Edge TTS",
            "value": "✅ متاح" if edge_ok else "❌ معطّل",
        },
        {"label": "HuggingFace", "value": "✅ متاح"},
        {
            "label": "ElevenLabs",
            "value": "✅ متاح" if elevenlabs_ok else "❌ غير مهيأ",
        },
        {
            "label": "D-ID",
            "value": "✅ متاح" if did_ok else "❌ غير مهيأ",
        },
        {"label": "Whisper", "value": whisper_detail},
        {
            "label": "FFmpeg",
            "value": "✅ متاح" if ffmpeg_ok else "❌ غير مثبّت",
        },
        {"label": "Jobs Storage", "value": JOBS_STORAGE_PREFIX},
    ]

    from datetime import datetime
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
async def models_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from infrastructure.repositories.sql_hf_model_repository import (
        SQLHFModelRepository,
    )
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
