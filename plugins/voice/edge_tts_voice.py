"""
EdgeTTS Voice Plugin — Microsoft Edge TTS, free, no API key required.
Supports Arabic and 400+ voices across 100+ languages.
"""
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

from shared.ports.voice_port import VoicePort, VoiceConfig, VoiceInfo, VoiceGenerationResult

logger = logging.getLogger(__name__)

# Default voices per language prefix
_DEFAULT_VOICES: dict[str, str] = {
    "ar": "ar-SA-ZariyahNeural",   # Arabic female (Saudi)
    "ar-male": "ar-SA-HamedNeural",
    "en": "en-US-JennyNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-ElviraNeural",
    "tr": "tr-TR-EmelNeural",
}

_FALLBACK_VOICE = "ar-SA-ZariyahNeural"


class EdgeTTSVoicePlugin(VoicePort):
    """
    TTS plugin using Microsoft Edge TTS via the edge-tts library.
    Generates MP3 audio files from text, fully offline (no API key needed).
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def engine_name(self) -> str:
        return "edge_tts"

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    async def list_voices(self) -> list[VoiceInfo]:
        try:
            import edge_tts
            voices = await edge_tts.list_voices()
            return [
                VoiceInfo(
                    id=v["ShortName"],
                    name=v["FriendlyName"],
                    language=v["Locale"],
                    gender=v.get("Gender", "neutral").lower(),
                    description=v.get("VoiceTag", {}).get("ContentCategories", [""])[0]
                    if isinstance(v.get("VoiceTag", {}).get("ContentCategories"), list)
                    else "",
                )
                for v in voices
            ]
        except Exception as e:
            logger.warning("Could not list edge-tts voices: %s", e)
            return [
                VoiceInfo(id="ar-SA-ZariyahNeural", name="Zariyah (Arabic Female)", language="ar-SA", gender="female"),
                VoiceInfo(id="ar-SA-HamedNeural",   name="Hamed (Arabic Male)",   language="ar-SA", gender="male"),
                VoiceInfo(id="en-US-JennyNeural",   name="Jenny (English Female)", language="en-US", gender="female"),
            ]

    async def generate(
        self,
        text: str,
        config: VoiceConfig,
        output_path: Path,
    ) -> VoiceGenerationResult:
        if not text.strip():
            return await self._silent_fallback(text, output_path)

        voice = self._resolve_voice(config)
        rate  = self._speed_to_rate(config.speed)
        pitch = self._pitch_to_str(config.pitch)

        # edge-tts outputs to MP3; ensure path ends with .mp3
        mp3_path = output_path.with_suffix(".mp3")

        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(str(mp3_path))

            if not mp3_path.exists() or mp3_path.stat().st_size < 100:
                raise RuntimeError("edge-tts produced empty output")

            # Convert to requested format if needed
            if output_path.suffix.lower() != ".mp3":
                await self._convert(mp3_path, output_path)
                mp3_path.unlink(missing_ok=True)
            else:
                output_path = mp3_path

            duration = await self._get_duration(output_path)
            logger.info("EdgeTTS generated %s (%.1fs) voice=%s", output_path.name, duration, voice)
            return VoiceGenerationResult(audio_path=output_path, duration=duration, sample_rate=24000)

        except Exception as e:
            logger.error("EdgeTTS generation failed: %s — falling back to silent", e)
            return await self._silent_fallback(text, output_path)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_voice(self, config: VoiceConfig) -> str:
        # Explicit voice ID takes priority
        if config.voice_id and config.voice_id not in ("default", "silent"):
            return config.voice_id
        # Match language prefix
        lang = (config.language or "ar").lower()
        for prefix, voice in _DEFAULT_VOICES.items():
            if lang.startswith(prefix):
                return voice
        return _FALLBACK_VOICE

    @staticmethod
    def _speed_to_rate(speed: float) -> str:
        """Convert speed multiplier (0.5–2.0) to edge-tts rate string (+/-N%)."""
        pct = int((speed - 1.0) * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"

    @staticmethod
    def _pitch_to_str(pitch: float) -> str:
        """Convert pitch multiplier (0.5–2.0) to edge-tts pitch string (+/-NHz)."""
        hz = int((pitch - 1.0) * 50)
        return f"+{hz}Hz" if hz >= 0 else f"{hz}Hz"

    @staticmethod
    async def _convert(src: Path, dst: Path) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), str(dst)],
                capture_output=True, timeout=60,
            ),
        )

    @staticmethod
    async def _get_duration(path: Path) -> float:
        """Use ffprobe to get audio duration in seconds."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                    capture_output=True, text=True, timeout=15,
                ),
            )
            return float(result.stdout.strip())
        except Exception:
            return 5.0

    @staticmethod
    async def _silent_fallback(text: str, output_path: Path) -> VoiceGenerationResult:
        words = len(text.split())
        duration = max(1.0, (words / 150) * 60)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi",
                 "-i", f"anullsrc=r=24000:cl=mono:d={duration}",
                 "-c:a", "libmp3lame", "-b:a", "64k", str(output_path)],
                capture_output=True, timeout=30,
            ),
        )
        return VoiceGenerationResult(audio_path=output_path, duration=duration, sample_rate=24000)
