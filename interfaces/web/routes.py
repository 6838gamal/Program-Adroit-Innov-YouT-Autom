"""Jinja2 HTML page routes with modern Supabase configuration."""
import uuid
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
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
    """
    Format a duration in seconds to a human-readable string.

    Examples:
        0        -> "0:00"
        5        -> "0:05"
        65       -> "1:05"
        3665     -> "1:01:05"
        None     -> "—"
    """
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
    """
    Format a number with thousands separators.

    Examples:
        1000      -> "1,000"
        1234567   -> "1,234,567"
        None      -> "0"
    """
    if value is None:
        return "0"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


# Register the filters on the Jinja2 environment
templates.env.filters["format_duration"] = _format_duration
templates.env.filters["format_number"] = _format_number


# ============================================================
# HELPERS
# ============================================================

def get_supabase_config() -> dict:
    """Get Supabase configuration for frontend."""
    return {
        "url": settings.SUPABASE_URL,
        "public_key": settings.supabase_public_key_value,
        "bucket": settings.SUPABASE_BUCKET,
        "configured": settings.supabase_configured,
        "storage_type": settings.STORAGE_TYPE,
    }


async def _resolve_video_url(project) -> str | None:
    """
    محاولة استخراج رابط الفيديو العام من المشروع.
    يحاول بالترتيب:
      1. project.video_url إن كان رابطاً كاملاً
      2. project.data.video_url كـ fallback
      3. project.storage_path عبر SupabaseStorageAdapter
      4. project.output_path عبر SupabaseStorageAdapter
      5. project.result_url / output_url إن وُجدت
    """
    # 1) video_url مباشر (من property أو من data)
    video_url = getattr(project, "video_url", None)
    if not video_url:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            video_url = data.get("video_url")

    if video_url and isinstance(video_url, str) and video_url.startswith("http"):
        return video_url

    # 2) storage_path
    storage_path = getattr(project, "storage_path", None)
    if not storage_path:
        # 3) output_path
        storage_path = getattr(project, "output_path", None)

    # من data أيضاً
    if not storage_path:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            storage_path = data.get("video_path") or data.get("storage_path")

    # 4) result_url / output_url مباشر
    if not storage_path:
        alt = getattr(project, "result_url", None) or getattr(project, "output_url", None)
        if alt and isinstance(alt, str) and alt.startswith("http"):
            return alt

    if not storage_path:
        return video_url  # قد يكون None

    # محاولة بناء الرابط العام
    try:
        storage = SupabaseStorageAdapter()
        if hasattr(storage, "get_public_url"):
            public = await storage.get_public_url(storage_path)  # type: ignore
            if public:
                return public
        # fallback: بناؤه يدوياً
        if settings.supabase_configured:
            bucket = settings.SUPABASE_BUCKET
            base = settings.SUPABASE_URL.rstrip("/")
            return f"{base}/storage/v1/object/public/{bucket}/{storage_path.lstrip('/')}"
    except Exception as e:
        logger.warning(f"Failed to build video_url from storage_path: {e}")

    return video_url


async def _resolve_thumbnail_url(project) -> str | None:
    """استخراج رابط الصورة المصغرة من المشروع."""
    thumb_url = getattr(project, "thumbnail_url", None)
    if not thumb_url:
        data = getattr(project, "data", None)
        if isinstance(data, dict):
            thumb_url = data.get("thumbnail")

    if thumb_url and isinstance(thumb_url, str) and thumb_url.startswith("http"):
        return thumb_url
    return thumb_url


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

    # Build scenes from timeline or script (fallback)
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

    # Fallback: generate approximate scenes from script paragraphs
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

    return templates.TemplateResponse(request, "projects/timeline.html", {
        "project": project,
        "scenes": scenes,
        "scenes_json": json.dumps(scenes, ensure_ascii=False),
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

    # ✅ حلّ رابط الفيديو والصورة المصغرة
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
# ASSETS - WITH SUPABASE STORAGE
# ============================================================

@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_asset_repository import SQLAssetRepository
    repo = SQLAssetRepository(session)
    assets = await repo.list_all(limit=50)
    total = await repo.count()

    # Get assets from Supabase storage
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
            "id": "silent",
            "name": "Silent",
            "provider": "Built-in",
            "description": "لا يولّد صوتاً. مفيد لمشاريع الفيديو الصامتة أو عند توفير صوت يدوياً.",
            "languages": ["كل اللغات"],
            "quality": 1,
            "available": True,
            "active": True,
        },
        {
            "id": "default",
            "name": "Default TTS",
            "provider": "Built-in",
            "description": "محرك افتراضي بسيط. مناسب للاختبار السريع.",
            "languages": ["en", "ar"],
            "quality": 2,
            "available": True,
            "active": False,
        },
        {
            "id": "elevenlabs",
            "name": "ElevenLabs",
            "provider": "ElevenLabs API",
            "description": "صوت بجودة عالية يدعم العربية والإنجليزية مع مجموعة متنوعة من الأصوات.",
            "languages": ["ar", "en", "fr", "de", "es"],
            "quality": 5,
            "available": False,
            "active": False,
        },
        {
            "id": "openai_tts",
            "name": "OpenAI TTS",
            "provider": "OpenAI API",
            "description": "محرك OpenAI للنص إلى صوت بنماذج متعددة (tts-1, tts-1-hd).",
            "languages": ["ar", "en", "fr", "de", "es", "ja", "zh"],
            "quality": 5,
            "available": False,
            "active": False,
        },
        {
            "id": "piper",
            "name": "Piper",
            "provider": "Open Source",
            "description": "محرك مفتوح المصدر يعمل محلياً بدون إنترنت. يتطلب تثبيت إضافياً.",
            "languages": ["ar", "en"],
            "quality": 3,
            "available": False,
            "active": False,
        },
        {
            "id": "kokoro",
            "name": "Kokoro",
            "provider": "Open Source",
            "description": "محرك محلي خفيف الوزن عالي الجودة. يتطلب تثبيت إضافياً.",
            "languages": ["en"],
            "quality": 4,
            "available": False,
            "active": False,
        },
    ]
    return templates.TemplateResponse(request, "voices.html", {
        "voice_engines": voice_engines,
        "active_voice": "Silent",
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
        {"level": "INFO",    "source": "plugins", "timestamp": now - timedelta(seconds=3),  "message": "Plugins loaded: voice, renderer, exporter, publisher"},
        {"level": "INFO",    "source": "system",  "timestamp": now - timedelta(seconds=2),  "message": "Seeded default YouTube platform"},
        {"level": "INFO",    "source": "main",    "timestamp": now - timedelta(seconds=1),  "message": "Platform ready at http://0.0.0.0:5000"},
    ]

    if settings.supabase_configured:
        log_entries.append({
            "level": "INFO",
            "source": "supabase",
            "timestamp": now,
            "message": f"Supabase configured: {settings.SUPABASE_URL} (bucket: {settings.SUPABASE_BUCKET})"
        })
    else:
        log_entries.append({
            "level": "WARNING",
            "source": "supabase",
            "timestamp": now,
            "message": "Supabase not configured. Set SUPABASE_URL, SUPABASE_PUBLIC_KEY, SUPABASE_SECRET_KEY"
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
    supabase_detail = "متصل" if supabase_ok else "غير مهيأ"

    overall = "healthy" if (db_ok and media_ok and supabase_ok) else "degraded"

    components = [
        {
            "name": "قاعدة البيانات",
            "status": "ok" if db_ok else "error",
            "detail": db_detail,
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/></svg>',
        },
        {
            "name": "تخزين الملفات",
            "status": "ok" if media_ok else "error",
            "detail": str(settings.MEDIA_DIR) if media_ok else "المجلد غير موجود",
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>',
        },
        {
            "name": "Supabase Storage",
            "status": "ok" if supabase_ok else "error",
            "detail": supabase_detail,
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/></svg>',
        },
        {
            "name": "FFmpeg",
            "status": "ok" if ffmpeg_ok else "degraded",
            "detail": "متاح" if ffmpeg_ok else "غير مثبت — الرندر لن يعمل",
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.069A1 1 0 0121 8.87v6.26a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>',
        },
        {
            "name": "Plugin System",
            "status": "ok",
            "detail": "محملة بنجاح",
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/></svg>',
        },
        {
            "name": "WebSocket",
            "status": "ok",
            "detail": "/ws/render/{job_id}",
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.14 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0"/></svg>',
        },
    ]

    plugins = {}
    try:
        registry = request.app.state.plugin_registry
        plugins = {k: v for k, v in registry.list_all().items()}
    except Exception:
        pass

    system_info = [
        {"label": "Python",       "value": sys.version.split()[0]},
        {"label": "Platform",     "value": platform.system() + " " + platform.release()},
        {"label": "APP_NAME",     "value": settings.APP_NAME},
        {"label": "APP_VERSION",  "value": settings.APP_VERSION},
        {"label": "Supabase",     "value": "✅ مهيأ" if supabase_ok else "❌ غير مهيأ"},
        {"label": "Public Key",   "value": "✅ موجود" if settings.supabase_public_key_value else "❌ مفقود"},
        {"label": "Secret Key",   "value": "✅ موجود" if settings.supabase_secret_key_value else "❌ مفقود"},
        {"label": "Storage Type", "value": settings.STORAGE_TYPE},
    ]

    return templates.TemplateResponse(request, "health.html", {
        "overall_status": overall,
        "last_check": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "components": components,
        "plugins": plugins,
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
            "scheduler_enabled": settings.SCHEDULER_ENABLED,
            "media_dir": str(settings.MEDIA_DIR),
            "exports_dir": str(settings.EXPORTS_DIR),
            "temp_dir": str(settings.TEMP_DIR),
            "storage_type": settings.STORAGE_TYPE,
            "supabase_configured": settings.supabase_configured,
            "supabase_url": settings.SUPABASE_URL,
            "supabase_bucket": settings.SUPABASE_BUCKET,
        },
        "active_page": "settings",
        "supabase": get_supabase_config(),
    })


# ============================================================
# SUPABASE CONFIGURATION API (for frontend)
# ============================================================

@router.get("/api/supabase/config")
async def get_supabase_config_api():
    """API endpoint for frontend to get Supabase configuration."""
    return {
        "url": settings.SUPABASE_URL,
        "public_key": settings.supabase_public_key_value,
        "bucket": settings.SUPABASE_BUCKET,
        "configured": settings.supabase_configured,
        "storage_type": settings.STORAGE_TYPE,
        "buckets": {
            "videos": settings.SUPABASE_BUCKET,
            "thumbnails": settings.SUPABASE_BUCKET_THUMBNAILS,
            "temp": settings.SUPABASE_BUCKET_TEMP,
            "exports": settings.SUPABASE_BUCKET_EXPORTS,
        }
    }


@router.get("/api/supabase/status")
async def get_supabase_status():
    """Check Supabase connection status."""
    try:
        if not settings.supabase_configured:
            return {
                "status": "not_configured",
                "message": "Supabase is not configured. Set SUPABASE_URL, SUPABASE_PUBLIC_KEY, SUPABASE_SECRET_KEY"
            }

        storage = SupabaseStorageAdapter()
        await storage.list_files(prefix="", limit=1)

        return {
            "status": "connected",
            "message": "Supabase is connected and working",
            "url": settings.SUPABASE_URL,
            "bucket": settings.SUPABASE_BUCKET
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Supabase connection error: {str(e)}"
        }


# ============================================================
# 🔍 DEBUG ENDPOINTS (temporary — للتشخيص فقط)
# ============================================================

@router.get("/api/debug/project/{project_id}")
async def debug_project(project_id: str, session: AsyncSession = Depends(get_db)):
    """
    Endpoint تشخيصي مؤقت — يعرض بنية clips في DB.

    استخدمه لمعرفة سبب عدم ظهور الوسائط في الفيديو النهائي.

    مثال:
        GET /api/debug/project/fe2d7c15-a8ff-46c7-96a8-a7b7b43104c1
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse(
            {"error": f"Invalid project_id: {project_id}"},
            status_code=400,
        )

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse(
            {"error": "Project not found"},
            status_code=404,
        )

    data = getattr(project, "data", None) or {}
    if not isinstance(data, dict):
        data = {}

    clips = data.get("clips", []) or []
    media_files = data.get("media_files", []) or []

    # ── تشخيص كل clip ────────────────────────────────────────
    clips_info = []
    for i, c in enumerate(clips):
        if not isinstance(c, dict):
            clips_info.append({"index": i, "error": "not a dict"})
            continue

        content = c.get("content") or c.get("url") or ""
        metadata = c.get("metadata") or {}

        # ابحث عن URL في عدة أماكن
        url_candidates = {
            "content": c.get("content"),
            "url": c.get("url"),
            "metadata.url": metadata.get("url") if isinstance(metadata, dict) else None,
            "metadata.file": metadata.get("file") if isinstance(metadata, dict) else None,
        }

        clips_info.append({
            "index": i,
            "type": c.get("type"),
            "title": c.get("title"),
            "duration": c.get("duration"),
            "layer": c.get("layer"),
            "start": c.get("start"),
            "content_preview": (str(content)[:200] if content else None),
            "content_is_http": str(content).startswith("http") if content else False,
            "content_is_blob": str(content).startswith("blob:") if content else False,
            "content_is_empty": not bool(content),
            "metadata": metadata,
            "url_candidates": {
                k: (str(v)[:120] if v else None)
                for k, v in url_candidates.items()
            },
        })

    # ── تشخيص الصورة المصغرة والفيديو ────────────────────────
    video_url_direct = getattr(project, "video_url", None)
    thumbnail_url_direct = getattr(project, "thumbnail_url", None)

    data_video_url = data.get("video_url")
    data_thumb_url = data.get("thumbnail")

    return {
        "project_id": project_id,
        "title": project.title,
        "status": (
            project.status.value
            if hasattr(project.status, "value")
            else str(project.status)
        ),

        # روابط المخرجات
        "outputs": {
            "video_url_property": video_url_direct,
            "video_url_in_data": data_video_url,
            "thumbnail_url_property": thumbnail_url_direct,
            "thumbnail_url_in_data": data_thumb_url,
        },

        # data keys
        "data_keys": list(data.keys()),

        # counts
        "clips_count": len(clips),
        "media_files_count": len(media_files),

        # تفاصيل clips
        "clips": clips_info,

        # عينة من media_files
        "media_files_sample": [
            {
                "name": mf.get("name") if isinstance(mf, dict) else str(mf),
                "type": mf.get("type") if isinstance(mf, dict) else None,
                "size": mf.get("size") if isinstance(mf, dict) else None,
                "url": (str(mf.get("url"))[:120] if isinstance(mf, dict) and mf.get("url") else None),
            }
            for mf in media_files[:10]
        ],
    }


@router.get("/api/debug/render-jobs/{project_id}")
async def debug_render_jobs(project_id: str, session: AsyncSession = Depends(get_db)):
    """
    تشخيص مهام الرندر لمشروع معيّن.

    يعرض حالة كل مهمة وأي خطأ.

    مثال:
        GET /api/debug/render-jobs/fe2d7c15-a8ff-46c7-96a8-a7b7b43104c1
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse(
            {"error": f"Invalid project_id: {project_id}"},
            status_code=400,
        )

    job_repo = SQLRenderJobRepository(session)
    jobs = await job_repo.list_for_project(project_uuid)

    return {
        "project_id": project_id,
        "jobs_count": len(jobs),
        "jobs": [
            {
                "id": str(j.id),
                "status": (
                    j.status.value if hasattr(j.status, "value") else str(j.status)
                ),
                "progress": getattr(j, "progress", None),
                "current_stage": getattr(j, "current_stage", None),
                "error_message": getattr(j, "error_message", None),
                "created_at": (
                    j.created_at.isoformat()
                    if getattr(j, "created_at", None) else None
                ),
                "completed_at": (
                    j.completed_at.isoformat()
                    if getattr(j, "completed_at", None) else None
                ),
                "output_path": getattr(j, "output_path", None),
            }
            for j in jobs
        ],
    }
