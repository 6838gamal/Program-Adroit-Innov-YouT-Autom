"""FFprobe duration helpers."""
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def _get_audio_duration(file_path: Path) -> float:
    """احسب مدة ملف صوتي باستخدام ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip() or 0)
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return 0.0


async def _get_video_duration(file_path: Path) -> float:
    """احسب مدة ملف فيديو باستخدام ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip() or 0)
    except Exception as e:
        logger.warning(f"ffprobe video failed: {e}")
        return 0.0
