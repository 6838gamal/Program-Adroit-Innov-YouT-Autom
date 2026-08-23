from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData
from config.settings import settings
import warnings


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
    Get the appropriate database URL based on configuration.
    
    Returns:
        str: Database connection URL
    """
    # إذا كان يستخدم Supabase كقاعدة بيانات رئيسية
    if settings.using_supabase_db:
        # Supabase تستخدم PostgreSQL تحت الغطاء
        # لكننا نفضل استخدام Supabase Client بدلاً من SQLAlchemy
        # نعيد عنوان وهمي مع تحذير
        warnings.warn(
            "Supabase is set as database. SQLAlchemy engine will use in-memory SQLite. "
            "Use supabase_db client for actual database operations.",
            UserWarning
        )
        # في حالة التطوير، استخدم SQLite للاختبار
        if settings.is_development or settings.is_testing:
            return "sqlite+aiosqlite:///:memory:"
        else:
            # في الإنتاج، لا نستخدم SQLAlchemy مع Supabase
            # نعيد عنوان وهمي ولكن لا نستخدمه فعلياً
            return "sqlite+aiosqlite:///./data/supabase_fallback.db"
    
    # استخدام PostgreSQL المباشر
    return settings.POSTGRES_URL


def get_engine() -> AsyncEngine:
    """Get database engine based on configuration."""
    global _engine
    
    if _engine is None:
        database_url = get_database_url()
        
        # إعدادات إضافية للاتصال
        engine_kwargs = {
            "echo": settings.DATABASE_ECHO,
            "future": True,
        }
        
        # إعدادات خاصة بـ PostgreSQL
        if not settings.using_supabase_db and "postgresql" in database_url:
            engine_kwargs.update({
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_timeout": settings.DB_POOL_TIMEOUT,
                "pool_recycle": settings.DB_POOL_RECYCLE,
                "pool_pre_ping": True,  # التحقق من الاتصال قبل الاستخدام
            })
        
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
    
    ملاحظة: إذا كنت تستخدم Supabase، يفضل استخدام SupabaseDBClient بدلاً من هذا.
    """
    # إذا كان يستخدم Supabase، نعطي تحذير
    if settings.using_supabase_db:
        warnings.warn(
            "Using SQLAlchemy session with Supabase is not recommended. "
            "Use supabase_db client instead.",
            UserWarning
        )
    
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
    
    - مع Supabase: يتم إنشاء الجداول عبر SQL Editor أو migrations
    - مع PostgreSQL: يتم إنشاؤها تلقائياً
    """
    # إذا كان يستخدم Supabase، لا نقوم بإنشاء الجداول تلقائياً
    if settings.using_supabase_db:
        warnings.warn(
            "Supabase is used as database. Tables should be created manually "
            "via Supabase SQL Editor or migrations. Skipping automatic creation.",
            UserWarning
        )
        return
    
    # لـ PostgreSQL أو SQLite
    try:
        # استيراد النماذج لضمان تسجيلها
        import infrastructure.database.models  # noqa: F401
        
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("✅ Database tables created/verified successfully!")
        
    except Exception as e:
        print(f"❌ Failed to create tables: {e}")
        raise


async def drop_all_tables() -> None:
    """
    Drop all tables (for testing only).
    """
    if settings.using_supabase_db:
        warnings.warn(
            "Cannot drop tables automatically with Supabase. Use SQL Editor.",
            UserWarning
        )
        return
    
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


# ============================================
# دالة مساعدة للحصول على محرك Supabase
# ============================================

def get_supabase_engine() -> AsyncEngine | None:
    """
    Get a SQLAlchemy engine that connects directly to Supabase PostgreSQL.
    
    ملاحظة: هذا يتطلب معرفة مباشرة بقاعدة البيانات وقد لا يكون متاحاً في جميع خطط Supabase.
    """
    if not settings.using_supabase_db:
        return None
    
    # بعض خطط Supabase توفر اتصالاً مباشراً بقاعدة البيانات
    # يمكنك الحصول على هذه المعلومات من Supabase Dashboard
    # Database Settings > Connection String > URI
    if hasattr(settings, 'SUPABASE_DIRECT_URL') and settings.SUPABASE_DIRECT_URL:
        return create_async_engine(
            settings.SUPABASE_DIRECT_URL,
            echo=settings.DATABASE_ECHO,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
        )
    
    return None


# ============================================
# نموذج لاستخدام Supabase Client مع SQLAlchemy
# ============================================

class SupabaseCompatibleSession:
    """
    Wrapper لتوفير واجهة مشابهة لـ SQLAlchemy مع Supabase.
    هذا يسمح بالتبديل بين SQLAlchemy و Supabase بسهولة.
    """
    
    def __init__(self):
        self._client = None
        self._connected = False
    
    async def __aenter__(self):
        from infrastructure.database.supabase_client import supabase_db
        self._client = supabase_db
        self._connected = True
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._connected = False
        # لا حاجة لإغلاق الاتصال في Supabase
    
    async def execute(self, table: str, operation: str, **kwargs):
        """تنفيذ عملية على Supabase"""
        if not self._connected:
            raise RuntimeError("Session is not connected")
        
        client = self._client.client
        
        if operation == "select":
            return client.table(table).select(**kwargs).execute()
        elif operation == "insert":
            return client.table(table).insert(kwargs.get('data', {})).execute()
        elif operation == "update":
            return client.table(table).update(kwargs.get('data', {})).eq(**kwargs.get('filters', {})).execute()
        elif operation == "delete":
            return client.table(table).delete().eq(**kwargs.get('filters', {})).execute()
        else:
            raise ValueError(f"Unsupported operation: {operation}")
