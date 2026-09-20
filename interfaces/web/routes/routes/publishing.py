"""Publishing pages: render-queue, publishing-queue, platforms, schedules."""
import json
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# RENDER QUEUE
# ============================================================

@router.get("/render-queue", response_class=HTMLResponse)
async def render_queue_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
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
async def publishing_queue_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from infrastructure.repositories.sql_publishing_repository import (
        SQLPublishingJobRepository,
    )
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
async def platforms_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """
    صفحة المنصات المتصلة.

    نبني `accounts_map_json` يحتوي على dict للحقول الجديدة
    (channel_id/title/handle/thumbnail) لتفادي مشكلة
    "Object of type Undefined is not JSON serializable" في Jinja.
    """
    from infrastructure.repositories.sql_publishing_repository import (
        SQLAccountRepository,
    )

    repo = SQLAccountRepository(session)
    accounts = await repo.list_all()

    # ── بناء خريطة JSON آمنة للقالب ────────────────────────────
    accounts_map: Dict[str, Dict[str, Any]] = {}
    for a in accounts:
        accounts_map[str(a.id)] = {
            "id":                str(a.id),
            "name":              getattr(a, "name", "") or "",
            "platform_name":     getattr(a, "platform_name", "") or "",
            "channel_id":        getattr(a, "channel_id", "") or "",
            "channel_title":     getattr(a, "channel_title", "") or "",
            "channel_handle":    getattr(a, "channel_handle", "") or "",
            "channel_thumbnail": getattr(a, "channel_thumbnail", "") or "",
            "is_active":         bool(getattr(a, "is_active", False)),
            "last_verified":     (
                a.last_verified.strftime("%Y-%m-%d %H:%M")
                if getattr(a, "last_verified", None) else ""
            ),
            "created_at":        (
                a.created_at.strftime("%Y-%m-%d")
                if getattr(a, "created_at", None) else ""
            ),
        }

    return templates.TemplateResponse(request, "publishing/platforms.html", {
        "accounts":          accounts,
        "accounts_map_json": json.dumps(accounts_map, ensure_ascii=False),
        "active_page":       "platforms",
        "supabase":          get_supabase_config(),
    })


# ============================================================
# PUBLISHING ACCOUNTS — DELETE (لزر "فصل الحساب")
# ============================================================

@router.delete("/api/v1/publishing/accounts/{account_id}")
async def delete_publishing_account(
    account_id: str,
    session: AsyncSession = Depends(get_db),
):
    """احذف حساب نشر مربوط (فصل الحساب)."""
    from infrastructure.repositories.sql_publishing_repository import (
        SQLAccountRepository,
    )

    repo = SQLAccountRepository(session)
    try:
        ok = await repo.delete(account_id)
    except Exception as e:
        logger.exception("Failed to delete publishing account")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )

    if not ok:
        return JSONResponse(
            {"success": False, "error": "account not found"},
            status_code=404,
        )

    await session.commit()

    return Response(status_code=204)


# ============================================================
# SCHEDULES
# ============================================================

@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from infrastructure.repositories.sql_publishing_repository import (
        SQLPublishingJobRepository,
        SQLAccountRepository,
    )

    pub_repo = SQLPublishingJobRepository(session)
    acc_repo = SQLAccountRepository(session)

    all_jobs = await pub_repo.list_recent(limit=100)
    accounts = await acc_repo.list_all()

    scheduled_jobs = [
        j for j in all_jobs if j.status.value == "scheduled"
    ]
    recent_published = [
        j for j in all_jobs
        if j.status.value in ("completed", "failed")
    ][:20]

    project_repo = SQLProjectRepository(session)
    rendered_projects = await project_repo.list_all(
        limit=50, status="rendered"
    )

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
