"""Jinja2 HTML page routes."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent.parent / "templates"))
router = APIRouter(tags=["web"])


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


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    project_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    import uuid
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


@router.get("/render-queue", response_class=HTMLResponse)
async def render_queue_page(request: Request, session: AsyncSession = Depends(get_db)):
    repo = SQLRenderJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return templates.TemplateResponse(request, "render/queue.html", {
        "jobs": jobs,
        "active_page": "render_queue",
    })


@router.get("/publishing-queue", response_class=HTMLResponse)
async def publishing_queue_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import SQLPublishingJobRepository
    repo = SQLPublishingJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return templates.TemplateResponse(request, "publishing/queue.html", {
        "jobs": jobs,
        "active_page": "publishing_queue",
    })


@router.get("/platforms", response_class=HTMLResponse)
async def platforms_page(request: Request, session: AsyncSession = Depends(get_db)):
    from infrastructure.repositories.sql_publishing_repository import SQLAccountRepository
    repo = SQLAccountRepository(session)
    accounts = await repo.list_all()
    return templates.TemplateResponse(request, "publishing/platforms.html", {
        "accounts": accounts,
        "active_page": "platforms",
    })
