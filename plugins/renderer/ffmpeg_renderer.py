import asyncio
import logging
import traceback
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Optional

from shared.ports.renderer_port import (
    RendererPort,
    RenderSettings,
    RenderResult,
    ThumbnailConfig,
    RendererCapabilities,
)


logger = logging.getLogger(__name__)


def _diag(msg: str) -> None:
    """Diagnostic log helper."""
    print(msg, flush=True)
    logger.info(msg)


def _diag_err(msg: str) -> None:
    """Diagnostic error log helper."""
    print(msg, flush=True)
    logger.error(msg)


class FFmpegRendererPlugin(RendererPort):
    """
    FFmpeg-based video renderer.

    Responsibilities:
    - Render complete timelines.
    - Render scene-based videos.
    - Render single assets.
    - Generate thumbnails.
    - Execute FFmpeg safely without blocking the event loop.

    Implements the RendererPort contract defined in
    shared.ports.renderer_port.

    Memory notes:
    - Tuned for Render free tier (512MB RAM).
    - Clamps resolution to 1280x720 max.
    - Uses ultrafast/veryfast x264 presets.
    - Uses -threads 1 to limit memory.
    - Uses -crf 28 for smaller buffers.
    """

    # Memory safety: never exceed this pixel count per frame.
    # 1280x720 = 921,600 pixels. 1920x1080 would be 2,073,600.
    MAX_PIXELS = 1280 * 720

    # Timeout per FFmpeg process (seconds).
    DEFAULT_TIMEOUT = 300

    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        timeout: int = 300,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.timeout = timeout

        _diag(
            f"🎬 FFmpeg renderer initialized "
            f"(ffmpeg={self.ffmpeg_binary}, timeout={self.timeout}s, "
            f"max_pixels={self.MAX_PIXELS})"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Capabilities
    # ─────────────────────────────────────────────────────────────────────────

    def get_capabilities(self) -> RendererCapabilities:
        """Return the capabilities of this renderer."""
        return RendererCapabilities(
            supported_formats=["mp4"],
            supports_hardware_acceleration=False,
            max_resolution=(1280, 720),
            name="ffmpeg",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Main render entrypoint (matches RendererPort contract)
    # ─────────────────────────────────────────────────────────────────────────

    async def render(
        self,
        project_id: uuid.UUID,
        timeline_data: dict,
        assets: dict,
        settings: RenderSettings,
        temp_dir: Path,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> RenderResult:
        """
        Render a complete project.

        If timeline_data contains scenes, scene-based rendering is used.
        Otherwise a single-asset render is attempted.
        """

        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        output_path = temp_dir / f"render_{project_id}.mp4"

        _diag("🎬 Starting render")
        _diag(f"   project_id={project_id}")
        _diag(f"   temp_dir={temp_dir}")
        _diag(f"   output={output_path}")
        _diag(
            f"   settings: fps={settings.fps}, "
            f"res={settings.resolution_width}x{settings.resolution_height}, "
            f"quality={settings.quality}"
        )
        _diag(f"   assets keys={list(assets.keys()) if assets else None}")

        scenes = timeline_data.get("scenes", [])

        if scenes:
            _diag(f"🎬 Found {len(scenes)} scenes")
            rendered_path = await self._render_scenes(
                project_id=project_id,
                scenes=scenes,
                timeline_data=timeline_data,
                settings=settings,
                temp_dir=temp_dir,
                output_path=output_path,
                progress_callback=progress_callback,
            )
        else:
            _diag("🎬 No scenes found, using single asset renderer")
            rendered_path = await self._render_single_asset(
                project_id=project_id,
                timeline_data=timeline_data,
                settings=settings,
                temp_dir=temp_dir,
                output_path=output_path,
                progress_callback=progress_callback,
            )

        size_bytes = (
            rendered_path.stat().st_size if rendered_path.exists() else 0
        )

        return RenderResult(
            output_path=rendered_path,
            duration=0.0,
            file_size=size_bytes,
            metadata={
                "fps": settings.fps,
                "width": settings.resolution_width,
                "height": settings.resolution_height,
                "quality": settings.quality,
                "renderer": "ffmpeg",
            },
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Scene-based rendering
    # ─────────────────────────────────────────────────────────────────────────

    async def _render_scenes(
        self,
        project_id: uuid.UUID,
        scenes: list,
        timeline_data: dict,
        settings: RenderSettings,
        temp_dir: Path,
        output_path: Path,
        progress_callback: Optional[
            Callable[[float, str], Awaitable[None]]
        ] = None,
    ) -> Path:
        """
        Render every scene into a separate MP4 and concatenate them.

        A failed scene is treated as a fatal render error.
        This avoids silently producing incomplete videos.
        """

        fps = int(settings.fps)
        width = int(settings.resolution_width)
        height = int(settings.resolution_height)
        quality = str(settings.quality)

        # ── Memory safety clamp ──────────────────────────────────────────
        width, height = self._clamp_resolution(width, height)

        _diag(
            f"🎬 Render settings: "
            f"fps={fps}, resolution={width}x{height}, quality={quality}"
        )

        clip_paths: list[Path] = []

        total_scenes = len(scenes)

        for index, scene in enumerate(scenes):
            clip_path = temp_dir / f"clip_{index:04d}.mp4"

            _diag(
                f"🎬 Rendering scene {index + 1}/{total_scenes}"
            )
            _diag(f"   clip={clip_path}")

            try:
                await self._render_single_scene(
                    scene=scene,
                    output_path=clip_path,
                    fps=fps,
                    width=width,
                    height=height,
                    quality=quality,
                )
            except asyncio.CancelledError:
                _diag_err(
                    f"🛑 Scene {index} render was cancelled"
                )
                raise

            except Exception as exc:
                _diag_err(
                    f"💥 Scene {index} render failed: {exc}"
                )
                _diag_err(traceback.format_exc())
                raise

            if not clip_path.exists():
                raise RuntimeError(
                    f"FFmpeg completed but scene clip was not created: "
                    f"{clip_path}"
                )

            clip_size = clip_path.stat().st_size

            if clip_size <= 0:
                raise RuntimeError(
                    f"FFmpeg created an empty scene clip: {clip_path}"
                )

            _diag(
                f"✅ Scene {index} rendered successfully "
                f"({clip_size} bytes)"
            )

            clip_paths.append(clip_path)

            if progress_callback:
                progress = 0.62 + ((index + 1) / total_scenes) * 0.35

                try:
                    await progress_callback(
                        progress,
                        f"رندر المشهد {index + 1}/{total_scenes}",
                    )
                except Exception as exc:
                    _diag_err(
                        f"⚠️ Progress callback failed: {exc}"
                    )

        if not clip_paths:
            raise RuntimeError("No scene clips were rendered")

        concat_list = temp_dir / "concat.txt"

        _diag(f"🎬 Creating concat file: {concat_list}")

        with concat_list.open("w", encoding="utf-8") as file:
            for clip_path in clip_paths:
                safe_path = str(clip_path).replace("'", "'\\''")
                file.write(f"file '{safe_path}'\n")

        concat_cmd = [
            self.ffmpeg_binary,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:v",
            "libx264",
            "-preset",
            self._get_preset(quality),
            "-crf",
            "28",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        _diag("🎬 Starting final concat render")

        success = await self._run_ffmpeg(concat_cmd)

        if not success:
            raise RuntimeError(
                "FFmpeg failed while concatenating scene clips"
            )

        if not output_path.exists():
            raise RuntimeError(
                f"Final output was not created: {output_path}"
            )

        output_size = output_path.stat().st_size

        if output_size <= 0:
            raise RuntimeError(
                f"Final output is empty: {output_path}"
            )

        _diag(
            f"✅ Final video rendered successfully "
            f"({output_size} bytes)"
        )

        return output_path

    # ─────────────────────────────────────────────────────────────────────────
    # Single scene
    # ─────────────────────────────────────────────────────────────────────────

    async def _render_single_scene(
        self,
        scene: dict,
        output_path: Path,
        fps: int,
        width: int,
        height: int,
        quality: str = "medium",
    ) -> None:
        """
        Render one scene into an MP4 clip.

        Accepts both key naming conventions:
        - image_path / image
        - audio_path / audio
        """

        output_path.parent.mkdir(parents=True, exist_ok=True)

        text = str(scene.get("text", "") or "")

        image_path = scene.get("image_path") or scene.get("image")
        audio_path = scene.get("audio_path") or scene.get("audio")

        duration_value = scene.get("duration", 0)

        try:
            duration = float(duration_value)
        except (TypeError, ValueError):
            duration = 0.0

        if duration <= 0:
            duration = 1.0

        transition = str(
            scene.get("transition", "fade") or "fade"
        ).lower()

        _diag("🎬 Scene info:")
        _diag(f"   text length: {len(text)}")
        _diag(f"   image: {image_path}")
        _diag(f"   audio: {audio_path}")
        _diag(f"   duration: {duration}")
        _diag(f"   transition: {transition}")

        command: list[str] = [
            self.ffmpeg_binary,
            "-y",
            "-nostdin",
            "-hide_banner",
        ]

        # ---------------------------------------------------------
        # Video input
        # ---------------------------------------------------------

        has_image = False
        if image_path:
            image = Path(str(image_path))

            if image.exists() and image.stat().st_size > 0:
                command.extend(
                    [
                        "-loop",
                        "1",
                        "-i",
                        str(image),
                    ]
                )
                has_image = True
            else:
                _diag_err(
                    f"⚠️ Scene image missing or empty, "
                    f"falling back to black background: {image}"
                )

        if not has_image:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={width}x{height}:r={fps}",
                ]
            )

        # ---------------------------------------------------------
        # Audio input
        # ---------------------------------------------------------

        has_audio = False

        if audio_path:
            audio = Path(str(audio_path))

            if audio.exists() and audio.stat().st_size > 0:
                command.extend(
                    [
                        "-i",
                        str(audio),
                    ]
                )
                has_audio = True
            else:
                _diag_err(
                    f"⚠️ Scene audio missing or empty, "
                    f"falling back to silence: {audio}"
                )

        if not has_audio:
            # Generate silent audio so every clip has the same
            # audio/video structure.
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                ]
            )

        # ---------------------------------------------------------
        # Video filters
        # ---------------------------------------------------------

        video_filters = [
            (
                f"scale={width}:{height}:"
                f"force_original_aspect_ratio=decrease"
            ),
            (
                f"pad={width}:{height}:"
                f"(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "format=yuv420p",
        ]

        if transition == "fade":
            fade_duration = min(0.5, duration / 2)

            if fade_duration > 0:
                fade_out_start = max(
                    0.0,
                    duration - fade_duration,
                )

                video_filters.append(
                    f"fade=t=in:st=0:d={fade_duration}"
                )

                video_filters.append(
                    f"fade=t=out:"
                    f"st={fade_out_start}:"
                    f"d={fade_duration}"
                )

        video_filter = ",".join(video_filters)

        # ---------------------------------------------------------
        # Video encoding (memory-tuned)
        # ---------------------------------------------------------

        preset = self._get_preset(quality)

        command.extend(
            [
                "-vf",
                video_filter,
                "-r",
                str(fps),
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                "28",
                "-threads",
                "1",
                "-pix_fmt",
                "yuv420p",
            ]
        )

        # ---------------------------------------------------------
        # Audio encoding
        # ---------------------------------------------------------

        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-af",
                f"atrim=0:{duration:.3f},"
                f"asetpts=PTS-STARTPTS",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )

        _diag(
            "🎬 FFmpeg scene command: "
            + " ".join(command)
        )

        success = await self._run_ffmpeg(command)

        if not success:
            raise RuntimeError(
                f"FFmpeg failed while rendering scene: "
                f"{output_path.name}"
            )

        if not output_path.exists():
            raise RuntimeError(
                f"FFmpeg reported success but output does not exist: "
                f"{output_path}"
            )

        if output_path.stat().st_size <= 0:
            raise RuntimeError(
                f"FFmpeg reported success but output is empty: "
                f"{output_path}"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Single asset
    # ─────────────────────────────────────────────────────────────────────────

    async def _render_single_asset(
        self,
        project_id: uuid.UUID,
        timeline_data: dict,
        settings: RenderSettings,
        temp_dir: Path,
        output_path: Path,
        progress_callback: Optional[
            Callable[[float, str], Awaitable[None]]
        ] = None,
    ) -> Path:
        """
        Render a single input asset.
        """

        fps = int(settings.fps)
        width = int(settings.resolution_width)
        height = int(settings.resolution_height)
        quality = str(settings.quality)

        # ── Memory safety clamp ──────────────────────────────────────────
        width, height = self._clamp_resolution(width, height)

        asset = timeline_data.get("asset")

        if not asset:
            asset = timeline_data.get("video")

        if not asset:
            asset = timeline_data.get("input")

        if not asset:
            raise ValueError(
                "No scenes or input asset found in timeline_data"
            )

        asset_path = Path(str(asset))

        if not asset_path.exists():
            raise FileNotFoundError(
                f"Input asset does not exist: {asset_path}"
            )

        if asset_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Input asset is empty: {asset_path}"
            )

        preset = self._get_preset(quality)

        command = [
            self.ffmpeg_binary,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(asset_path),
            "-vf",
            (
                f"scale={width}:{height}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:"
                f"(ow-iw)/2:(oh-ih)/2:color=black,"
                f"format=yuv420p"
            ),
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            "28",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        _diag(
            "🎬 Starting single asset render"
        )

        success = await self._run_ffmpeg(command)

        if not success:
            raise RuntimeError(
                "FFmpeg failed while rendering single asset"
            )

        if not output_path.exists():
            raise RuntimeError(
                f"Single asset output was not created: {output_path}"
            )

        if output_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Single asset output is empty: {output_path}"
            )

        if progress_callback:
            try:
                await progress_callback(
                    0.95,
                    "اكتمل رندر الملف",
                )
            except Exception as exc:
                _diag_err(
                    f"⚠️ Progress callback failed: {exc}"
                )

        return output_path

    # ─────────────────────────────────────────────────────────────────────────
    # Thumbnail (matches RendererPort contract)
    # ─────────────────────────────────────────────────────────────────────────

    async def generate_thumbnail(
        self,
        video_path: Path,
        config: ThumbnailConfig,
        output_path: Path,
    ) -> Path:
        """
        Generate a thumbnail from a video.

        Signature matches RendererPort.generate_thumbnail:
            (video_path, config, output_path)
        """

        video_path = Path(video_path)
        output_path = Path(output_path)

        if not video_path.exists():
            raise FileNotFoundError(
                f"Video does not exist: {video_path}"
            )

        if video_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Video is empty: {video_path}"
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Grab frame at timestamp 0 by default.
        # `config` is accepted for compatibility with the port contract;
        # advanced thumbnail composition (title, logo, colors) can be
        # added later without changing this signature.
        timestamp = 0.0

        command = [
            self.ffmpeg_binary,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-ss",
            str(max(0.0, timestamp)),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]

        _diag(
            f"🖼️ Generating thumbnail: {output_path}"
        )

        success = await self._run_ffmpeg(command)

        if not success:
            raise RuntimeError(
                "FFmpeg failed while generating thumbnail"
            )

        if not output_path.exists():
            raise RuntimeError(
                f"Thumbnail was not created: {output_path}"
            )

        if output_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Thumbnail is empty: {output_path}"
            )

        _diag(
            f"✅ Thumbnail generated "
            f"({output_path.stat().st_size} bytes)"
        )

        return output_path

    # ─────────────────────────────────────────────────────────────────────────
    # FFmpeg execution
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_ffmpeg(
        self,
        cmd: list[str],
    ) -> bool:
        """
        Execute FFmpeg asynchronously.

        Important:
        - Does not block FastAPI's event loop.
        - Streams stderr while FFmpeg is running.
        - Logs PID and return code.
        - Handles timeout.
        - Handles cancellation.
        - Keeps a bounded stderr tail for diagnostics.
        """

        if not cmd:
            raise ValueError("FFmpeg command cannot be empty")

        command_text = " ".join(
            self._quote_command_argument(part)
            for part in cmd
        )

        _diag(
            f"🎬 FFmpeg exec:\n{command_text}"
        )

        process: Optional[asyncio.subprocess.Process] = None

        stderr_lines: list[str] = []

        max_stderr_lines = 200

        async def read_stderr(
            stream: Optional[asyncio.StreamReader],
        ) -> None:
            if stream is None:
                return

            try:
                while True:
                    line = await stream.readline()

                    if not line:
                        break

                    decoded = line.decode(
                        "utf-8",
                        errors="replace",
                    ).rstrip()

                    if not decoded:
                        continue

                    stderr_lines.append(decoded)

                    if len(stderr_lines) > max_stderr_lines:
                        del stderr_lines[
                            : len(stderr_lines) - max_stderr_lines
                        ]

                    # Keep diagnostic output visible.
                    _diag(
                        f"🎬 FFmpeg | {decoded}"
                    )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                _diag_err(
                    f"⚠️ Failed reading FFmpeg stderr: {exc}"
                )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            _diag(
                f"🎬 FFmpeg process started "
                f"(pid={process.pid})"
            )

            stderr_task = asyncio.create_task(
                read_stderr(process.stderr)
            )

            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=self.timeout,
                )

            except asyncio.TimeoutError:
                _diag_err(
                    f"⏱️ FFmpeg timeout after "
                    f"{self.timeout}s "
                    f"(pid={process.pid})"
                )

                try:
                    process.terminate()
                except ProcessLookupError:
                    pass

                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=10,
                    )
                except asyncio.TimeoutError:
                    _diag_err(
                        "⚠️ FFmpeg did not terminate gracefully; "
                        "killing process"
                    )

                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass

                    await process.wait()

                return False

            finally:
                try:
                    await asyncio.wait_for(
                        stderr_task,
                        timeout=10,
                    )
                except asyncio.TimeoutError:
                    _diag_err(
                        "⚠️ FFmpeg stderr reader timeout"
                    )
                    stderr_task.cancel()

                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass

            return_code = process.returncode

            _diag(
                f"🎬 FFmpeg process finished "
                f"(pid={process.pid}, rc={return_code})"
            )

            if return_code != 0:
                stderr_tail = "\n".join(
                    stderr_lines[-80:]
                )

                _diag_err(
                    "💥 FFmpeg failed "
                    f"(rc={return_code})\n"
                    f"STDERR tail:\n{stderr_tail}"
                )

                return False

            _diag(
                "✅ FFmpeg OK "
                f"(pid={process.pid}, rc=0)"
            )

            return True

        except asyncio.CancelledError:
            _diag_err(
                "🛑 FFmpeg execution was cancelled"
            )

            if process is not None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass

                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=5,
                    )
                except Exception:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass

            raise

        except FileNotFoundError as exc:
            _diag_err(
                f"💥 FFmpeg binary not found: "
                f"{self.ffmpeg_binary}"
            )
            _diag_err(str(exc))
            return False

        except PermissionError as exc:
            _diag_err(
                "💥 Permission denied while starting FFmpeg"
            )
            _diag_err(str(exc))
            return False

        except Exception as exc:
            _diag_err(
                f"💥 Unexpected FFmpeg execution error: {exc}"
            )
            _diag_err(traceback.format_exc())
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _clamp_resolution(
        cls,
        width: int,
        height: int,
    ) -> tuple[int, int]:
        """
        Clamp resolution to MAX_PIXELS to avoid OOM on
        memory-constrained hosts (Render free tier = 512MB RAM).

        If the requested resolution exceeds the limit, scale it down
        proportionally while preserving the aspect ratio, and round
        to even numbers (required by libx264).
        """

        requested_pixels = width * height

        if requested_pixels <= cls.MAX_PIXELS:
            return width, height

        # Scale down proportionally
        scale = (cls.MAX_PIXELS / requested_pixels) ** 0.5

        new_width = int(width * scale)
        new_height = int(height * scale)

        # libx264 requires even dimensions
        new_width = new_width - (new_width % 2)
        new_height = new_height - (new_height % 2)

        # Safety floor
        new_width = max(new_width, 320)
        new_height = max(new_height, 180)

        _diag(
            f"⚠️ Clamping resolution from "
            f"{width}x{height} ({requested_pixels} px) to "
            f"{new_width}x{new_height} "
            f"({new_width * new_height} px) — memory safety"
        )

        return new_width, new_height

    @staticmethod
    def _get_preset(quality: str) -> str:
        """
        Convert application quality setting to x264 preset.

        Note: On memory-constrained hosts (e.g. Render free tier
        with 512MB RAM), only ultrafast/veryfast are safe for 720p+.
        Slower presets cause OOM kills.
        """

        quality = str(quality or "medium").lower()

        presets = {
            "very_low": "ultrafast",
            "low": "ultrafast",
            "medium": "ultrafast",
            "high": "veryfast",
            "very_high": "veryfast",
        }

        return presets.get(
            quality,
            "ultrafast",
        )

    @staticmethod
    def _quote_command_argument(value: str) -> str:
        """
        Make command arguments readable in diagnostic logs.
        """

        value = str(value)

        if any(
            char in value
            for char in (
                " ",
                "\t",
                "\n",
                "'",
                '"',
            )
        ):
            return repr(value)

        return value
