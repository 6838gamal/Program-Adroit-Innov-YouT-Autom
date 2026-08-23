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
    # POSTGRESQL DATABASE (المفتاح الأول)
    # ============================================
    # POSTGRES_URL: رابط اتصال PostgreSQL الكامل
    POSTGRES_URL: str = Field(
        default=f"postgresql+asyncpg://postgres:postgres@localhost:5432/video_platform",
        description="PostgreSQL connection URL (async)"
    )
    
    # POSTGRES_SYNC_URL: رابط اتصال PostgreSQL للتحديثات (Synchronous)
    POSTGRES_SYNC_URL: str = Field(
        default=f"postgresql://postgres:postgres@localhost:5432/video_platform",
        description="PostgreSQL connection URL (sync for migrations)"
    )
    
    # إعدادات PostgreSQL الإضافية (إذا أردت بناء الرابط يدوياً)
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = Field(default="postgres")
    POSTGRES_DB: str = "video_platform"
    POSTGRES_SSL_MODE: str = "prefer"  # disable, allow, prefer, require, verify-ca, verify-full
    
    @property
    def DATABASE_URL(self) -> str:
        """Get async PostgreSQL connection URL"""
        return self.POSTGRES_URL
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Get sync PostgreSQL connection URL for migrations"""
        return self.POSTGRES_SYNC_URL

    # Database Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DATABASE_ECHO: bool = False

    # ============================================
    # SUPABASE STORAGE (المفاتيح المهمة)
    # ============================================
    
    # 1. SUPABASE_URL: رابط مشروع Supabase
    SUPABASE_URL: Optional[str] = Field(
        default=None,
        description="Supabase project URL (e.g., https://project.supabase.co)"
    )
    
    # 2. SUPABASE_PUBLIC_KEY: المفتاح العام (للعمليات من العميل)
    SUPABASE_PUBLIC_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Supabase public/anonymous key for client-side operations"
    )
    
    # 3. SUPABASE_SECRET_KEY: المفتاح السري (للعمليات من الخادم)
    SUPABASE_SECRET_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Supabase secret/service role key for server-side admin operations"
    )
    
    # 4. SUPABASE_STORAGE: نوع التخزين في Supabase
    SUPABASE_STORAGE: str = Field(
        default="s3",  # s3, gcs, azure
        description="Supabase storage type (s3, gcs, azure)"
    )
    
    # 5. SUPABASE_BUCKET: اسم دلو التخزين الرئيسي
    SUPABASE_BUCKET: str = Field(
        default="videos",
        description="Supabase storage bucket name for videos"
    )
    
    # دلاء إضافية
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
    
    # ============================================
    # SUPABASE PROPERTIES (للاستخدام الداخلي)
    # ============================================
    
    @property
    def supabase_configured(self) -> bool:
        """Check if Supabase is properly configured"""
        has_public_key = bool(
            self.SUPABASE_PUBLIC_KEY and 
            self.SUPABASE_PUBLIC_KEY.get_secret_value() not in [None, "", "your-supabase-public-key"]
        )
        has_secret_key = bool(
            self.SUPABASE_SECRET_KEY and 
            self.SUPABASE_SECRET_KEY.get_secret_value() not in [None, "", "your-supabase-secret-key"]
        )
        
        return bool(
            self.SUPABASE_URL and 
            self.SUPABASE_URL not in [None, "", "https://your-project.supabase.co"] and
            (has_public_key or has_secret_key)
        )
    
    @property
    def supabase_public_key_value(self) -> Optional[str]:
        """Get the public key value"""
        if self.SUPABASE_PUBLIC_KEY:
            return self.SUPABASE_PUBLIC_KEY.get_secret_value()
        return None
    
    @property
    def supabase_secret_key_value(self) -> Optional[str]:
        """Get the secret key value"""
        if self.SUPABASE_SECRET_KEY:
            return self.SUPABASE_SECRET_KEY.get_secret_value()
        return None

    # ============================================
    # LOCAL STORAGE (للتخزين المحلي)
    # ============================================
    MEDIA_DIR: Path = BASE_DIR / "media"
    TEMP_DIR: Path = BASE_DIR / "temp"
    EXPORTS_DIR: Path = BASE_DIR / "exports"
    THUMBNAILS_DIR: Path = BASE_DIR / "media" / "thumbnails"
    CACHE_DIR: Path = BASE_DIR / "cache"
    
    # نوع التخزين الأساسي (auto, local, supabase)
    STORAGE_TYPE: str = Field(
        default="auto",
        description="Storage type: auto (uses Supabase if configured), local, or supabase"
    )
    
    # ============================================
    # STORAGE LIMITS & VALIDATION
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
    PROCESSING_TIMEOUT_SECONDS: int = 3600  # 1 hour
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
    # CACHE (Redis optional)
    # ============================================
    CACHE_TYPE: str = "simple"  # simple, redis
    REDIS_URL: Optional[str] = None
    CACHE_DEFAULT_TTL: int = 300  # 5 minutes
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

    @field_validator("POSTGRES_PASSWORD")
    def validate_postgres_password(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value() == "postgres":
            env = os.getenv("ENVIRONMENT", "development")
            if env == "production":
                raise ValueError("POSTGRES_PASSWORD must be changed in production!")
            else:
                warnings.warn(
                    "Using default PostgreSQL password is not secure!",
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
        # Check critical production settings
        if settings.is_production:
            # Secret key must be changed
            if settings.SECRET_KEY.get_secret_value() == "change-me-in-production":
                raise ValueError("SECRET_KEY must be changed from default in production!")
            
            # Database password must be changed
            if settings.POSTGRES_PASSWORD.get_secret_value() == "postgres":
                raise ValueError("POSTGRES_PASSWORD must be changed from default in production!")
            
            # Supabase must be configured in production
            if not settings.supabase_configured:
                raise ValueError(
                    "Supabase must be configured for production! "
                    "Set SUPABASE_URL and at least one key (SUPABASE_PUBLIC_KEY or SUPABASE_SECRET_KEY)."
                )
            
            # Secret key is required for admin operations in production
            if not settings.SUPABASE_SECRET_KEY:
                warnings.warn(
                    "SUPABASE_SECRET_KEY is not set. Some admin operations may be limited.",
                    UserWarning
                )
        
        # Validate PostgreSQL connection parameters
        if not all([
            settings.POSTGRES_HOST,
            settings.POSTGRES_USER,
            settings.POSTGRES_DB,
        ]):
            raise ValueError("All PostgreSQL connection parameters must be configured!")
        
        # Validate Supabase if it's the selected storage type
        if settings.STORAGE_TYPE in ["supabase", "auto"]:
            if not settings.supabase_configured:
                if settings.STORAGE_TYPE == "supabase":
                    raise ValueError(
                        "Supabase is selected as storage type but not properly configured!"
                    )
                else:
                    warnings.warn(
                        "Supabase not configured, falling back to local storage",
                        UserWarning
                    )
        
        # Validate video processing settings
        if settings.MAX_CONCURRENT_PROCESSING < 1:
            raise ValueError("MAX_CONCURRENT_PROCESSING must be at least 1")
        
        if settings.MAX_FILE_SIZE <= 0:
            raise ValueError("MAX_FILE_SIZE must be greater than 0")
        
        # Ensure directories exist
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
