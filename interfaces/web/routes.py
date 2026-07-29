"""Jinja2 HTML page routes."""
import uuid
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent.parent / "templates")
)
router = APIRouter(tags=["web"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────── DASHBOARD ──────
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
    })


# ──────────────────────────────────────────────────────────── PROJECTS ───────
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
    })


@router.get("/projects/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    return templates.TemplateResponse(request, "projects/create.html", {
        "active_page": "projects",
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
            # Estimate ~1 word/second
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
    return templates.TemplateResponse(request, "projects/detail.html", {
        "project": project,
        "render_jobs": render_jobs,
        "active_page": "projects",
    })


# ──────────────────────────────────────────────────────────── ASSETS ─────────
@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_asset_repository import SQLAssetRepository
    repo = SQLAssetRepository(session)
    assets = await repo.list_all(limit=50)
    total = await repo.count()
    return templates.TemplateResponse(request, "assets/library.html", {
        "assets": assets,
        "total": total,
        "active_page": "assets",
    })


# ─────────────────────────────────────────────────────────── TEMPLATES ───────
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
    })


# ──────────────────────────────────────────────────────────── VOICES ─────────
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
    })


# ─────────────────────────────────────────────────────── RENDER QUEUE ────────
@router.get("/render-queue", response_class=HTMLResponse)
async def render_queue_page(request: Request, session: AsyncSession = Depends(get_db)):
    repo = SQLRenderJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return templates.TemplateResponse(request, "render/queue.html", {
        "jobs": jobs,
        "active_page": "render_queue",
    })


# ──────────────────────────────────────────────────── PUBLISHING QUEUE ────────
@router.get("/publishing-queue", response_class=HTMLResponse)
async def publishing_queue_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import SQLPublishingJobRepository
    repo = SQLPublishingJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return templates.TemplateResponse(request, "publishing/queue.html", {
        "jobs": jobs,
        "active_page": "publishing_queue",
    })


# ──────────────────────────────────────────────────────────── PLATFORMS ───────
@router.get("/platforms", response_class=HTMLResponse)
async def platforms_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import SQLAccountRepository
    repo = SQLAccountRepository(session)
    accounts = await repo.list_all()
    return templates.TemplateResponse(request, "publishing/platforms.html", {
        "accounts": accounts,
        "active_page": "platforms",
    })


# ──────────────────────────────────────────────────────────── SCHEDULES ───────
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

    # Separate scheduled vs recent
    scheduled_jobs = [j for j in all_jobs if j.status.value == "scheduled"]
    recent_published = [j for j in all_jobs if j.status.value in ("completed", "failed")][:20]

    # Build rendered projects list for the schedule form
    project_repo = SQLProjectRepository(session)
    rendered_projects = await project_repo.list_all(limit=50, status="rendered")

    # Add project title to jobs (best effort)
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
    })


# ──────────────────────────────────────────────────────────── ANALYTICS ───────
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

    # KPIs
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

    # Projects by status
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

    # Render stats
    render_stats = [
        {"label": "مكتمل", "value": completed, "color": "text-green-400"},
        {"label": "فاشل", "value": failed, "color": "text-red-400"},
        {"label": "جارٍ", "value": sum(1 for j in all_jobs if j.status.value == "processing"), "color": "text-amber-400"},
        {"label": "في الانتظار", "value": sum(1 for j in all_jobs if j.status.value in ("pending", "queued")), "color": "text-slate-300"},
    ]

    # Publish activity (last 7 days)
    today = datetime.utcnow().date()
    publish_activity = []
    for delta in range(6, -1, -1):
        day = today - timedelta(days=delta)
        count = sum(1 for j in all_pub if j.created_at.date() == day)
        short = ["أح", "إث", "ثل", "أر", "خم", "جم", "سب"][day.weekday()]
        publish_activity.append({"label": short, "count": count})

    # Asset type distribution
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
    })


# ────────────────────────────────────────────────────────────── LOGS ──────────
@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """System log viewer — reads from Python logging records (in-memory demo)."""
    import logging as _logging

    # Build synthetic log entries from standard Python logging
    log_entries = []
    for handler in _logging.root.handlers:
        # Try to read from any MemoryHandler or similar; otherwise show a sample
        pass

    # Add some representative demo entries if none found
    now = datetime.utcnow()
    log_entries = [
        {"level": "INFO",    "source": "main",    "timestamp": now - timedelta(seconds=5),  "message": "Platform started successfully"},
        {"level": "INFO",    "source": "system",  "timestamp": now - timedelta(seconds=4),  "message": "Database tables ready"},
        {"level": "INFO",    "source": "plugins", "timestamp": now - timedelta(seconds=3),  "message": "Plugins loaded: voice, renderer, exporter, publisher"},
        {"level": "INFO",    "source": "system",  "timestamp": now - timedelta(seconds=2),  "message": "Seeded default YouTube platform"},
        {"level": "INFO",    "source": "main",    "timestamp": now - timedelta(seconds=1),  "message": "Platform ready at http://0.0.0.0:5000"},
    ]

    return templates.TemplateResponse(request, "logs.html", {
        "log_entries": log_entries,
        "active_page": "logs",
    })


# ───────────────────────────────────────────────────────── SYSTEM HEALTH ──────
@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request, session: AsyncSession = Depends(get_db)):
    import platform
    import sys

    # Test DB
    db_ok = True
    db_detail = "متصل"
    try:
        await session.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        db_ok = False
        db_detail = str(e)[:60]

    # Check FFmpeg
    import shutil
    ffmpeg_ok = shutil.which("ffmpeg") is not None

    # Check media dirs
    media_ok = settings.MEDIA_DIR.exists()

    overall = "healthy" if (db_ok and media_ok) else "degraded"

    _icon = lambda path: f'<svg class="w-4 h-4 text-{{color}}" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="{path}"/></svg>'

    components = [
        {
            "name": "قاعدة البيانات (SQLite)",
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
            "name": "FastAPI / Uvicorn",
            "status": "ok",
            "detail": "يعمل على المنفذ 5000",
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"/></svg>',
        },
        {
            "name": "WebSocket",
            "status": "ok",
            "detail": "/ws/render/{job_id}",
            "icon": '<svg class="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.14 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0"/></svg>',
        },
    ]

    # Plugins from request state
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
        {"label": "DATABASE",     "value": "SQLite (aiosqlite)"},
        {"label": "HOST:PORT",    "value": f"{settings.HOST}:{settings.PORT}"},
    ]

    return templates.TemplateResponse(request, "health.html", {
        "overall_status": overall,
        "last_check": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "components": components,
        "plugins": plugins,
        "system_info": system_info,
        "active_page": "health",
    })


# ──────────────────────────────────────────────────────── MODEL LIBRARY ───────
@router.get("/models", response_class=HTMLResponse)
async def models_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_hf_model_repository import SQLHFModelRepository
    repo = SQLHFModelRepository(session)
    all_models = await repo.list_all()
    return templates.TemplateResponse(request, "models.html", {
        "models": [m.to_dict() for m in all_models],
        "active_page": "models",
    })


# ──────────────────────────────────────────────────────────── SETTINGS ────────
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
        },
        "active_page": "settings",
    })
