from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData
from config.settings import settings
import re
import logging

logger = logging.getLogger(__name__)


# تعريف قاعدة البيانات مع تسمية توافقية
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


def get_database_url() -> str:
    """
    Build Supabase PostgreSQL connection URL from settings.
    """
    if not settings.SUPABASE_URL:
        raise ValueError("SUPABASE_URL is required but not configured!")
    
    try:
        # استخراج project_ref من SUPABASE_URL
        # مثال: https://nyotevucyflkqaqkutjn.supabase.co
        match = re.search(r'https?://([^.]+)\.supabase\.co', settings.SUPABASE_URL)
        if not match:
            raise ValueError(f"Invalid SUPABASE_URL format: {settings.SUPABASE_URL}")
        
        project_ref = match.group(1)
        
        # استخدام POSTGRES_PASSWORD من الإعدادات
        password = settings.POSTGRES_PASSWORD.get_secret_value()
        if not password or password == "postgres":
            logger.warning("⚠️ POSTGRES_PASSWORD is using default value. Please set a secure password in production!")
        
        db_url = f"postgresql+asyncpg://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"
        logger.info(f"✅ Built Supabase PostgreSQL URL for project: {project_ref}")
        return db_url
        
    except Exception as e:
        logger.error(f"❌ Failed to build Supabase database URL: {e}")
        raise


def get_engine() -> AsyncEngine:
    """Get database engine for Supabase."""
    global _engine
    
    if _engine is None:
        database_url = get_database_url()
        
        # إعدادات الاتصال
        engine_kwargs = {
            "echo": settings.DATABASE_ECHO,
            "future": True,
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW if hasattr(settings, 'DB_MAX_OVERFLOW') else 20,
            "pool_timeout": settings.DB_POOL_TIMEOUT if hasattr(settings, 'DB_POOL_TIMEOUT') else 30,
            "pool_recycle": settings.DB_POOL_RECYCLE if hasattr(settings, 'DB_POOL_RECYCLE') else 3600,
            "pool_pre_ping": True,
        }
        
        logger.info("Creating Supabase database engine...")
        _engine = create_async_engine(
            database_url,
            **engine_kwargs
        )
    
    return _engine


def get_session_factory() -> async_sessionmaker:
    """Get async session factory."""
    global _session_factory
    
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    
    return _session_factory


async def get_db() -> AsyncSession:
    """
    FastAPI dependency — yields an async DB session.
    """
    factory = get_session_factory()
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
    """
    Create all tables on startup.
    """
    try:
        # استيراد النماذج لضمان تسجيلها
        import infrastructure.database.models  # noqa: F401
        
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ Database tables created/verified successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to create tables: {e}")
        raise


async def drop_all_tables() -> None:
    """
    Drop all tables (for testing only).
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("✅ All tables dropped")


async def check_connection() -> bool:
    """
    Check database connection.
    
    Returns:
        bool: True if connected successfully
    """
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        logger.info("✅ Supabase connection successful!")
        return True
    except Exception as e:
        logger.error(f"❌ Supabase connection failed: {e}")
        return False


async def get_db_info() -> dict:
    """
    Get database information.
    
    Returns:
        dict: Database information
    """
    info = {
        "type": "supabase",
        "connected": False,
        "tables": []
    }
    
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            # اختبار الاتصال
            await conn.execute("SELECT 1")
            info["connected"] = True
            
            # جلب أسماء الجداول
            result = await conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            tables = result.scalars().all()
            info["tables"] = list(tables)
                
    except Exception as e:
        logger.error(f"❌ Failed to get database info: {e}")
    
    return info


async def table_exists(table_name: str) -> bool:
    """
    Check if a table exists in the database.
    
    Args:
        table_name: Name of the table to check
        
    Returns:
        bool: True if table exists
    """
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :name)",
                {"name": table_name}
            )
            return result.scalar() or False
    except Exception as e:
        logger.error(f"❌ Failed to check table existence: {e}")
        return False
