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

from config.settings import settings, ensure_dirs, validate_config
from infrastructure.database.session import create_all_tables
from infrastructure.database.supabase_client import supabase_db
from plugins.registry import PluginRegistry, PluginLoader
from interfaces.api.router import api_router
from interfaces.api.oauth import router as oauth_router
from interfaces.web.routes import router as web_router
from interfaces.websocket.render_ws import router as ws_router

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
    logger.info("Database Type: %s", "Supabase" if settings.using_supabase_db else "PostgreSQL/SQLite")

    # Validate configuration
    try:
        validate_config()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        if settings.is_production:
            raise

    # Ensure required directories exist
    ensure_dirs()

    # ── Database Setup ──────────────────────────────────────────────────────
    if settings.using_supabase_db:
        # استخدام Supabase كقاعدة بيانات
        logger.info("Using Supabase as database")
        try:
            # اختبار الاتصال بـ Supabase
            if settings.supabase_configured:
                # محاولة جلب بيانات للاختبار
                test_result = await supabase_db.get_videos(limit=1)
                logger.info("✅ Supabase connection successful!")
                logger.info(f"Supabase Public Key: {'✅ Configured' if settings.supabase_public_key_value else '❌ Missing'}")
                logger.info(f"Supabase Secret Key: {'✅ Configured' if settings.supabase_secret_key_value else '⚠️ Not set (some operations limited)'}")
            else:
                logger.warning("⚠️ Supabase is not properly configured. Check your environment variables.")
                logger.warning("Required: SUPABASE_URL, SUPABASE_PUBLIC_KEY or SUPABASE_SECRET_KEY")
                
                if settings.is_production:
                    raise RuntimeError("Supabase configuration is required in production!")
        except Exception as e:
            logger.error(f"❌ Supabase connection failed: {e}")
            if settings.is_production:
                raise
            else:
                logger.warning("⚠️ Continuing with limited functionality (development mode)")
    else:
        # استخدام PostgreSQL أو SQLite
        logger.info("Using PostgreSQL/SQLite as database")
        await create_all_tables()
        logger.info("✅ Database tables ready")

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
    try:
        await _seed_initial_data()
    except Exception as e:
        logger.warning(f"⚠️ Failed to seed initial data: {e}")
        # Not critical for startup

    logger.info("🚀 Platform ready at http://%s:%s", settings.HOST, settings.PORT)
    logger.info("📚 API Docs: http://%s:%s/docs", settings.HOST, settings.PORT)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("🛑 Shutting down platform...")
    
    # Cleanup Supabase client if needed
    if hasattr(supabase_db, 'close'):
        await supabase_db.close()


async def _seed_initial_data() -> None:
    """
    Insert default platform records if not present.
    Uses Supabase if configured, otherwise falls back to SQLAlchemy.
    """
    # إذا كان يستخدم Supabase، استخدم Supabase Client
    if settings.using_supabase_db and settings.supabase_configured:
        logger.info("Seeding initial data via Supabase...")
        try:
            # التحقق من وجود البيانات
            response = supabase_db.client.table('publishing_platforms')\
                .select('id')\
                .eq('name', 'youtube')\
                .limit(1)\
                .execute()
            
            if response.data:
                logger.info("✅ Initial data already exists in Supabase")
                return
            
            # إضافة البيانات الأولية
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
            ]
            
            for platform in default_platforms:
                supabase_db.client.table('publishing_platforms').insert(platform).execute()
            
            logger.info(f"✅ Seeded {len(default_platforms)} default platforms in Supabase")
            
        except Exception as e:
            logger.error(f"❌ Failed to seed data in Supabase: {e}")
            raise
        return
    
    # ── Fallback: SQLAlchemy (PostgreSQL/SQLite) ──────────────────────
    try:
        from infrastructure.database.session import get_session_factory
        from infrastructure.database.models.publishing_model import PublishingPlatformModel
        from sqlalchemy import select
        
        factory = get_session_factory()
        async with factory() as session:
            # Check if YouTube platform exists
            q = select(PublishingPlatformModel).where(PublishingPlatformModel.name == "youtube")
            result = await session.execute(q)
            if result.scalar_one_or_none():
                logger.info("✅ Initial data already exists in SQL database")
                return
            
            # Add default platforms
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
            ]
            
            for platform_data in default_platforms:
                platform = PublishingPlatformModel(**platform_data)
                session.add(platform)
            
            await session.commit()
            logger.info(f"✅ Seeded {len(default_platforms)} default platforms in SQL database")
            
    except Exception as e:
        logger.error(f"❌ Failed to seed data in SQL database: {e}")
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

    # ── Health Check ─────────────────────────────────────────────────────
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "supabase" if settings.using_supabase_db else "postgresql/sqlite",
            "supabase_configured": settings.supabase_configured if settings.using_supabase_db else None,
        }

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower() if hasattr(settings, 'LOG_LEVEL') else "info",
    )
