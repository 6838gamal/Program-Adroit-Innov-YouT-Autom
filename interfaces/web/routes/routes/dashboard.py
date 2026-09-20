"""Dashboard page."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

router = APIRouter()


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
