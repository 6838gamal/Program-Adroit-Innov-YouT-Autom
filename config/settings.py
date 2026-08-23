from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, SecretStr
from pathlib import Path
from typing import Optional, List
from functools import lru_cache
import os
import warnings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ============================================
    # APPLICATION SETTINGS
    # ============================================
    APP_NAME: str = "Content Production & Publishing Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development, staging, production
    DEBUG: bool = False
    SECRET_KEY: SecretStr = Field(default="change-me-in-production")

    # ============================================
    # SERVER SETTINGS
    # ============================================
    HOST: str = "0.0.0.0"
    PORT: int = 5000
    WORKERS: int = 1

    # ============================================
    # DATABASE TYPE
    # ============================================
    DATABASE_TYPE: str = Field(
        default="supabase",
        description="Database type: supabase, postgres, sqlite"
    )

    # ============================================
    # SUPABASE - المفاتيح الجديدة (Current)
    # ============================================
    
    # 1. SUPABASE_URL: رابط مشروع Supabase
    SUPABASE_URL: Optional[str] = Field(
        default=None,
        description="Supabase project URL (e.g., https://project.supabase.co)"
    )
    
    # 2. SUPABASE_PUBLIC_KEY: المفتاح العام الجديد
    #    يبدأ بـ sb_publishable_...
    #    Dashboard > API Settings > Project API Keys > Publishable Key
    SUPABASE_PUBLIC_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Supabase publishable key (starts with sb_publishable_)"
    )
    
    # 3. SUPABASE_SECRET_KEY: المفتاح السري الجديد
    #    يبدأ بـ sb_secret_...
    #    ⚠️ Dashboard > API Settings > Project API Keys > Secret Key
    SUPABASE_SECRET_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Supabase secret key for server-side (starts with sb_secret_)"
    )
    
    # ============================================
    # SUPABASE - المفاتيح القديمة (Legacy) للتوافق
    # ============================================
    # هذه للتوافق مع الكود القديم - يمكن إزالتها لاحقاً
    SUPABASE_LEGACY_PUBLIC_KEY: Optional[SecretStr] = Field(
        default=None,
        description="[Legacy] Supabase anon key (deprecated, use SUPABASE_PUBLIC_KEY)"
    )
    SUPABASE_LEGACY_SECRET_KEY: Optional[SecretStr] = Field(
        default=None,
        description="[Legacy] Supabase service_role key (deprecated, use SUPABASE_SECRET_KEY)"
    )
    
    # 4. SUPABASE_DB_SCHEMA: مخطط قاعدة البيانات
    SUPABASE_DB_SCHEMA: str = Field(
        default="public",
        description="Supabase database schema"
    )
    
    # 5. SUPABASE_DB_POOL_SIZE: حجم تجمع الاتصالات
    SUPABASE_DB_POOL_SIZE: int = Field(
        default=10,
        description="Supabase connection pool size"
    )
    
    # 6. SUPABASE_STORAGE: نوع التخزين
    SUPABASE_STORAGE: str = Field(
        default="s3",
        description="Supabase storage type"
    )
    
    # 7. SUPABASE_BUCKET: دلاء التخزين
    SUPABASE_BUCKET: str = Field(
        default="videos",
        description="Supabase storage bucket for videos"
    )
    SUPABASE_BUCKET_THUMBNAILS: str = Field(
        default="thumbnails",
        description="Supabase storage bucket for thumbnails"
    )
    SUPABASE_BUCKET_TEMP: str = Field(
        default="temp",
        description="Supabase storage bucket for temporary files"
    )
    SUPABASE_BUCKET_EXPORTS: str = Field(
        default="exports",
        description="Supabase storage bucket for exported files"
    )
    
    @property
    def supabase_database_url(self) -> Optional[str]:
        """Construct Supabase database connection URL using the REST API"""
        if not self.SUPABASE_URL:
            return None
        return f"{self.SUPABASE_URL}/rest/v1"
    
    @property
    def supabase_configured(self) -> bool:
        """Check if Supabase is properly configured with new keys"""
        # التحقق من المفاتيح الجديدة
        has_public_key = bool(
            self.SUPABASE_PUBLIC_KEY and 
            self.SUPABASE_PUBLIC_KEY.get_secret_value() not in [None, "", "your-supabase-public-key"]
        )
        has_secret_key = bool(
            self.SUPABASE_SECRET_KEY and 
            self.SUPABASE_SECRET_KEY.get_secret_value() not in [None, "", "your-supabase-secret-key"]
        )
        
        # التحقق من المفاتيح القديمة كاحتياطي
        has_legacy_public = bool(
            self.SUPABASE_LEGACY_PUBLIC_KEY and 
            self.SUPABASE_LEGACY_PUBLIC_KEY.get_secret_value() not in [None, "", "your-supabase-legacy-public-key"]
        )
        has_legacy_secret = bool(
            self.SUPABASE_LEGACY_SECRET_KEY and 
            self.SUPABASE_LEGACY_SECRET_KEY.get_secret_value() not in [None, "", "your-supabase-legacy-secret-key"]
        )
        
        return bool(
            self.SUPABASE_URL and 
            self.SUPABASE_URL not in [None, "", "https://your-project.supabase.co"] and
            (has_public_key or has_secret_key or has_legacy_public or has_legacy_secret)
        )
    
    @property
    def supabase_public_key_value(self) -> Optional[str]:
        """Get the public key value (prefer new, fallback to legacy)"""
        if self.SUPABASE_PUBLIC_KEY:
            return self.SUPABASE_PUBLIC_KEY.get_secret_value()
        elif self.SUPABASE_LEGACY_PUBLIC_KEY:
            warnings.warn(
                "Using legacy public key. Please migrate to SUPABASE_PUBLIC_KEY.",
                DeprecationWarning
            )
            return self.SUPABASE_LEGACY_PUBLIC_KEY.get_secret_value()
        return None
    
    @property
    def supabase_secret_key_value(self) -> Optional[str]:
        """Get the secret key value (prefer new, fallback to legacy)"""
        if self.SUPABASE_SECRET_KEY:
            return self.SUPABASE_SECRET_KEY.get_secret_value()
        elif self.SUPABASE_LEGACY_SECRET_KEY:
            warnings.warn(
                "Using legacy secret key. Please migrate to SUPABASE_SECRET_KEY.",
                DeprecationWarning
            )
            return self.SUPABASE_LEGACY_SECRET_KEY.get_secret_value()
        return None

    # ============================================
    # POSTGRESQL DATABASE (اختياري - للتطوير المحلي)
    # ============================================
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = Field(default="postgres")
    POSTGRES_DB: str = "video_platform"
    POSTGRES_SSL_MODE: str = "prefer"
    
    @property
    def POSTGRES_URL(self) -> str:
        """Construct PostgreSQL connection URL (for local development)"""
        password = self.POSTGRES_PASSWORD.get_secret_value()
        ssl_param = f"?sslmode={self.POSTGRES_SSL_MODE}" if self.POSTGRES_SSL_MODE else ""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{password}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl_param}"
    
    @property
    def SYNC_POSTGRES_URL(self) -> str:
        """Construct sync PostgreSQL connection URL (for migrations)"""
        password = self.POSTGRES_PASSWORD.get_secret_value()
        ssl_param = f"?sslmode={self.POSTGRES_SSL_MODE}" if self.POSTGRES_SSL_MODE else ""
        return f"postgresql://{self.POSTGRES_USER}:{password}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl_param}"

    # Database Pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DATABASE_ECHO: bool = False

    # ============================================
    # LOCAL STORAGE
    # ============================================
    MEDIA_DIR: Path = BASE_DIR / "media"
    TEMP_DIR: Path = BASE_DIR / "temp"
    EXPORTS_DIR: Path = BASE_DIR / "exports"
    THUMBNAILS_DIR: Path = BASE_DIR / "media" / "thumbnails"
    CACHE_DIR: Path = BASE_DIR / "cache"
    
    STORAGE_TYPE: str = Field(
        default="auto",
        description="Storage type: auto, local, supabase"
    )
    
    # ============================================
    # STORAGE LIMITS
    # ============================================
    MAX_FILE_SIZE: int = 500 * 1024 * 1024  # 500MB
    MAX_THUMBNAIL_SIZE: int = 5 * 1024 * 1024  # 5MB
    ALLOWED_VIDEO_EXTENSIONS: List[str] = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"]
    ALLOWED_IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]

    # ============================================
    # VIDEO PROCESSING
    # ============================================
    VIDEO_PROCESSING_QUEUE: str = "video_processing"
    MAX_CONCURRENT_PROCESSING: int = 3
    PROCESSING_TIMEOUT_SECONDS: int = 3600
    FFMPEG_PATH: str = "ffmpeg"
    FFMPEG_PRESET: str = "medium"
    VIDEO_THUMBNAIL_TIME: float = 5.0

    # ============================================
    # SECURITY
    # ============================================
    CREDENTIALS_ENCRYPTION_KEY: Optional[str] = None
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5000"]
    CORS_ALLOW_CREDENTIALS: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 100

    # ============================================
    # CACHE
    # ============================================
    CACHE_TYPE: str = "simple"
    REDIS_URL: Optional[str] = None
    CACHE_DEFAULT_TTL: int = 300
    CACHE_KEY_PREFIX: str = "video_platform"

    # ============================================
    # SCHEDULER
    # ============================================
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "UTC"

    # ============================================
    # LOGGING
    # ============================================
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[Path] = None
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # ============================================
    # PLUGINS
    # ============================================
    PLUGIN_CONFIG_PATH: Path = BASE_DIR / "config" / "plugin_config.yaml"
    PLUGINS_ENABLED: bool = True

    # ============================================
    # API
    # ============================================
    API_PREFIX: str = "/api/v1"
    API_DOCS_ENABLED: bool = True
    API_RATE_LIMIT_ENABLED: bool = True

    # ============================================
    # PROPERTIES
    # ============================================
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT.lower() == "testing"
    
    @property
    def using_supabase_db(self) -> bool:
        """Check if using Supabase as database"""
        return self.DATABASE_TYPE.lower() == "supabase"

    # ============================================
    # VALIDATORS
    # ============================================
    @field_validator("SECRET_KEY")
    def validate_secret_key(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value() == "change-me-in-production":
            env = os.getenv("ENVIRONMENT", "development")
            if env == "production":
                raise ValueError("SECRET_KEY must be changed in production!")
            else:
                warnings.warn(
                    "Using default SECRET_KEY - change this in production!",
                    UserWarning
                )
        return v

    @field_validator("SUPABASE_URL")
    def validate_supabase_url(cls, v: Optional[str]) -> Optional[str]:
        if v and v == "https://your-project.supabase.co":
            warnings.warn(
                "SUPABASE_URL is set to default value! Please update it.",
                UserWarning
            )
        return v

    @field_validator("SUPABASE_PUBLIC_KEY")
    def validate_supabase_public_key(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        if v and v.get_secret_value() == "your-supabase-public-key":
            warnings.warn(
                "SUPABASE_PUBLIC_KEY is set to default value! Please update it.",
                UserWarning
            )
        return v

    @field_validator("SUPABASE_SECRET_KEY")
    def validate_supabase_secret_key(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        if v and v.get_secret_value() == "your-supabase-secret-key":
            warnings.warn(
                "SUPABASE_SECRET_KEY is set to default value! Please update it.",
                UserWarning
            )
        return v

    @field_validator("MEDIA_DIR", "TEMP_DIR", "EXPORTS_DIR", "THUMBNAILS_DIR", "CACHE_DIR")
    def validate_directories(cls, v: Path) -> Path:
        return v.absolute()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        secrets_dir = "/run/secrets"
        extra = "ignore"


# ============================================
# SINGLETON INSTANCE
# ============================================
@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()


# ============================================
# DIRECTORY CREATION
# ============================================
def ensure_dirs() -> None:
    """Create necessary directories."""
    directories = [
        settings.MEDIA_DIR,
        settings.TEMP_DIR,
        settings.EXPORTS_DIR,
        settings.THUMBNAILS_DIR,
        settings.CACHE_DIR,
        BASE_DIR / "data",
        BASE_DIR / "logs",
        BASE_DIR / "config",
        settings.PLUGIN_CONFIG_PATH.parent,
    ]
    
    for d in directories:
        try:
            d.mkdir(parents=True, exist_ok=True)
            if settings.is_production:
                d.chmod(0o755)
        except PermissionError:
            warnings.warn(f"Cannot create directory: {d}")
        except Exception as e:
            warnings.warn(f"Error creating directory {d}: {e}")


# ============================================
# CONFIGURATION VALIDATION
# ============================================
def validate_config() -> bool:
    """Validate critical configuration settings."""
    try:
        if settings.is_production:
            if settings.SECRET_KEY.get_secret_value() == "change-me-in-production":
                raise ValueError("SECRET_KEY must be changed from default in production!")
            
            if not settings.supabase_configured:
                raise ValueError(
                    "Supabase must be configured for production! "
                    "Set SUPABASE_URL and at least one key (SUPABASE_PUBLIC_KEY or SUPABASE_SECRET_KEY)."
                )
        
        # Validate based on database type
        if settings.using_supabase_db:
            if not settings.supabase_configured:
                raise ValueError(
                    "DATABASE_TYPE is set to 'supabase' but Supabase is not properly configured!"
                )
        
        # Validate video processing settings
        if settings.MAX_CONCURRENT_PROCESSING < 1:
            raise ValueError("MAX_CONCURRENT_PROCESSING must be at least 1")
        
        if settings.MAX_FILE_SIZE <= 0:
            raise ValueError("MAX_FILE_SIZE must be greater than 0")
        
        ensure_dirs()
        return True
        
    except Exception as e:
        if settings.is_production:
            raise
        else:
            warnings.warn(f"Configuration validation warning: {e}")
            return False


# Auto-validation on import (only in production)
if settings.is_production:
    validate_config()
