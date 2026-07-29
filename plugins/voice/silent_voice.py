"""
SilentVoicePlugin — fallback voice engine that generates a silent audio file.
Used when no TTS engine is installed/configured.
"""
import asyncio
import logging
from pathlib import Path

from shared.ports.voice_port import VoicePort, VoiceConfig, VoiceInfo, VoiceGenerationResult

logger = logging.getLogger(__name__)


class SilentVoicePlugin(VoicePort):
    """Generates a silent audio track (placeholder for real TTS)."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def engine_name(self) -> str:
        return "silent"

    def is_available(self) -> bool:
        return True

    async def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id="silent", name="Silent (Placeholder)", language="any", gender="neutral")
        ]

    async def generate(
        self,
        text: str,
        config: VoiceConfig,
        output_path: Path,
    ) -> VoiceGenerationResult:
        # Estimate ~150 words per minute → seconds
        words = len(text.split())
        duration = max(1.0, (words / 150) * 60)

        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=22050:cl=mono:d={duration}",
            "-c:a", "libmp3lame",
            "-b:a", "64k",
            str(output_path),
        ]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, timeout=30),
        )
        if result.returncode != 0:
            # Fallback: create empty file
            output_path.write_bytes(b"")

        return VoiceGenerationResult(
            audio_path=output_path,
            duration=duration,
            sample_rate=22050,
        )
