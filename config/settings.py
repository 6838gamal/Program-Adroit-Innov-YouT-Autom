from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Content Production & Publishing Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = Field(default="change-me-in-production")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 5000

    # Database — use APP_DATABASE_URL to avoid Replit's auto-injected DATABASE_URL
    APP_DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR}/data/platform.db"
    DATABASE_ECHO: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return self.APP_DATABASE_URL

    # Storage
    MEDIA_DIR: Path = BASE_DIR / "media"
    TEMP_DIR: Path = BASE_DIR / "temp"
    EXPORTS_DIR: Path = BASE_DIR / "exports"
    THUMBNAILS_DIR: Path = BASE_DIR / "media" / "thumbnails"

    # Plugin config
    PLUGIN_CONFIG_PATH: Path = BASE_DIR / "config" / "plugin_config.yaml"

    # Security
    CREDENTIALS_ENCRYPTION_KEY: Optional[str] = None

    # Scheduler
    SCHEDULER_ENABLED: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def ensure_dirs() -> None:
    for d in [
        settings.MEDIA_DIR,
        settings.TEMP_DIR,
        settings.EXPORTS_DIR,
        settings.THUMBNAILS_DIR,
        BASE_DIR / "data",
    ]:
        d.mkdir(parents=True, exist_ok=True)
