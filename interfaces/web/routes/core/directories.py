"""كل المجلدات + الثوابت المشتركة."""
from pathlib import Path

from config.settings import settings

VOICEOVER_DIR = Path(settings.MEDIA_DIR) / "voiceovers"
VOICEOVER_DIR.mkdir(parents=True, exist_ok=True)

CLONED_VOICES_DIR = Path(settings.MEDIA_DIR) / "cloned_voices"
CLONED_VOICES_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = CLONED_VOICES_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HF_VOICES_DIR = Path(settings.MEDIA_DIR) / "hf_voices"
HF_VOICES_DIR.mkdir(parents=True, exist_ok=True)

TALKING_HEADS_DIR = Path(settings.MEDIA_DIR) / "talking_heads"
TALKING_HEADS_DIR.mkdir(parents=True, exist_ok=True)

PROPERTY_ASSETS_DIR = Path(settings.MEDIA_DIR) / "property_assets"
PROPERTY_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

PROPERTY_VIDEOS_DIR = Path(settings.MEDIA_DIR) / "property_videos"
PROPERTY_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

JOBS_DIR = Path(settings.MEDIA_DIR) / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

JOBS_STORAGE_PREFIX = "jobs"

VOICEOVER_MAX_SIZE = 100 * 1024 * 1024  # 100MB

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a",
    "audio/x-m4a", "audio/aac", "audio/flac",
    "video/webm",
}
