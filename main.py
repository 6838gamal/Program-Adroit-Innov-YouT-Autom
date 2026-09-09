"""
Content Production & Publishing Platform
Entry point — FastAPI application factory.
"""
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

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

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL if hasattr(settings, 'LOG_LEVEL') else logging.INFO,
    format=settings.LOG_FORMAT if hasattr(settings, 'LOG_FORMAT') else "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt=settings.LOG_DATE_FORMAT if hasattr(settings, 'LOG_DATE_FORMAT') else "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# SUPABASE STATUS HELPER
# ============================================================

async def get_supabase_status() -> dict:
    """
    Get detailed Supabase connection status.
    Returns status information about Supabase configuration and connectivity.
    """
    status = {
        "configured": False,
        "url": None,
        "public_key": None,
        "secret_key": None,
        "bucket": None,
        "connection": {
            "status": "unknown",
            "message": "",
            "error": None
        },
        "storage": {
            "status": "unknown",
            "message": "",
            "error": None
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Check configuration
    status["configured"] = settings.supabase_configured
    status["url"] = settings.SUPABASE_URL
    status["public_key"] = "✅ موجود" if settings.supabase_public_key_value else "❌ مفقود"
    status["secret_key"] = "✅ موجود" if settings.supabase_secret_key_value else "❌ مفقود"
    status["bucket"] = settings.SUPABASE_BUCKET
    
    if not status["configured"]:
        status["connection"]["status"] = "not_configured"
        status["connection"]["message"] = "Supabase is not configured. Please set SUPABASE_URL, SUPABASE_PUBLIC_KEY, and SUPABASE_SECRET_KEY"
        return status
    
    # Test database connection
    try:
        db_status = get_db_status()
        if db_status.get("available", False):
            status["connection"]["status"] = "connected"
            status["connection"]["message"] = "Database connection successful"
        else:
            status["connection"]["status"] = "error"
            status["connection"]["message"] = "Database connection failed"
            status["connection"]["error"] = get_db_error()
    except Exception as e:
        status["connection"]["status"] = "error"
        status["connection"]["message"] = "Database connection error"
        status["connection"]["error"] = str(e)
    
    # Test storage connection
    try:
        from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter
        storage = SupabaseStorageAdapter()
        
        # Try to list files (with limit 1 to test connection)
        try:
            await storage.list_files(prefix="", limit=1)
            status["storage"]["status"] = "connected"
            status["storage"]["message"] = "Storage connection successful"
        except Exception as e:
            status["storage"]["status"] = "error"
            status["storage"]["message"] = "Storage connection failed"
            status["storage"]["error"] = str(e)
            
    except ImportError as e:
        status["storage"]["status"] = "error"
        status["storage"]["message"] = "Storage adapter not available"
        status["storage"]["error"] = str(e)
    except Exception as e:
        status["storage"]["status"] = "error"
        status["storage"]["message"] = "Storage connection error"
        status["storage"]["error"] = str(e)
    
    return status


# ============================================================
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("🚀 %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("=" * 60)
    logger.info("🌍 Environment: %s", settings.ENVIRONMENT)
    logger.info("📦 Database Type: Supabase (Modern)")
    logger.info("🔧 Storage Type: %s", settings.STORAGE_TYPE)
    
    # ── Validate Configuration ──────────────────────────────────────────────
    try:
        validate_config()
        logger.info("✅ Configuration validated")
    except Exception as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        if settings.is_production:
            raise
    
    # ── Supabase Status ──────────────────────────────────────────────────────
    logger.info("-" * 60)
    logger.info("🔐 SUPABASE STATUS")
    logger.info("-" * 60)
    
    supabase_status = await get_supabase_status()
    
    if supabase_status["configured"]:
        logger.info("✅ Supabase is configured")
        logger.info("   📍 URL: %s", supabase_status["url"])
        logger.info("   🔑 Public Key: %s", supabase_status["public_key"])
        logger.info("   🔐 Secret Key: %s", supabase_status["secret_key"])
        logger.info("   📦 Bucket: %s", supabase_status["bucket"])
        
        # Database status
        db_status = supabase_status["connection"]
        if db_status["status"] == "connected":
            logger.info("   🗄️  Database: ✅ %s", db_status["message"])
        else:
            logger.warning("   🗄️  Database: ❌ %s", db_status["message"])
            if db_status.get("error"):
                logger.warning("      Error: %s", db_status["error"])
        
        # Storage status
        storage_status = supabase_status["storage"]
        if storage_status["status"] == "connected":
            logger.info("   💾 Storage: ✅ %s", storage_status["message"])
        else:
            logger.warning("   💾 Storage: ❌ %s", storage_status["message"])
            if storage_status.get("error"):
                logger.warning("      Error: %s", storage_status["error"])
    else:
        logger.warning("❌ Supabase is NOT configured")
        logger.warning("   Please set:")
        logger.warning("   - SUPABASE_URL")
        logger.warning("   - SUPABASE_PUBLIC_KEY")
        logger.warning("   - SUPABASE_SECRET_KEY")
    
    logger.info("-" * 60)
    
    # ── Ensure Directories ──────────────────────────────────────────────────
    ensure_dirs()
    logger.info("📁 Directories created")
    
    # ── Database Setup ──────────────────────────────────────────────────────
    logger.info("Connecting to database...")
    try:
        await create_all_tables()
        
        if await check_connection():
            logger.info("✅ Database connected successfully!")
        else:
            logger.warning("⚠️ Database connection failed - running in limited mode")
            logger.warning(f"   Error: {get_db_error()}")
            
    except Exception as e:
        logger.warning(f"⚠️ Database setup warning: {e}")
        logger.warning("⚠️ Continuing without database - some features will be unavailable")
    
    # Display database status
    status = get_db_status()
    logger.info("📊 Database status: Available=%s, Engine Initialized=%s", 
                status.get('available', False), 
                status.get('engine_initialized', False))
    
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
    
    # ── Store Supabase Status in App State ──────────────────────────────────
    app.state.supabase_status = supabase_status
    app.state.startup_time = datetime.utcnow()
    
    # ── Startup Complete ──────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("🚀 Platform ready at http://%s:%s", settings.HOST, settings.PORT)
    logger.info("📚 API Docs: http://%s:%s/docs", settings.HOST, settings.PORT)
    logger.info("📊 Supabase Status: %s", "✅ Connected" if supabase_status["configured"] else "❌ Not Configured")
    logger.info("=" * 60)
    
    if not is_database_available():
        logger.warning("⚠️ ════════════════════════════════════════════════════")
        logger.warning("⚠️  RUNNING IN LIMITED MODE - Database is not available")
        logger.warning("⚠️  Some features will not work properly")
        logger.warning("⚠️  Check your database configuration:")
        logger.warning("⚠️    - SUPABASE_URL: %s", "Set" if settings.SUPABASE_URL else "Missing")
        logger.warning("⚠️    - SUPABASE_PUBLIC_KEY: %s", "Set" if settings.supabase_public_key_value else "Missing")
        logger.warning("⚠️    - SUPABASE_SECRET_KEY: %s", "Set" if settings.supabase_secret_key_value else "Missing")
        logger.warning("⚠️  Error: %s", get_db_error())
        logger.warning("⚠️ ════════════════════════════════════════════════════")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("🛑 Shutting down platform...")


# ============================================================
# SEED DATA
# ============================================================

async def _seed_initial_data() -> None:
    """Insert default platform records if not present."""
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
            q = select(PublishingPlatformModel).where(PublishingPlatformModel.name == "youtube")
            result = await session.execute(q)
            if result.scalar_one_or_none():
                logger.info("✅ Initial data already exists")
                return
            
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


# ============================================================
# CREATE APP
# ============================================================

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
    app.include_router(youtube_router, prefix="/api/v1")

    # ── Health Check ─────────────────────────────────────────────────────
    @app.get("/health")
    async def health_check():
        """Health check endpoint with Supabase status."""
        supabase_status = await get_supabase_status()
        
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "supabase",
            "supabase": supabase_status,
            "timestamp": datetime.utcnow().isoformat()
        }

    # ── Supabase Status Endpoint ──────────────────────────────────────────
    @app.get("/api/supabase/status")
    async def supabase_status_endpoint():
        """Detailed Supabase status endpoint."""
        return await get_supabase_status()

    # ── Status Endpoint ──────────────────────────────────────────────────
    @app.get("/status")
    async def system_status():
        """System status endpoint with detailed database info."""
        supabase_status = await get_supabase_status()
        
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
            "supabase": supabase_status,
            "plugins_loaded": hasattr(app.state, 'plugin_registry'),
            "supabase_configured": settings.supabase_configured if hasattr(settings, 'supabase_configured') else False,
            "supabase_url": settings.SUPABASE_URL if hasattr(settings, 'SUPABASE_URL') else None,
            "startup_time": getattr(app.state, 'startup_time', None),
        }

    return app


# ============================================================
# RUN APPLICATION
# ============================================================

# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 10000))
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=port,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower() if hasattr(settings, 'LOG_LEVEL') else "info",
    )
