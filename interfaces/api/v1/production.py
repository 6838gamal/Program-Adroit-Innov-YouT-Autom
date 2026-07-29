from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Annotated

from application.services.production_service import ProductionService
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from interfaces.schemas.production_schemas import StartRenderRequest, RenderJobResponse
from shared.exceptions import ProjectNotFoundError, RenderJobNotFoundError

router = APIRouter(prefix="/production", tags=["production"])

# Shared event bus instance (module-level singleton for MVP)
_event_bus = InMemoryEventBus()


def get_production_service(
    session: AsyncSession = Depends(get_db),
) -> ProductionService:
    from interfaces.web.dependencies import get_plugin_registry_from_app
    from fastapi import Request
    # Import registry lazily to avoid circular imports
    from plugins.registry import PluginRegistry, PluginLoader
    from config.settings import settings

    registry = PluginRegistry()
    loader = PluginLoader()
    loader.load_all(settings.PLUGIN_CONFIG_PATH, registry)

    return ProductionService(
        project_repo=SQLProjectRepository(session),
        job_repo=SQLRenderJobRepository(session),
        event_bus=_event_bus,
        plugin_registry=registry,
    )


@router.post("/render", response_model=RenderJobResponse, status_code=202)
async def start_render(
    body: StartRenderRequest,
    service: ProductionService = Depends(get_production_service),
):
    try:
        job = await service.start_render(
            project_id=body.project_id,
            render_settings={
                "fps": body.fps,
                "width": body.width,
                "height": body.height,
                "quality": body.quality,
            },
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RenderJobResponse(**job.to_dict())


@router.get("/jobs", response_model=list[RenderJobResponse])
async def list_render_jobs(
    service: ProductionService = Depends(get_production_service),
):
    jobs = await service.list_jobs()
    return [RenderJobResponse(**j.to_dict()) for j in jobs]


@router.get("/jobs/{job_id}", response_model=RenderJobResponse)
async def get_render_job(
    job_id: UUID,
    service: ProductionService = Depends(get_production_service),
):
    try:
        job = await service.get_job(job_id)
    except RenderJobNotFoundError:
        raise HTTPException(status_code=404, detail="Render job not found")
    return RenderJobResponse(**job.to_dict())
