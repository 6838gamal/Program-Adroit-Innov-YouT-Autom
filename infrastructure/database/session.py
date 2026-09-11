import logging
import os
import re
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from infrastructure.database.base import Base


logger = logging.getLogger(__name__)


# ============================================================
# Global database state
# ============================================================

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None

_db_available: bool = False
_db_error: Optional[str] = None


# ============================================================
# Configuration helpers
# ============================================================

def normalize_database_url(url: str) -> str:
    """
    Normalize PostgreSQL connection URLs for asyncpg.

    Supported:
        postgresql://
        postgres://
        postgresql+asyncpg://

    Supabase / Render DATABASE_URL values can therefore be used
    without manually changing the scheme.
    """

    if not url:
        return url

    url = url.strip()

    if url.startswith("postgresql+asyncpg://"):
        return url

    if url.startswith("postgresql://"):
        return url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    if url.startswith("postgres://"):
        return url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    return url


def get_database_url() -> Optional[str]:
    """
    Get PostgreSQL connection URL.

    Priority:
        1. DATABASE_URL
        2. Build Supabase direct connection from:
           SUPABASE_URL + POSTGRES_PASSWORD
    """

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return normalize_database_url(database_url)

    # --------------------------------------------------------
    # Optional Supabase fallback
    # --------------------------------------------------------

    supabase_url = os.getenv("SUPABASE_URL")
    postgres_password = os.getenv("POSTGRES_PASSWORD")

    if not supabase_url or not postgres_password:
        return None

    # Example:
    # https://abcdefghijklmnop.supabase.co
    match = re.search(
        r"https?://([a-zA-Z0-9-]+)\.supabase\.co",
        supabase_url,
    )

    if not match:
        logger.error("Unable to extract Supabase project reference.")
        return None

    project_ref = match.group(1)

    return (
        f"postgresql+asyncpg://postgres:"
        f"{postgres_password}"
        f"@db.{project_ref}.supabase.co:5432/postgres"
    )


# ============================================================
# Engine
# ============================================================

def get_engine() -> Optional[AsyncEngine]:
    """
    Create and return the SQLAlchemy async engine.

    The engine itself is created lazily.

    IMPORTANT:
    Creating an engine does NOT mean the database is reachable.
    Actual connectivity is verified by check_connection().
    """

    global _engine
    global _db_available
    global _db_error

    if _engine is not None:
        return _engine

    database_url = get_database_url()

    if not database_url:
        _db_available = False
        _db_error = "DATABASE_URL is not configured."

        logger.error(_db_error)

        return None

    try:
        # ----------------------------------------------------
        # Conservative pool configuration for Render + Supabase
        # ----------------------------------------------------

        pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "2"))
        pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "1800"))

        echo = os.getenv("DB_ECHO", "false").lower() == "true"

        _engine = create_async_engine(
            database_url,
            echo=echo,
            future=True,

            # Connection pool
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,

            # Detect stale connections
            pool_pre_ping=True,
        )

        # Do NOT mark database available yet.
        #
        # The actual connection is tested by check_connection().
        _db_available = False
        _db_error = None

        logger.info(
            "PostgreSQL async engine created "
            "(pool_size=%s, max_overflow=%s)",
            pool_size,
            max_overflow,
        )

        return _engine

    except Exception as exc:
        _engine = None
        _db_available = False
        _db_error = str(exc)

        logger.exception(
            "Failed to create PostgreSQL engine."
        )

        return None


# ============================================================
# Session factory
# ============================================================

def get_session_factory() -> Optional[async_sessionmaker[AsyncSession]]:
    """
    Return the global async session factory.

    The factory is created lazily after the engine exists.
    """

    global _session_factory

    if _session_factory is not None:
        return _session_factory

    engine = get_engine()

    if engine is None:
        return None

    _session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,

        # Prevent SQLAlchemy from expiring objects after commit.
        # This is useful for the current domain/repository architecture.
        expire_on_commit=False,

        # Explicit transaction control.
        autoflush=False,
        autocommit=False,
    )

    return _session_factory


# ============================================================
# Database availability
# ============================================================

def is_database_available() -> bool:
    """
    Return whether the database is currently considered available.

    NOTE:
    This is only an in-memory state flag.
    check_connection() performs the real connectivity test.
    """

    return (
        _db_available
        and _engine is not None
    )


def get_database_error() -> Optional[str]:
    """
    Return the last database error without exposing it to clients.
    """

    return _db_error


# ============================================================
# Connection check
# ============================================================

async def check_connection() -> bool:
    """
    Actually test the PostgreSQL connection.

    Executes:
        SELECT 1

    Returns:
        True  -> database reachable
        False -> database unavailable
    """

    global _db_available
    global _db_error

    engine = get_engine()

    if engine is None:
        _db_available = False

        if not _db_error:
            _db_error = "Database engine is unavailable."

        return False

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        _db_available = True
        _db_error = None

        logger.info("PostgreSQL connection check succeeded.")

        return True

    except Exception as exc:
        _db_available = False
        _db_error = str(exc)

        logger.exception(
            "PostgreSQL connection check failed."
        )

        return False


# ============================================================
# FastAPI dependency
# ============================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI database dependency.

    Usage:

        session: AsyncSession = Depends(get_db)
    """

    global _db_available
    global _db_error

    # --------------------------------------------------------
    # Make sure the engine exists
    # --------------------------------------------------------

    factory = get_session_factory()

    if factory is None:
        _db_available = False

        raise HTTPException(
            status_code=503,
            detail="Database is currently unavailable.",
        )

    # --------------------------------------------------------
    # Create session
    # --------------------------------------------------------

    async with factory() as session:
        try:
            yield session

            await session.commit()

        except Exception as exc:
            await session.rollback()

            logger.exception(
                "Database session transaction failed: %s",
                type(exc).__name__,
            )

            raise

        finally:
            await session.close()


# ============================================================
# Startup initialization
# ============================================================

async def initialize_database() -> bool:
    """
    Initialize database connectivity.

    Recommended to call this during FastAPI startup/lifespan.

    Returns:
        True if PostgreSQL is reachable.
    """

    global _db_available
    global _db_error

    logger.info("Initializing PostgreSQL connection...")

    engine = get_engine()

    if engine is None:
        _db_available = False
        return False

    connected = await check_connection()

    if connected:
        logger.info("PostgreSQL database is ready.")
        return True

    logger.error(
        "PostgreSQL initialization failed: %s",
        _db_error,
    )

    return False


# ============================================================
# Shutdown
# ============================================================

async def close_database() -> None:
    """
    Dispose the SQLAlchemy engine.

    Should be called during application shutdown.
    """

    global _engine
    global _session_factory
    global _db_available
    global _db_error

    if _engine is not None:
        try:
            await _engine.dispose()

            logger.info(
                "PostgreSQL engine disposed."
            )

        except Exception:
            logger.exception(
                "Error while disposing PostgreSQL engine."
            )

    _engine = None
    _session_factory = None
    _db_available = False
    _db_error = None


# ============================================================
# Database information
# ============================================================

def get_db_info() -> dict:
    """
    Return safe database diagnostic information.

    NEVER returns the password or complete DATABASE_URL.
    """

    database_url = get_database_url()

    if not database_url:
        return {
            "configured": False,
            "available": False,
            "error": _db_error,
        }

    try:
        # Extract only safe connection information.
        if "@" in database_url:
            connection_part = database_url.split("@", 1)[1]
        else:
            connection_part = "unknown"

        host_port_db = connection_part

        if "/" in host_port_db:
            host_port = host_port_db.split("/", 1)[0]
        else:
            host_port = host_port_db

        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
        else:
            host = host_port
            port = None

    except Exception:
        host = "unknown"
        port = None

    return {
        "configured": True,
        "available": is_database_available(),
        "host": host,
        "port": port,
        "error": _db_error,
    }


# ============================================================
# Table helpers
# ============================================================

async def table_exists(table_name: str) -> bool:
    """
    Check whether a PostgreSQL table exists.
    """

    engine = get_engine()

    if engine is None:
        return False

    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = :table_name
                    )
                    """
                ),
                {
                    "table_name": table_name,
                },
            )

            return bool(result.scalar())

    except SQLAlchemyError:
        logger.exception(
            "Failed checking table existence: %s",
            table_name,
        )

        return False


# ============================================================
# Schema migrations (idempotent)
# ============================================================

# قائمة migrations (idempotent — آمنة للتشغيل المتكرر).
# أضف أي تغيير مستقبلي على المخطط هنا.
#
# الصيغة: (اسم_وصفي, جملة_SQL)
#
# ملاحظة: يجب أن تكون كل جملة آمنة للتشغيل المتكرر باستخدام
#         IF NOT EXISTS / IF EXISTS.
_SCHEMA_MIGRATIONS: list[tuple[str, str]] = [
    # ── 2026-09-11: add `data` column to projects ──────────────────────────
    (
        "projects.data",
        "ALTER TABLE projects "
        "ADD COLUMN IF NOT EXISTS data JSONB DEFAULT '{}'::jsonb",
    ),
    (
        "projects.data_backfill",
        "UPDATE projects SET data = '{}'::jsonb WHERE data IS NULL",
    ),
    (
        "projects.status_index",
        "CREATE INDEX IF NOT EXISTS ix_projects_status "
        "ON projects (status)",
    ),

    # ── أضف migrations جديدة هنا ──────────────────────────────────────────
    # (
    #     "table.column",
    #     "ALTER TABLE table ADD COLUMN IF NOT EXISTS column TYPE DEFAULT ...",
    # ),
]


async def _apply_schema_migrations(connection) -> None:
    """
    Apply idempotent schema migrations on an existing connection.

    Uses IF NOT EXISTS / IF EXISTS so it is safe to run on every startup.
    Never raises — logs warnings on failure so the app can still start.
    """
    for name, sql in _SCHEMA_MIGRATIONS:
        try:
            await connection.execute(text(sql))
            logger.info("✅ Migration applied: %s", name)
        except Exception as exc:
            logger.warning(
                "⚠️ Migration skipped/failed (%s): %s",
                name,
                exc,
            )


# ============================================================
# Development / fallback table creation
# ============================================================

async def create_all_tables() -> bool:
    """
    Create all SQLAlchemy tables AND apply idempotent schema migrations.

    IMPORTANT:
    `Base.metadata.create_all` only creates MISSING tables — it does NOT
    add new columns to existing tables. Therefore we explicitly run
    ALTER TABLE ... ADD COLUMN IF NOT EXISTS migrations below.

    This function is retained for development/startup compatibility.
    In production, prefer Alembic migrations.
    """

    engine = get_engine()

    if engine is None:
        logger.error(
            "Cannot create tables: database engine unavailable."
        )

        return False

    try:
        async with engine.begin() as connection:
            # 1) إنشاء الجداول غير الموجودة
            await connection.run_sync(
                Base.metadata.create_all
            )
            logger.info(
                "Database tables created/verified."
            )

            # 2) ✅ تطبيق migrations تلقائية (idempotent)
            await _apply_schema_migrations(connection)

        return True

    except Exception:
        logger.exception(
            "Failed to create database tables."
        )

        return False


# ============================================================
# Database status
# ============================================================

async def get_db_status() -> dict:
    """
    Return detailed but safe database status.
    """

    connected = await check_connection()

    return {
        "available": connected,
        "configured": get_database_url() is not None,
        "error": _db_error,
    }
