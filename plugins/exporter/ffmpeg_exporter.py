import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Callable, Awaitable

from shared.ports.exporter_port import ExporterPort, ExportSettings, ExportResult

logger = logging.getLogger(__name__)


class FFmpegExporterPlugin(ExporterPort):
    """Exports rendered video to various formats using FFmpeg."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_supported_formats(self) -> list[str]:
        return ["mp4", "mov", "avi", "gif", "webm"]

    async def export(
        self,
        input_path: Path,
        settings: ExportSettings,
        output_path: Path,
        progress_callback: Callable[[float], Awaitable[None]],
    ) -> ExportResult:
        cmd = self._build_command(input_path, settings, output_path)
        await progress_callback(10.0)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=600),
        )

        if result.returncode != 0:
            logger.error("FFmpeg export error:\n%s", result.stderr[-2000:])
            raise RuntimeError(f"Export failed: {result.stderr[-500:]}")

        await progress_callback(100.0)

        file_size = output_path.stat().st_size if output_path.exists() else 0
        return ExportResult(
            output_path=output_path,
            file_size=file_size,
            duration=0.0,
            format=settings.format,
            resolution=(settings.width, settings.height),
        )

    def _build_command(
        self, input_path: Path, s: ExportSettings, output_path: Path
    ) -> list[str]:
        scale = (
            f"scale={s.width}:{s.height}:force_original_aspect_ratio=decrease,"
            f"pad={s.width}:{s.height}:(ow-iw)/2:(oh-ih)/2"
        )
        base = ["ffmpeg", "-y", "-i", str(input_path)]

        if s.format == "gif":
            return base + [
                "-vf", f"{scale},split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "-r", str(min(s.fps, 15)),
                str(output_path),
            ]
        elif s.format == "webm":
            return base + [
                "-vf", scale,
                "-c:v", "libvpx-vp9",
                "-b:v", s.video_bitrate,
                "-c:a", "libopus",
                "-b:a", s.audio_bitrate,
                str(output_path),
            ]
        else:
            return base + [
                "-vf", scale,
                "-r", str(s.fps),
                "-c:v", "libx264",
                "-preset", s.preset,
                "-crf", str(s.crf),
                "-b:v", s.video_bitrate,
                "-c:a", "aac",
                "-b:a", s.audio_bitrate,
                "-movflags", "+faststart",
                str(output_path),
            ]
