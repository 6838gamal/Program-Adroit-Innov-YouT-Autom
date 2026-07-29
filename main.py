"""
Content Production & Publishing Platform
Entry point — FastAPI application factory.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings, ensure_dirs
from infrastructure.database.session import create_all_tables
from plugins.registry import PluginRegistry, PluginLoader
from interfaces.api.router import api_router
from interfaces.api.oauth import router as oauth_router
from interfaces.web.routes import router as web_router
from interfaces.websocket.render_ws import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # Ensure required directories exist
    ensure_dirs()

    # Create DB tables
    await create_all_tables()
    logger.info("Database tables ready")

    # Load plugins
    registry = PluginRegistry()
    loader = PluginLoader()
    loader.load_all(settings.PLUGIN_CONFIG_PATH, registry)
    app.state.plugin_registry = registry
    logger.info("Plugins loaded: %s", registry.list_all())

    # Seed built-in data
    await _seed_initial_data()

    logger.info("Platform ready at http://%s:%s", settings.HOST, settings.PORT)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down platform")


async def _seed_initial_data() -> None:
    """Insert default platform records if not present."""
    from infrastructure.database.session import get_session_factory
    from infrastructure.database.models.publishing_model import PublishingPlatformModel
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        q = select(PublishingPlatformModel).where(PublishingPlatformModel.name == "youtube")
        result = await session.execute(q)
        if not result.scalar_one_or_none():
            session.add(PublishingPlatformModel(
                name="youtube",
                display_name="YouTube",
                plugin="youtube",
                constraints={
                    "max_duration": 43200,
                    "max_file_size": 137438953472,
                    "supported_formats": ["mp4", "mov", "avi", "webm"],
                    "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
                },
                is_active=True,
            ))
            await session.commit()
            logger.info("Seeded default YouTube platform")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Professional Content Production & Publishing Platform",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Media files
    media_dir = settings.MEDIA_DIR
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    # Routers
    app.include_router(ws_router)      # WebSocket: /ws/render/{job_id}
    app.include_router(api_router)     # REST API:  /api/v1/...
    app.include_router(web_router)     # Web UI:    /

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        log_level="info",
    )
