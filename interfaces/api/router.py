from fastapi import APIRouter
from interfaces.api.v1 import projects, production, assets, publishing, health, models

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(projects.router)
api_router.include_router(production.router)
api_router.include_router(assets.router)
api_router.include_router(publishing.router)
api_router.include_router(health.router)
api_router.include_router(models.router)
