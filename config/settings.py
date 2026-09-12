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
    # SUPABASE - MODERN CONFIGURATION
    # ============================================
    SUPABASE_URL: Optional[str] = Field(
        default=None,
        description="Supabase project URL (e.g., https://project.supabase.co)"
    )

    SUPABASE_DIRECT_URL: Optional[str] = Field(
        default=None,
        description="Direct PostgreSQL connection URL for Supabase"
    )

    SUPABASE_PUBLIC_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Supabase public key (starts with sb_publishable_ or eyJh)"
    )

    SUPABASE_SECRET_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Supabase secret key for server-side (starts with sb_secret_ or eyJh)"
    )

    SUPABASE_DB_SCHEMA: str = Field(
        default="public",
        description="Supabase database schema"
    )

    SUPABASE_DB_POOL_SIZE: int = Field(
        default=10,
        description="Supabase connection pool size"
    )

    SUPABASE_STORAGE: str = Field(
        default="s3",
        description="Supabase storage type"
    )

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
        if not self.SUPABASE_URL:
            return None
        return f"{self.SUPABASE_URL}/rest/v1"

    @property
    def supabase_configured(self) -> bool:
        has_url = bool(
            self.SUPABASE_URL and
            self.SUPABASE_URL not in [None, "", "https://your-project.supabase.co"]
        )

        has_direct_url = bool(
            self.SUPABASE_DIRECT_URL and
            self.SUPABASE_DIRECT_URL not in [None, "", "postgresql://postgres:password@db.project.supabase.co:5432/postgres"]
        )

        public_key_value = self.SUPABASE_PUBLIC_KEY.get_secret_value() if self.SUPABASE_PUBLIC_KEY else None
        has_public_key = bool(
            public_key_value and
            public_key_value not in [None, "", "your-supabase-public-key", "your-supabase-anon-key"]
        )

        secret_key_value = self.SUPABASE_SECRET_KEY.get_secret_value() if self.SUPABASE_SECRET_KEY else None
        has_secret_key = bool(
            secret_key_value and
            secret_key_value not in [None, "", "your-supabase-secret-key", "your-supabase-service-role-key"]
        )

        return (has_url or has_direct_url) and (has_public_key or has_secret_key)

    @property
    def supabase_public_key_value(self) -> Optional[str]:
        if self.SUPABASE_PUBLIC_KEY:
            return self.SUPABASE_PUBLIC_KEY.get_secret_value()
        return None

    @property
    def supabase_secret_key_value(self) -> Optional[str]:
        if self.SUPABASE_SECRET_KEY:
            return self.SUPABASE_SECRET_KEY.get_secret_value()
        return None

    # ============================================
    # 🎙️ VOICE CLONING — Multi-Provider Configuration
    # ============================================

    # ── المزوّد الافتراضي ──
    VOICE_CLONING_PROVIDER: str = Field(
        default="huggingface",
        description="Default voice cloning provider: huggingface | elevenlabs | edge_tts"
    )

    # ── 🔊 Edge TTS (مجاني 100% — بدون API key) ──
    EDGE_TTS_ENABLED: bool = Field(
        default=True,
        description="Enable Edge TTS (Microsoft — free, high quality)"
    )
    EDGE_TTS_MAX_CHARS: int = Field(
        default=10000,
        description="Max characters per Edge TTS request"
    )
    EDGE_TTS_DEFAULT_VOICE: str = Field(
        default="ar-SA-HamedNeural",
        description="Default Edge TTS voice"
    )
    EDGE_TTS_TIMEOUT: int = Field(
        default=60,
        description="Edge TTS request timeout (seconds)"
    )

    # أصوات Edge TTS العربية (مُضمَّنة)
    EDGE_TTS_ARABIC_VOICES: List[dict] = [
        {"id": "ar-SA-HamedNeural", "name": "حامد (سعودي)", "lang": "ar-SA", "gender": "male"},
        {"id": "ar-SA-ZariyahNeural", "name": "زارية (سعودية)", "lang": "ar-SA", "gender": "female"},
        {"id": "ar-EG-ShakirNeural", "name": "شاكر (مصري)", "lang": "ar-EG", "gender": "male"},
        {"id": "ar-EG-SalmaNeural", "name": "سلمى (مصرية)", "lang": "ar-EG", "gender": "female"},
        {"id": "ar-AE-HamdanNeural", "name": "حمدان (إماراتي)", "lang": "ar-AE", "gender": "male"},
        {"id": "ar-AE-FatimaNeural", "name": "فاطمة (إماراتية)", "lang": "ar-AE", "gender": "female"},
        {"id": "ar-MA-JamalNeural", "name": "جمال (مغربي)", "lang": "ar-MA", "gender": "male"},
        {"id": "ar-MA-MounaNeural", "name": "منى (مغربية)", "lang": "ar-MA", "gender": "female"},
        {"id": "ar-SY-AmanyNeural", "name": "أماني (سورية)", "lang": "ar-SY", "gender": "female"},
        {"id": "ar-SY-LaithNeural", "name": "ليث (سوري)", "lang": "ar-SY", "gender": "male"},
    ]

    # ── 🤗 HuggingFace Spaces (مجاني — XTTS v2) ──
    HUGGINGFACE_SPACE_URL: str = Field(
        default="https://coqui-xtts.hf.space",
        description="HuggingFace Space URL for XTTS v2"
    )
    HUGGINGFACE_SPACE_URL_FALLBACK: str = Field(
        default="https://openvoice.hf.space",
        description="Fallback HuggingFace Space URL"
    )
    HUGGINGFACE_TIMEOUT: int = Field(
        default=300,
        description="Timeout for HuggingFace requests (seconds)"
    )
    HUGGINGFACE_MAX_CHARS: int = Field(
        default=500,
        description="Max chars per HuggingFace request"
    )
    HUGGINGFACE_ENABLED: bool = Field(
        default=True,
        description="Enable HuggingFace voice cloning"
    )

    @property
    def huggingface_configured(self) -> bool:
        """HuggingFace يعمل دائماً (بدون مفتاح API)"""
        return self.HUGGINGFACE_ENABLED

    # ── 💎 ElevenLabs (اختياري — مدفوع) ──
    ELEVENLABS_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description=(
            "ElevenLabs API key (starts with sk_...). "
            "Requires Starter plan ($5/month) or higher for voice cloning."
        )
    )
    ELEVENLABS_MODEL_ID: str = Field(
        default="eleven_multilingual_v2",
        description="ElevenLabs model ID for TTS"
    )
    ELEVENLABS_DEFAULT_STABILITY: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="Default voice stability (0.0-1.0)"
    )
    ELEVENLABS_DEFAULT_SIMILARITY: float = Field(
        default=0.75,
        ge=0.0, le=1.0,
        description="Default similarity boost (0.0-1.0)"
    )
    ELEVENLABS_MAX_CHARS: int = Field(
        default=5000,
        description="Max characters per TTS request"
    )

    @property
    def elevenlabs_api_key_value(self) -> Optional[str]:
        if self.ELEVENLABS_API_KEY:
            return self.ELEVENLABS_API_KEY.get_secret_value()
        return None

    @property
    def elevenlabs_configured(self) -> bool:
        key = self.elevenlabs_api_key_value
        return bool(
            key and
            key not in [
                None, "",
                "your-elevenlabs-api-key",
                "sk_your_key_here",
                "sk_xxx",
            ] and
            key.startswith("sk_")
        )

    # ── 🎭 D-ID (Talking Head) ──
    DID_API_KEY: Optional[SecretStr] = Field(
        default=None,
        description=(
            "D-ID API key for talking head animation. "
            "Format: 'Basic <base64_encoded_credentials>'. "
            "Get it from https://studio.d-id.com"
        )
    )
    DID_API_BASE: str = Field(
        default="https://api.d-id.com",
        description="D-ID API base URL"
    )
    DID_DEFAULT_PRESENTER: str = Field(
        default="amy-jcwCkr1grs",
        description="Default D-ID presenter ID"
    )
    DID_MAX_TEXT_CHARS: int = Field(
        default=1000,
        description="Max text characters for talking head"
    )
    DID_DEFAULT_LANGUAGE: str = Field(
        default="ar",
        description="Default language for talking head"
    )
    DID_POLLING_INTERVAL: int = Field(
        default=5,
        description="Polling interval for talking head status (seconds)"
    )
    DID_MAX_POLLING_ATTEMPTS: int = Field(
        default=60,
        description="Max polling attempts (60 × 5s = 5 minutes)"
    )

    @property
    def did_api_key_value(self) -> Optional[str]:
        if self.DID_API_KEY:
            return self.DID_API_KEY.get_secret_value()
        return None

    @property
    def did_configured(self) -> bool:
        key = self.did_api_key_value
        return bool(
            key and
            key not in [
                None, "",
                "your-did-api-key",
                "Basic xxx",
                "Basic your_key_here",
            ] and
            key.startswith("Basic ") and
            len(key) > 20
        )

    # ── 🎙️ Whisper (STT) ──
    WHISPER_ENABLED: bool = Field(
        default=True,
        description="Enable Whisper transcription (requires faster-whisper)"
    )
    WHISPER_MODEL_SIZE: str = Field(
        default="base",
        description="Whisper model size: tiny, base, small, medium, large"
    )
    WHISPER_DEVICE: str = Field(
        default="cpu",
        description="Whisper device: cpu or cuda"
    )

    # ============================================
    # POSTGRESQL DATABASE
    # ============================================
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = Field(
        default="postgres",
        description="PostgreSQL database password"
    )
    POSTGRES_DB: str = "postgres"
    POSTGRES_SSL_MODE: str = "prefer"

    @property
    def POSTGRES_URL(self) -> str:
        ssl_param = f"?sslmode={self.POSTGRES_SSL_MODE}" if self.POSTGRES_SSL_MODE else ""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl_param}"

    @property
    def SYNC_POSTGRES_URL(self) -> str:
        ssl_param = f"?sslmode={self.POSTGRES_SSL_MODE}" if self.POSTGRES_SSL_MODE else ""
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl_param}"

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
    MAX_VOICEOVER_SIZE: int = 100 * 1024 * 1024  # 100MB
    MAX_TALKING_HEAD_IMAGE_SIZE: int = 10 * 1024 * 1024  # 10MB

    ALLOWED_VIDEO_EXTENSIONS: List[str] = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"]
    ALLOWED_IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]
    ALLOWED_AUDIO_EXTENSIONS: List[str] = [".mp3", ".wav", ".m4a", ".ogg", ".webm", ".aac", ".flac"]

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
    # AUDIO PROCESSING
    # ============================================
    AUDIO_TARGET_LUFS: float = Field(
        default=-16.0,
        description="Target loudness for audio normalization (LUFS)"
    )
    AUDIO_PROCESSING_TIMEOUT: int = Field(
        default=300,
        description="Timeout for audio processing (seconds)"
    )

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
        return self.DATABASE_TYPE.lower() == "supabase"

    @property
    def voice_features_available(self) -> bool:
        """هل توجد أي ميزة صوت متاحة؟"""
        return (
            self.EDGE_TTS_ENABLED or
            self.huggingface_configured or
            self.elevenlabs_configured
        )

    @property
    def best_voice_provider(self) -> str:
        """أفضل مزود متاح تلقائياً."""
        if self.elevenlabs_configured:
            return "elevenlabs"
        if self.huggingface_configured:
            return "huggingface"
        if self.EDGE_TTS_ENABLED:
            return "edge_tts"
        return "none"

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

    @field_validator("SUPABASE_DIRECT_URL")
    def validate_supabase_direct_url(cls, v: Optional[str]) -> Optional[str]:
        if v and v == "postgresql://postgres:password@db.project.supabase.co:5432/postgres":
            warnings.warn(
                "SUPABASE_DIRECT_URL is set to default value! Please update it.",
                UserWarning
            )
        return v

    @field_validator("SUPABASE_PUBLIC_KEY")
    def validate_supabase_public_key(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        if v:
            value = v.get_secret_value()
            if value in ["your-supabase-public-key", "your-supabase-anon-key"]:
                warnings.warn(
                    "SUPABASE_PUBLIC_KEY is set to default value! Please update it.",
                    UserWarning
                )
        return v

    @field_validator("SUPABASE_SECRET_KEY")
    def validate_supabase_secret_key(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        if v:
            value = v.get_secret_value()
            if value in ["your-supabase-secret-key", "your-supabase-service-role-key"]:
                warnings.warn(
                    "SUPABASE_SECRET_KEY is set to default value! Please update it.",
                    UserWarning
                )
        return v

    @field_validator("ELEVENLABS_API_KEY")
    def validate_elevenlabs_key(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        if v:
            value = v.get_secret_value()
            if value in ["your-elevenlabs-api-key", "sk_your_key_here", "sk_xxx"]:
                warnings.warn(
                    "ELEVENLABS_API_KEY is set to placeholder value! Please update it.",
                    UserWarning
                )
            elif not value.startswith("sk_"):
                warnings.warn(
                    "ELEVENLABS_API_KEY does not start with 'sk_' — it may be invalid.",
                    UserWarning
                )
        return v

    @field_validator("DID_API_KEY")
    def validate_did_key(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        if v:
            value = v.get_secret_value()
            if value in ["your-did-api-key", "Basic xxx", "Basic your_key_here"]:
                warnings.warn(
                    "DID_API_KEY is set to placeholder value! Please update it.",
                    UserWarning
                )
            elif not value.startswith("Basic "):
                warnings.warn(
                    "DID_API_KEY should start with 'Basic ' — it may be invalid.",
                    UserWarning
                )
            elif len(value) < 20:
                warnings.warn(
                    "DID_API_KEY looks too short — verify it's a valid base64-encoded key.",
                    UserWarning
                )
        return v

    @field_validator("POSTGRES_PASSWORD")
    def validate_postgres_password(cls, v: str) -> str:
        if v == "postgres":
            env = os.getenv("ENVIRONMENT", "development")
            if env == "production":
                warnings.warn(
                    "POSTGRES_PASSWORD is using default value in production! This is insecure.",
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
        # الأساسية
        settings.MEDIA_DIR,
        settings.TEMP_DIR,
        settings.EXPORTS_DIR,
        settings.THUMBNAILS_DIR,
        settings.CACHE_DIR,

        # 🎙️ مجلدات الصوت
        settings.MEDIA_DIR / "voiceovers",
        settings.MEDIA_DIR / "cloned_voices",
        settings.MEDIA_DIR / "cloned_voices" / "cache",
        settings.MEDIA_DIR / "tts",
        settings.MEDIA_DIR / "hf_voices",

        # 🎭 مجلدات Talking Head
        settings.MEDIA_DIR / "talking_heads",
        settings.MEDIA_DIR / "talking_heads" / "images",
        settings.MEDIA_DIR / "talking_heads" / "videos",
        settings.MEDIA_DIR / "talking_heads" / "temp",

        # عامة
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
                    "Set SUPABASE_URL or SUPABASE_DIRECT_URL and both PUBLIC and SECRET keys."
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

        # ── تحذيرات الميزات الاختيارية ──
        if not settings.EDGE_TTS_ENABLED and not settings.huggingface_configured:
            warnings.warn(
                "⚠️ لا يوجد مزود TTS مجاني مُفعَّل! "
                "فعّل EDGE_TTS_ENABLED أو HUGGINGFACE_ENABLED.",
                UserWarning
            )

        if not settings.elevenlabs_configured:
            warnings.warn(
                "ℹ️ ELEVENLABS_API_KEY غير مُعرّف — "
                "سيُستخدم HuggingFace/Edge TTS بدلاً منه (مجاني).",
                UserWarning
            )

        if not settings.did_configured:
            warnings.warn(
                "ℹ️ DID_API_KEY غير مُعرّف — "
                "ميزة Talking Head معطّلة (اختيارية).",
                UserWarning
            )

        ensure_dirs()
        return True

    except Exception as e:
        if settings.is_production:
            raise
        else:
            warnings.warn(f"Configuration validation warning: {e}")
            return False


# ============================================
# FEATURE AVAILABILITY
# ============================================
def get_available_features() -> dict:
    """Get a summary of available features based on configuration."""
    return {
        # الصوت
        "voice_cloning": settings.huggingface_configured or settings.elevenlabs_configured,
        "voice_cloning_free": settings.huggingface_configured,
        "voice_cloning_paid": settings.elevenlabs_configured,
        "edge_tts": settings.EDGE_TTS_ENABLED,
        "talking_head": settings.did_configured,
        "transcription": settings.WHISPER_ENABLED,

        # التخزين
        "supabase_storage": settings.supabase_configured,
        "audio_processing": True,  # ffmpeg

        # المزود الموصى به
        "recommended_voice_provider": settings.best_voice_provider,
    }


# Auto-validation on import (only in production)
if settings.is_production:
    validate_config()
