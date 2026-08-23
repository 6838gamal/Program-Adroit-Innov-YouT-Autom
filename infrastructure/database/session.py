import os
import re
import logging
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData
from sqlalchemy import text  # ✅ استيراد text

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_db_available: bool = False
_db_error: str | None = None
_use_supabase_client: bool = False


def normalize_database_url(url: str) -> str:
    """
    Convert various URL formats to postgresql+asyncpg:// format.
    """
    if not url:
        return url
    
    if url.startswith("https://"):
        url = url.replace("https://", "postgresql+asyncpg://")
        logger.info("✅ Converted HTTPS URL to PostgreSQL asyncpg URL")
        return url
    
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://")
        logger.info("✅ Converted PostgreSQL URL to asyncpg URL")
        return url
    
    if url.startswith("postgresql+asyncpg://"):
        logger.info("✅ URL already in asyncpg format")
        return url
    
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://")
        logger.info("✅ Converted postgres:// URL to asyncpg URL")
        return url
    
    logger.warning(f"⚠️ Unknown URL format: {url[:30]}...")
    return url


def get_database_url() -> str | None:
    """
    Build Supabase PostgreSQL connection URL from environment variables.
    Returns None if not configured.
    """
    direct_url = os.getenv("DATABASE_URL")
    if direct_url:
        return normalize_database_url(direct_url)
    
    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url:
        logger.warning("⚠️ SUPABASE_URL not found")
        return None
    
    try:
        match = re.search(r'https?://([^.]+)\.supabase\.co', supabase_url)
        if not match:
            logger.warning("⚠️ Could not extract project reference from SUPABASE_URL")
            return None
        
        project_ref = match.group(1)
        password = os.getenv("POSTGRES_PASSWORD")
        if not password:
            logger.warning("⚠️ POSTGRES_PASSWORD not set")
            return None
        
        db_url = f"postgresql+asyncpg://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"
        logger.info(f"✅ Built Supabase PostgreSQL URL for project: {project_ref}")
        return db_url
        
    except Exception as e:
        logger.error(f"❌ Failed to build Supabase database URL: {e}")
        return None


def get_engine() -> AsyncEngine | None:
    """Get database engine for Supabase. Returns None if connection fails."""
    global _engine, _db_available, _db_error
    
    if _engine is not None:
        return _engine
    
    try:
        database_url = get_database_url()
        if not database_url:
            logger.warning("⚠️ No database URL configured")
            _db_available = False
            return None
        
        engine_kwargs = {
            "echo": os.getenv("DATABASE_ECHO", "false").lower() == "true",
            "future": True,
            "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
            "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "3600")),
            "pool_pre_ping": True,
        }
        
        logger.info("Creating database engine...")
        _engine = create_async_engine(
            database_url,
            **engine_kwargs
        )
        
        _db_available = True
        _db_error = None
        logger.info("✅ Database engine created successfully!")
        return _engine
        
    except Exception as e:
        _db_error = str(e)
        _db_available = False
        logger.error(f"❌ Failed to create database engine: {e}")
        logger.warning("⚠️ The application will continue in limited mode. Database features will be unavailable.")
        return None


def get_session_factory() -> async_sessionmaker | None:
    """Get async session factory. Returns None if engine is not available."""
    global _session_factory
    
    engine = get_engine()
    if engine is None:
        return None
    
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    
    return _session_factory


async def get_db() -> AsyncSession:
    """
    FastAPI dependency — yields an async DB session.
    Raises HTTPException if database is not available.
    """
    from fastapi import HTTPException
    
    if not is_database_available():
        raise HTTPException(
            status_code=503,
            detail="Database is currently unavailable. Please try again later."
        )
    
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(
            status_code=503,
            detail="Database is currently unavailable. Please try again later."
        )
    
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_all_tables() -> None:
    """Create all tables on startup."""
    engine = get_engine()
    if engine is None:
        logger.warning("⚠️ Skipping table creation: Database engine not available")
        return
    
    try:
        import infrastructure.database.models  # noqa: F401
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ Database tables created/verified successfully!")
        global _db_available
        _db_available = True
        
    except Exception as e:
        global _db_error
        _db_error = str(e)
        _db_available = False
        logger.error(f"❌ Failed to create tables: {e}")
        logger.warning("⚠️ Continuing without database tables - some features will be unavailable")


async def drop_all_tables() -> None:
    """Drop all tables (for testing only)."""
    engine = get_engine()
    if engine is None:
        logger.warning("⚠️ Skipping table drop: Database engine not available")
        return
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("✅ All tables dropped")


async def check_connection() -> bool:
    """Check database connection."""
    global _db_available, _db_error
    
    engine = get_engine()
    if engine is None:
        _db_available = False
        return False
    
    try:
        async with engine.connect() as conn:
            # ✅ استخدام text() بشكل صحيح في SQLAlchemy 2.0
            await conn.execute(text("SELECT 1"))
        _db_available = True
        _db_error = None
        logger.info("✅ Database connection successful!")
        return True
    except Exception as e:
        _db_available = False
        _db_error = str(e)
        logger.error(f"❌ Database connection failed: {e}")
        return False


def is_database_available() -> bool:
    """Check if database is available."""
    return _db_available and _engine is not None


def get_db_error() -> str | None:
    """Get the last database error."""
    return _db_error


async def get_db_info() -> dict:
    """Get database information."""
    engine = get_engine()
    
    info = {
        "type": "supabase",
        "available": is_database_available(),
        "using_supabase_client": _use_supabase_client,
        "error": get_db_error(),
        "tables": []
    }
    
    if not is_database_available() or engine is None:
        return info
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            tables = result.scalars().all()
            info["tables"] = list(tables)
                
    except Exception as e:
        logger.error(f"❌ Failed to get database info: {e}")
        info["error"] = str(e)
    
    return info


async def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    if not is_database_available():
        return False
    
    engine = get_engine()
    if engine is None:
        return False
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :name)"),
                {"name": table_name}
            )
            return result.scalar() or False
    except Exception as e:
        logger.error(f"❌ Failed to check table existence: {e}")
        return False


def get_db_status() -> dict:
    """Get database status without making async calls."""
    return {
        "available": is_database_available(),
        "engine_initialized": _engine is not None,
        "using_supabase_client": _use_supabase_client,
        "error": get_db_error(),
    }
