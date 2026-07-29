import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Callable, Awaitable
import uuid

from shared.ports.renderer_port import (
    RendererPort,
    RenderSettings,
    RenderResult,
    ThumbnailConfig,
    RendererCapabilities,
)

logger = logging.getLogger(__name__)


class FFmpegRendererPlugin(RendererPort):
    """
    FFmpeg-based rendering engine.
    The ONLY place in the system where FFmpeg is used for rendering.
    All other code interacts with RendererPort only.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(
            supported_formats=["mp4", "mov", "avi", "webm", "gif"],
            supports_hardware_acceleration=False,
            max_resolution=(3840, 2160),
            name="FFmpeg",
        )

    async def render(
        self,
        project_id: uuid.UUID,
        timeline_data: dict,
        assets: dict,
        settings: RenderSettings,
        temp_dir: Path,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> RenderResult:
        output_path = temp_dir / f"render_{project_id}.mp4"
        duration = timeline_data.get("duration", 10.0)

        await progress_callback(5.0, "Preparing render")

        # Build a simple render: if we have a video asset, re-encode it;
        # otherwise generate a black video as placeholder.
        video_assets = [
            a for a in assets.values()
            if a.get("type") in ("video",) and a.get("file_path")
        ]
        image_assets = [
            a for a in assets.values()
            if a.get("type") in ("image", "background") and a.get("file_path")
        ]

        await progress_callback(15.0, "Building filter graph")

        width = settings.resolution_width
        height = settings.resolution_height
        fps = settings.fps

        if video_assets:
            input_path = video_assets[0]["file_path"]
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "-r", str(fps),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_path),
            ]
        elif image_assets:
            input_path = image_assets[0]["file_path"]
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", input_path,
                "-t", str(duration),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r", str(fps),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                str(output_path),
            ]
        else:
            # Generate a black video as placeholder
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=black:size={width}x{height}:rate={fps}:duration={duration}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "28",
                str(output_path),
            ]

        await progress_callback(30.0, "Encoding video")
        success = await self._run_ffmpeg(cmd)

        if not success or not output_path.exists():
            raise RuntimeError("FFmpeg render failed")

        await progress_callback(90.0, "Finalizing")

        file_size = output_path.stat().st_size
        return RenderResult(
            output_path=output_path,
            duration=duration,
            file_size=file_size,
        )

    async def generate_thumbnail(
        self,
        video_path: Path,
        config: ThumbnailConfig,
        output_path: Path,
    ) -> Path:
        """Extract a frame from the video and use it as thumbnail."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", "00:00:01.000",
            "-vframes", "1",
            "-vf", f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease,"
                   f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2",
            str(output_path),
        ]
        await self._run_ffmpeg(cmd)
        if not output_path.exists():
            # Fallback: create blank thumbnail with Pillow
            await self._create_blank_thumbnail(config, output_path)
        return output_path

    async def _run_ffmpeg(self, cmd: list[str]) -> bool:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                ),
            )
            if result.returncode != 0:
                logger.error("FFmpeg error:\n%s", result.stderr[-2000:])
                return False
            return True
        except Exception as e:
            logger.exception("FFmpeg execution error: %s", e)
            return False

    async def _create_blank_thumbnail(
        self, config: ThumbnailConfig, output_path: Path
    ) -> None:
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.new("RGB", (config.width, config.height), color=(30, 30, 30))
            draw = ImageDraw.Draw(img)
            if config.title:
                draw.text(
                    (config.width // 2, config.height // 2),
                    config.title,
                    fill=config.text_color,
                    anchor="mm",
                )
            img.save(str(output_path), "JPEG", quality=90)
        except Exception as e:
            logger.warning("Could not create thumbnail: %s", e)
