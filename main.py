"""
Content Production & Publishing Platform
Entry point — FastAPI application factory.
"""
import os  # ✅ تم إضافة الاستيراد
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings, ensure_dirs, validate_config
from infrastructure.database.session import (
    create_all_tables, 
    check_connection, 
    is_database_available,
    get_db_status,
    get_db_error,
    get_session_factory,
    _use_supabase_client
)
from plugins.registry import PluginRegistry, PluginLoader
from interfaces.api.router import api_router
from interfaces.api.oauth import router as oauth_router
from interfaces.web.routes import router as web_router
from interfaces.websocket.render_ws import router as ws_router

from interfaces.api.youtube_routes import router as youtube_router
from interfaces.api.video_routes import router as video_router

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL if hasattr(settings, 'LOG_LEVEL') else logging.INFO,
    format=settings.LOG_FORMAT if hasattr(settings, 'LOG_FORMAT') else "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt=settings.LOG_DATE_FORMAT if hasattr(settings, 'LOG_DATE_FORMAT') else "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment: %s", settings.ENVIRONMENT)
    logger.info("Database Type: Supabase")

    # Validate configuration
    try:
        validate_config()
        logger.info("✅ Configuration validated")
    except Exception as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        if settings.is_production:
            raise

    # Ensure required directories exist
    ensure_dirs()
    logger.info("✅ Directories created")

    # ── Database Setup ──────────────────────────────────────────────────────
    logger.info("Connecting to database...")
    try:
        # إنشاء الجداول
        await create_all_tables()
        
        # التحقق من الاتصال
        if await check_connection():
            logger.info("✅ Database connected successfully!")
        else:
            logger.warning("⚠️ Database connection failed - running in limited mode")
            logger.warning(f"   Error: {get_db_error()}")
            
    except Exception as e:
        logger.warning(f"⚠️ Database setup warning: {e}")
        logger.warning("⚠️ Continuing without database - some features will be unavailable")
    
    # عرض حالة قاعدة البيانات
    status = get_db_status()
    logger.info(f"📊 Database status: Available={status['available']}, Engine Initialized={status['engine_initialized']}")

    # ── Load Plugins ────────────────────────────────────────────────────────
    try:
        registry = PluginRegistry()
        loader = PluginLoader()
        loader.load_all(settings.PLUGIN_CONFIG_PATH, registry)
        app.state.plugin_registry = registry
        logger.info("✅ Plugins loaded: %s", registry.list_all())
    except Exception as e:
        logger.warning(f"⚠️ Failed to load plugins: {e}")

    # ── Seed initial data ──────────────────────────────────────────────────
    if is_database_available():
        try:
            await _seed_initial_data()
        except Exception as e:
            logger.warning(f"⚠️ Failed to seed initial data: {e}")
    else:
        logger.warning("⚠️ Skipping data seeding: Database not available")

    # ── Startup Complete ──────────────────────────────────────────────────
    logger.info("🚀 Platform ready at http://%s:%s", settings.HOST, settings.PORT)
    logger.info("📚 API Docs: http://%s:%s/docs", settings.HOST, settings.PORT)
    
    if not is_database_available():
        logger.warning("⚠️ ════════════════════════════════════════════════════")
        logger.warning("⚠️  RUNNING IN LIMITED MODE - Database is not available")
        logger.warning("⚠️  Some features will not work properly")
        logger.warning("⚠️  Check your database configuration:")
        logger.warning("⚠️    - DATABASE_URL or SUPABASE_URL: %s", "Set" if settings.SUPABASE_URL else "Missing")
        logger.warning("⚠️    - POSTGRES_PASSWORD: %s", "Set" if os.getenv("POSTGRES_PASSWORD") else "Missing")
        logger.warning("⚠️  Error: %s", get_db_error())
        logger.warning("⚠️ ════════════════════════════════════════════════════")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("🛑 Shutting down platform...")


async def _seed_initial_data() -> None:
    """
    Insert default platform records if not present.
    Uses SQLAlchemy directly.
    """
    if not is_database_available():
        logger.warning("⚠️ Skipping data seeding: Database not available")
        return
    
    try:
        from infrastructure.database.models.publishing_model import PublishingPlatformModel
        from sqlalchemy import select
        
        factory = get_session_factory()
        if factory is None:
            logger.warning("⚠️ Cannot get session factory - database not available")
            return
            
        async with factory() as session:
            # التحقق من وجود البيانات
            q = select(PublishingPlatformModel).where(PublishingPlatformModel.name == "youtube")
            result = await session.execute(q)
            if result.scalar_one_or_none():
                logger.info("✅ Initial data already exists")
                return
            
            # إضافة البيانات الافتراضية
            default_platforms = [
                {
                    "name": "youtube",
                    "display_name": "YouTube",
                    "plugin": "youtube",
                    "constraints": {
                        "max_duration": 43200,
                        "max_file_size": 137438953472,
                        "supported_formats": ["mp4", "mov", "avi", "webm"],
                        "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
                    },
                    "is_active": True,
                },
                {
                    "name": "twitter",
                    "display_name": "Twitter/X",
                    "plugin": "twitter",
                    "constraints": {
                        "max_duration": 140,
                        "max_file_size": 512 * 1024 * 1024,
                        "supported_formats": ["mp4", "mov"],
                    },
                    "is_active": True,
                },
                {
                    "name": "facebook",
                    "display_name": "Facebook",
                    "plugin": "facebook",
                    "constraints": {
                        "max_duration": 240,
                        "max_file_size": 10 * 1024 * 1024 * 1024,
                        "supported_formats": ["mp4", "mov", "avi"],
                    },
                    "is_active": True,
                },
                {
                    "name": "instagram",
                    "display_name": "Instagram",
                    "plugin": "instagram",
                    "constraints": {
                        "max_duration": 60,
                        "max_file_size": 100 * 1024 * 1024,
                        "supported_formats": ["mp4", "mov"],
                        "supported_aspect_ratios": ["1:1", "4:5", "16:9"],
                    },
                    "is_active": True,
                },
                {
                    "name": "tiktok",
                    "display_name": "TikTok",
                    "plugin": "tiktok",
                    "constraints": {
                        "max_duration": 180,
                        "max_file_size": 287 * 1024 * 1024,
                        "supported_formats": ["mp4", "mov"],
                        "supported_aspect_ratios": ["9:16", "1:1"],
                    },
                    "is_active": True,
                },
            ]
            
            for platform_data in default_platforms:
                platform = PublishingPlatformModel(**platform_data)
                session.add(platform)
            
            await session.commit()
            logger.info(f"✅ Seeded {len(default_platforms)} default platforms")
            
    except Exception as e:
        logger.error(f"❌ Failed to seed data: {e}")
        raise


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Professional Content Production & Publishing Platform",
        lifespan=lifespan,
        docs_url="/docs" if settings.API_DOCS_ENABLED else None,
        redoc_url="/redoc" if settings.API_DOCS_ENABLED else None,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS if hasattr(settings, 'ALLOWED_ORIGINS') else ["*"],
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS if hasattr(settings, 'CORS_ALLOW_CREDENTIALS') else True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Static Files ──────────────────────────────────────────────────────
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Media Files ───────────────────────────────────────────────────────
    media_dir = settings.MEDIA_DIR
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(ws_router)      # WebSocket: /ws/render/{job_id}
    app.include_router(oauth_router)   # OAuth2:    /oauth/...
    app.include_router(api_router)     # REST API:  /api/v1/...
    app.include_router(web_router)     # Web UI:    /

    # تسجيل الرواترز
    app.include_router(youtube_router, prefix="/api/v1")
    app.include_router(video_router, prefix="/api/v1")

    # ── Health Check ─────────────────────────────────────────────────────
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        status = {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "supabase"
        }
        
        # إضافة حالة قاعدة البيانات
        db_status = get_db_status()
        status["database_status"] = db_status
        
        return status

    # ── Status Endpoint ──────────────────────────────────────────────────
    @app.get("/status")
    async def system_status():
        """System status endpoint with detailed database info."""
        db_info = {
            "available": is_database_available(),
            "error": get_db_error(),
            "using_supabase_client": _use_supabase_client
        }
        
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": db_info,
            "plugins_loaded": hasattr(app.state, 'plugin_registry'),
            "supabase_configured": settings.supabase_configured if hasattr(settings, 'supabase_configured') else False,
            "supabase_url": settings.SUPABASE_URL if hasattr(settings, 'SUPABASE_URL') else None,
        }

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    # استخدام PORT من متغيرات البيئة أو الافتراضي 10000
    port = int(os.getenv("PORT", 10000))
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=port,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower() if hasattr(settings, 'LOG_LEVEL') else "info",
    )
