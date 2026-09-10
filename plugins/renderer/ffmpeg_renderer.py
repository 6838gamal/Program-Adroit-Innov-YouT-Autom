"""
FFmpeg Renderer Plugin — Real scene-based compositor.
Builds a full video from scenes: each scene = image + audio, concatenated.
Falls back to a simple single-asset render when no scenes are provided.
"""
import asyncio
import logging
import subprocess
import traceback
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


def _diag(msg: str) -> None:
    print(msg, flush=True)
    logger.info(msg)


def _diag_err(msg: str, exc: BaseException | None = None) -> None:
    print(msg, flush=True)
    if exc is not None:
        logger.error(msg, exc_info=exc)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    else:
        logger.error(msg)


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
        _diag(f"🎬 FFmpegRenderer.render START project={project_id}")
        _diag(f"🎬 temp_dir={temp_dir}")
        _diag(f"🎬 settings fps={settings.fps} W={settings.resolution_width} H={settings.resolution_height}")
        _diag(f"🎬 timeline_data keys={list(timeline_data.keys())}")

        output_path = temp_dir / f"render_{project_id}.mp4"
        _diag(f"🎬 output_path={output_path}")

        # ── Scene-based render (new pipeline) ─────────────────────────────────
        scenes: list[dict] = timeline_data.get("scenes", [])
        _diag(f"🎬 scenes count={len(scenes)}")

        if scenes:
            for i, sc in enumerate(scenes):
                _diag(
                    f"🎬 scene[{i}] text_len={len(sc.get('text', ''))} "
                    f"image={sc.get('image_path', '')!r} "
                    f"audio={sc.get('audio_path', '')!r} "
                    f"dur={sc.get('duration')}"
                )
            return await self._render_scenes(
                scenes, output_path, settings, temp_dir, progress_callback
            )

        # ── Legacy single-asset render ─────────────────────────────────────────
        _diag("🎬 No scenes — falling back to single-asset render")
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

        _diag(f"🎬 _render_scenes START total={total} W={W} H={H} fps={fps}")

        await progress_callback(10.0, f"تجهيز {total} مشهد")

        # Step 1: Render each scene to a temp clip
        clips: list[Path] = []
        for i, scene in enumerate(scenes):
            progress = 10.0 + (i / total) * 60.0
            await progress_callback(progress, f"تركيب المشهد {i + 1}/{total}")

            clip_path = temp_dir / f"clip_{i:04d}.mp4"  # ← اسم مميز لتجنب التعارض مع scene_{i}.jpg
            _diag(f"🎬 Rendering scene {i + 1}/{total} → {clip_path}")

            try:
                await self._render_single_scene(scene, clip_path, W, H, fps)
            except Exception as e:
                _diag_err(f"💥 _render_single_scene failed for scene {i}: {e}", e)
                continue

            if clip_path.exists() and clip_path.stat().st_size > 0:
                _diag(f"✅ scene {i} clip OK size={clip_path.stat().st_size}")
                clips.append(clip_path)
            else:
                _diag_err(f"⚠️ Scene {i} render produced no/invalid output: {clip_path}")

        if not clips:
            raise RuntimeError("جميع المشاهد فشلت في التحويل")

        _diag(f"🎬 All scenes rendered, clips={len(clips)}")

        await progress_callback(72.0, "دمج المشاهد")

        # Step 2: Concatenate all clips
        concat_list = temp_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for clip in clips:
                f.write(f"file '{clip}'\n")
        _diag(f"🎬 concat.txt written with {len(clips)} entries")

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
        _diag(f"🎬 Running concat FFmpeg cmd: {' '.join(cmd)}")
        success = await self._run_ffmpeg(cmd)
        _diag(f"🎬 Concat FFmpeg success={success}")

        if not success or not output_path.exists():
            raise RuntimeError("FFmpeg concat render failed")

        await progress_callback(95.0, "اكتمل الرندر")

        result = RenderResult(
            output_path=output_path,
            duration=sum(s.get("duration", 5.0) for s in scenes),
            file_size=output_path.stat().st_size,
        )
        _diag(f"🎬 _render_scenes END output={output_path} size={result.file_size}")
        return result

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

        has_image = bool(image_path) and Path(image_path).exists()
        has_audio = bool(audio_path) and Path(audio_path).exists()

        _diag(
            f"🎬 _render_single_scene: image={has_image} audio={has_audio} "
            f"duration={duration} transition={transition}"
        )

        # ── Build video input ────────────────────────────────────────────────
        if has_image:
            video_input = ["-loop", "1", "-i", image_path]
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

        # ── Build audio input ────────────────────────────────────────────────
        if has_audio:
            audio_input = ["-i", audio_path]
            audio_encode = ["-c:a", "aac", "-b:a", "192k"]
            # Trim audio to match duration WITHOUT apad (apad + shortest = hang)
            audio_filter = ["-af", f"atrim=0:{duration}"]
        else:
            # Silent audio
            audio_input = [
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
            ]
            audio_encode = ["-c:a", "aac", "-b:a", "64k"]
            audio_filter = []

        # ── Build full command ───────────────────────────────────────────────
        # IMPORTANT: -t on OUTPUT (not input), and -shortest only for audio
        # Remove "-shortest" entirely to avoid deadlocks; use -t on output.
        cmd = (
            ["ffmpeg", "-y", "-nostdin"]
            + video_input
            + audio_input
            + [
                "-vf", vf,
                "-r", str(fps),
                "-t", str(duration),  # ← output duration (limits both streams)
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
            ]
            + audio_encode
            + audio_filter
            + [
                "-movflags", "+faststart",
                str(output_path),
            ]
        )

        _diag(f"🎬 Scene FFmpeg cmd: {' '.join(cmd)}")
        ok = await self._run_ffmpeg(cmd)
        _diag(f"🎬 Scene FFmpeg success={ok} exists={output_path.exists()}")

        if not ok:
            raise RuntimeError(f"Scene render failed: {output_path}")

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

        _diag(f"🎬 _render_single_asset START duration={duration}")

        await progress_callback(5.0, "تجهيز الأصول")

        video_assets = [a for a in assets.values() if a.get("type") == "video" and a.get("file_path")]
        image_assets = [a for a in assets.values() if a.get("type") in ("image", "background") and a.get("file_path")]

        await progress_callback(15.0, "بناء filter graph")

        if video_assets:
            cmd = [
                "ffmpeg", "-y", "-nostdin", "-i", video_assets[0]["file_path"],
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
                "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output_path),
            ]
        elif image_assets:
            cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-loop", "1", "-i", image_assets[0]["file_path"],
                "-t", str(duration),
                "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "23", str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-nostdin", "-f", "lavfi",
                "-i", f"color=black:size={W}x{H}:rate={fps}:duration={duration}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28", str(output_path),
            ]

        await progress_callback(30.0, "تشفير الفيديو")
        _diag(f"🎬 Single-asset FFmpeg cmd: {' '.join(cmd)}")
        success = await self._run_ffmpeg(cmd)
        _diag(f"🎬 Single-asset success={success}")

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
        _diag(f"🎬 generate_thumbnail video={video_path} → {output_path}")

        cmd = [
            "ffmpeg", "-y", "-nostdin", "-i", str(video_path),
            "-ss", "00:00:01.000", "-vframes", "1",
            "-vf", (
                f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease,"
                f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2"
            ),
            str(output_path),
        ]
        ok = await self._run_ffmpeg(cmd)
        _diag(f"🎬 thumbnail ffmpeg ok={ok} exists={output_path.exists()}")

        if not output_path.exists():
            await self._create_blank_thumbnail(config, output_path)
        return output_path

    # ─── Utilities ────────────────────────────────────────────────────────────

    async def _run_ffmpeg(self, cmd: list[str]) -> bool:
        """Run FFmpeg with proper stdin/stdout handling and timeout."""
        loop = asyncio.get_event_loop()

        def _run():
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                stdin=subprocess.DEVNULL,  # ← CRITICAL: prevent hangs
            )

        try:
            _diag(f"🎬 FFmpeg exec: {' '.join(cmd[:8])} ...")
            result = await loop.run_in_executor(None, _run)

            if result.returncode != 0:
                _diag_err(
                    f"💥 FFmpeg failed (rc={result.returncode})\n"
                    f"STDERR tail:\n{result.stderr[-3000:]}"
                )
                return False

            _diag(f"✅ FFmpeg OK (rc=0)")
            return True

        except subprocess.TimeoutExpired as e:
            _diag_err(f"💥 FFmpeg TIMEOUT after 300s: {e}", e)
            return False

        except Exception as e:
            _diag_err(f"💥 FFmpeg execution error: {e}", e)
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
            _diag(f"✅ Blank thumbnail created: {output_path}")
        except Exception as e:
            _diag_err(f"⚠️ Could not create blank thumbnail: {e}", e)
