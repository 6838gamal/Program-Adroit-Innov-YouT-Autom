"""
FFmpeg Renderer Plugin — Real scene-based compositor.
Builds a full video from scenes: each scene = image + audio, concatenated.
Falls back to a simple single-asset render when no scenes are provided.
"""
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

    # ─── Main render entry point ──────────────────────────────────────────────

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

        # ── Scene-based render (new pipeline) ─────────────────────────────────
        scenes: list[dict] = timeline_data.get("scenes", [])
        if scenes:
            return await self._render_scenes(
                scenes, output_path, settings, temp_dir, progress_callback
            )

        # ── Legacy single-asset render ─────────────────────────────────────────
        return await self._render_single_asset(
            timeline_data, assets, output_path, settings, progress_callback
        )

    # ─── Scene-based compositor ───────────────────────────────────────────────

    async def _render_scenes(
        self,
        scenes: list[dict],
        output_path: Path,
        settings: RenderSettings,
        temp_dir: Path,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> RenderResult:
        """
        Compose a video from a list of scene dicts:
          scene = {
            "image_path": str,   # generated scene image
            "audio_path": str,   # generated TTS audio (optional)
            "duration":   float, # seconds
            "text":       str,   # for subtitles / fallback
            "transition": str,   # "fade" | "none" (default: "fade")
          }
        """
        W = settings.resolution_width
        H = settings.resolution_height
        fps = settings.fps
        total = len(scenes)

        await progress_callback(10.0, f"تجهيز {total} مشهد")

        # Step 1: Render each scene to a temp clip
        clips: list[Path] = []
        for i, scene in enumerate(scenes):
            progress = 10.0 + (i / total) * 60.0
            await progress_callback(progress, f"تركيب المشهد {i + 1}/{total}")

            clip_path = temp_dir / f"scene_{i:04d}.mp4"
            await self._render_single_scene(scene, clip_path, W, H, fps)
            if clip_path.exists():
                clips.append(clip_path)
            else:
                logger.warning("Scene %d render failed, skipping", i)

        if not clips:
            raise RuntimeError("جميع المشاهد فشلت في التحويل")

        await progress_callback(72.0, "دمج المشاهد")

        # Step 2: Concatenate all clips
        concat_list = temp_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for clip in clips:
                f.write(f"file '{clip}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]

        await progress_callback(80.0, "الترميز النهائي")
        success = await self._run_ffmpeg(cmd)

        if not success or not output_path.exists():
            raise RuntimeError("FFmpeg concat render failed")

        await progress_callback(95.0, "اكتمل الرندر")
        return RenderResult(
            output_path=output_path,
            duration=sum(s.get("duration", 5.0) for s in scenes),
            file_size=output_path.stat().st_size,
        )

    async def _render_single_scene(
        self,
        scene: dict,
        output_path: Path,
        W: int,
        H: int,
        fps: int,
    ) -> None:
        """Render one scene (image + optional audio) into a short MP4 clip."""
        image_path = scene.get("image_path", "")
        audio_path = scene.get("audio_path", "")
        duration   = float(scene.get("duration", 5.0))
        transition = scene.get("transition", "fade")

        has_image = image_path and Path(image_path).exists()
        has_audio = audio_path and Path(audio_path).exists()

        # Build video input
        if has_image:
            video_input = ["-loop", "1", "-t", str(duration), "-i", image_path]
            vf = (
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"format=yuv420p"
            )
            if transition == "fade":
                fade_dur = min(0.5, duration * 0.15)
                vf += (
                    f",fade=t=in:st=0:d={fade_dur}"
                    f",fade=t=out:st={max(0, duration - fade_dur):.2f}:d={fade_dur}"
                )
        else:
            # Black video placeholder
            video_input = [
                "-f", "lavfi",
                "-i", f"color=black:size={W}x{H}:rate={fps}:duration={duration}",
            ]
            vf = "format=yuv420p"

        # Build audio input
        if has_audio:
            audio_input = ["-i", audio_path]
            audio_encode = ["-c:a", "aac", "-b:a", "192k"]
            # Trim/pad audio to match duration
            audio_filter = [
                "-af",
                f"apad,atrim=0:{duration}",
            ]
        else:
            # Silent audio
            audio_input = [
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
            ]
            audio_encode = ["-c:a", "aac", "-b:a", "64k"]
            audio_filter = []

        cmd = (
            ["ffmpeg", "-y"]
            + video_input
            + audio_input
            + [
                "-vf", vf,
                "-r", str(fps),
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
            ]
            + audio_encode
            + audio_filter
            + [
                "-shortest",
                "-movflags", "+faststart",
                str(output_path),
            ]
        )

        await self._run_ffmpeg(cmd)

    # ─── Legacy single-asset render ───────────────────────────────────────────

    async def _render_single_asset(
        self,
        timeline_data: dict,
        assets: dict,
        output_path: Path,
        settings: RenderSettings,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> RenderResult:
        duration = timeline_data.get("duration", 10.0)
        W = settings.resolution_width
        H = settings.resolution_height
        fps = settings.fps

        await progress_callback(5.0, "تجهيز الأصول")

        video_assets = [a for a in assets.values() if a.get("type") == "video" and a.get("file_path")]
        image_assets = [a for a in assets.values() if a.get("type") in ("image", "background") and a.get("file_path")]

        await progress_callback(15.0, "بناء filter graph")

        if video_assets:
            cmd = [
                "ffmpeg", "-y", "-i", video_assets[0]["file_path"],
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
                "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output_path),
            ]
        elif image_assets:
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", image_assets[0]["file_path"],
                "-t", str(duration),
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "23", str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=black:size={W}x{H}:rate={fps}:duration={duration}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28", str(output_path),
            ]

        await progress_callback(30.0, "تشفير الفيديو")
        success = await self._run_ffmpeg(cmd)

        if not success or not output_path.exists():
            raise RuntimeError("FFmpeg render failed")

        await progress_callback(90.0, "اكتمل")
        return RenderResult(
            output_path=output_path,
            duration=duration,
            file_size=output_path.stat().st_size,
        )

    # ─── Thumbnail ────────────────────────────────────────────────────────────

    async def generate_thumbnail(
        self,
        video_path: Path,
        config: ThumbnailConfig,
        output_path: Path,
    ) -> Path:
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-ss", "00:00:01.000", "-vframes", "1",
            "-vf", (
                f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease,"
                f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2"
            ),
            str(output_path),
        ]
        await self._run_ffmpeg(cmd)
        if not output_path.exists():
            await self._create_blank_thumbnail(config, output_path)
        return output_path

    # ─── Utilities ────────────────────────────────────────────────────────────

    async def _run_ffmpeg(self, cmd: list[str]) -> bool:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300),
            )
            if result.returncode != 0:
                logger.error("FFmpeg error:\n%s", result.stderr[-3000:])
                return False
            return True
        except Exception as e:
            logger.exception("FFmpeg execution error: %s", e)
            return False

    async def _create_blank_thumbnail(self, config: ThumbnailConfig, output_path: Path) -> None:
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (config.width, config.height), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)
            if config.title:
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 56
                    )
                except Exception:
                    font = ImageFont.load_default()
                draw.text(
                    (config.width // 2, config.height // 2),
                    config.title, font=font,
                    fill=config.text_color, anchor="mm",
                )
            img.save(str(output_path), "JPEG", quality=90)
        except Exception as e:
            logger.warning("Could not create thumbnail: %s", e)
