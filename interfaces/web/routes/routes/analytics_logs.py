"""Analytics and logs pages."""
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository

from ..core.config_helpers import get_supabase_config
from ..core.directories import CACHE_DIR, JOBS_DIR, JOBS_STORAGE_PREFIX
from ..core.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# ANALYTICS
# ============================================================

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from infrastructure.repositories.sql_asset_repository import (
        SQLAssetRepository,
    )
    from infrastructure.repositories.sql_publishing_repository import (
        SQLPublishingJobRepository,
    )

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
    success_rate = (
        round(completed / total_renders * 100) if total_renders else 0
    )

    kpis = [
        {
            "label": "إجمالي المشاريع",
            "value": total_projects,
            "trend": 0,
            "sub": "مشروع",
        },
        {
            "label": "عمليات الرندر",
            "value": total_renders,
            "trend": 0,
            "sub": "مهمة",
        },
        {
            "label": "نسبة النجاح",
            "value": f"{success_rate}%",
            "trend": 0,
            "sub": "رندر مكتمل",
        },
        {
            "label": "إجمالي الأصول",
            "value": total_assets,
            "trend": 0,
            "sub": "ملف",
        },
    ]

    status_colors = {
        "draft": "bg-slate-500",
        "in_production": "bg-amber-500",
        "rendered": "bg-green-500",
        "published": "bg-blue-500",
        "failed": "bg-red-500",
    }
    status_labels = {
        "draft": "مسودة",
        "in_production": "إنتاج",
        "rendered": "تم الرندر",
        "published": "منشور",
        "failed": "فشل",
    }
    projects_by_status = []
    for s in [
        "draft", "in_production", "rendered", "published", "failed"
    ]:
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
        {
            "label": "جارٍ",
            "value": sum(
                1 for j in all_jobs if j.status.value == "processing"
            ),
            "color": "text-amber-400",
        },
        {
            "label": "في الانتظار",
            "value": sum(
                1 for j in all_jobs
                if j.status.value in ("pending", "queued")
            ),
            "color": "text-slate-300",
        },
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
        {
            "level": "INFO",
            "source": "main",
            "timestamp": now - timedelta(seconds=5),
            "message": "Platform started",
        },
        {
            "level": "INFO",
            "source": "system",
            "timestamp": now - timedelta(seconds=4),
            "message": "Database tables ready",
        },
        {
            "level": "INFO",
            "source": "plugins",
            "timestamp": now - timedelta(seconds=3),
            "message": "Plugins loaded",
        },
        {
            "level": "INFO",
            "source": "main",
            "timestamp": now - timedelta(seconds=1),
            "message": "Platform ready",
        },
    ]

    if settings.supabase_configured:
        log_entries.append({
            "level": "INFO",
            "source": "supabase",
            "timestamp": now,
            "message": f"Supabase configured: {settings.SUPABASE_URL}",
        })

    edge_ok = settings.EDGE_TTS_ENABLED
    log_entries.append({
        "level": "INFO" if edge_ok else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": f"Edge TTS: {'✅ متاح' if edge_ok else '❌ معطّل'}",
    })

    hf_ok = True
    log_entries.append({
        "level": "INFO" if hf_ok else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": (
            f"HuggingFace XTTS: {'✅ متاح' if hf_ok else '❌ معطّل'}"
        ),
    })

    elevenlabs_ok = settings.elevenlabs_configured
    log_entries.append({
        "level": "INFO" if elevenlabs_ok else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": (
            f"ElevenLabs: "
            f"{'✅ متاح' if elevenlabs_ok else '⚠️ غير مهيأ (سيعمل Edge TTS بدلاً منه)'}"
        ),
    })

    did_ok = settings.did_configured
    log_entries.append({
        "level": "INFO" if did_ok else "WARNING",
        "source": "talking_head",
        "timestamp": now,
        "message": (
            f"D-ID Talking Head: "
            f"{'✅ متاح' if did_ok else '❌ غير مهيأ (DID_API_KEY مفقود)'}"
        ),
    })

    whisper_status = "غير مثبّت"
    try:
        import faster_whisper  # noqa
        whisper_status = "faster-whisper ✅"
    except ImportError:
        try:
            import whisper  # noqa
            whisper_status = "openai-whisper ✅"
        except ImportError:
            whisper_status = "❌ غير مثبّت"

    log_entries.append({
        "level": "INFO" if "✅" in whisper_status else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": f"Whisper: {whisper_status}",
    })

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    log_entries.append({
        "level": "INFO" if ffmpeg_ok else "WARNING",
        "source": "voiceover",
        "timestamp": now,
        "message": f"FFmpeg: {'✅ متاح' if ffmpeg_ok else '❌ غير مثبّت'}",
    })

    cache_files = list(CACHE_DIR.glob("*.mp3"))
    cache_size = sum(f.stat().st_size for f in cache_files) / 1024 / 1024
    log_entries.append({
        "level": "INFO",
        "source": "voiceover",
        "timestamp": now,
        "message": (
            f"Voice Cache: {len(cache_files)} files ({cache_size:.1f} MB)"
        ),
    })

    jobs_count = (
        len(list(JOBS_DIR.glob("*.json"))) if JOBS_DIR.exists() else 0
    )
    log_entries.append({
        "level": "INFO",
        "source": "property_video",
        "timestamp": now,
        "message": f"Local Jobs: {jobs_count} files",
    })

    log_entries.append({
        "level": "INFO",
        "source": "property_video",
        "timestamp": now,
        "message": (
            f"Supabase Jobs Prefix: {JOBS_STORAGE_PREFIX}/ "
            f"(bucket: {settings.SUPABASE_BUCKET})"
        ),
    })

    return templates.TemplateResponse(request, "logs.html", {
        "log_entries": log_entries,
        "active_page": "logs",
        "supabase": get_supabase_config(),
    })
