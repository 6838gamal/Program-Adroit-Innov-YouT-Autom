"""
HuggingFace TTS Plugin.
Runs any HF text-to-speech model via the HF Inference API (no local download).
Wraps the result and converts to MP3 via FFmpeg.
"""
import asyncio
import logging
import subprocess
from pathlib import Path

from shared.ports.voice_port import VoicePort, VoiceConfig, VoiceInfo, VoiceGenerationResult

logger = logging.getLogger(__name__)


class HFTTSPlugin(VoicePort):
    """
    TTS plugin backed by a HuggingFace model via InferenceClient.
    model_id: e.g. "facebook/mms-tts-ara", "microsoft/speecht5_tts"
    """

    def __init__(self, model_id: str, hf_token: str | None = None, config: dict | None = None):
        self._model_id = model_id
        self._token = hf_token
        self._config = config or {}

    @property
    def engine_name(self) -> str:
        return f"hf:{self._model_id}"

    def is_available(self) -> bool:
        try:
            from huggingface_hub import InferenceClient  # noqa: F401
            return True
        except ImportError:
            return False

    async def list_voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(
            id=self._model_id,
            name=self._model_id.split("/")[-1],
            language="ar" if "ara" in self._model_id or "arabic" in self._model_id.lower() else "en",
            gender="neutral",
            description=f"HuggingFace: {self._model_id}",
        )]

    async def generate(
        self,
        text: str,
        config: VoiceConfig,
        output_path: Path,
    ) -> VoiceGenerationResult:
        if not text.strip():
            return await self._silent_fallback(text, output_path)

        try:
            from huggingface_hub import InferenceClient
            import io

            loop = asyncio.get_event_loop()

            def _call_api():
                client = InferenceClient(token=self._token)
                # Returns bytes (wav/flac/mp3 depending on model)
                audio_bytes = client.text_to_speech(text, model=self._model_id)
                return audio_bytes

            audio_bytes = await loop.run_in_executor(None, _call_api)

            # Write raw bytes to a temp file, then convert to MP3
            raw_path = output_path.with_suffix(".raw.wav")
            raw_path.write_bytes(audio_bytes)

            # Convert to target format via FFmpeg
            mp3_path = output_path.with_suffix(".mp3")
            convert_ok = await self._convert(raw_path, mp3_path)
            raw_path.unlink(missing_ok=True)

            final_path = mp3_path if convert_ok and mp3_path.exists() else output_path
            if not final_path.exists():
                raise RuntimeError("Audio conversion failed")

            duration = await self._get_duration(final_path)
            logger.info("HF TTS [%s] → %s (%.1fs)", self._model_id, final_path.name, duration)
            return VoiceGenerationResult(audio_path=final_path, duration=duration, sample_rate=22050)

        except Exception as e:
            logger.error("HF TTS [%s] failed: %s — falling back", self._model_id, e)
            return await self._silent_fallback(text, output_path)

    @staticmethod
    async def _convert(src: Path, dst: Path) -> bool:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src), str(dst)],
                    capture_output=True, timeout=60,
                ),
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    async def _get_duration(path: Path) -> float:
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
