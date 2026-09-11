
import asyncio
import logging
import subprocess
import traceback
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Optional

from shared.ports.renderer import RendererPort


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
    """

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
            f"(ffmpeg={self.ffmpeg_binary}, timeout={self.timeout}s)"
        )

    async def render(
        self,
        project_id: uuid.UUID,
        timeline_data: dict,
        temp_dir: Path,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Path:
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

        scenes = timeline_data.get("scenes", [])

        if scenes:
            _diag(f"🎬 Found {len(scenes)} scenes")
            return await self._render_scenes(
                project_id=project_id,
                scenes=scenes,
                timeline_data=timeline_data,
                temp_dir=temp_dir,
                output_path=output_path,
                progress_callback=progress_callback,
            )

        _diag("🎬 No scenes found, using single asset renderer")

        return await self._render_single_asset(
            project_id=project_id,
            timeline_data=timeline_data,
            temp_dir=temp_dir,
            output_path=output_path,
            progress_callback=progress_callback,
        )

    async def _render_scenes(
        self,
        project_id: uuid.UUID,
        scenes: list,
        timeline_data: dict,
        temp_dir: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Path:
        """
        Render every scene into a separate MP4 and concatenate them.

        A failed scene is treated as a fatal render error.
        This avoids silently producing incomplete videos.
        """

        settings = timeline_data.get("settings", {}) or {}

        fps = int(settings.get("fps", 30))
        width = int(settings.get("width", 1920))
        height = int(settings.get("height", 1080))
        quality = str(settings.get("quality", "medium"))

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
                progress = (index + 1) / total_scenes

                try:
                    await progress_callback(progress)
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
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
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
        """

        output_path.parent.mkdir(parents=True, exist_ok=True)

        text = str(scene.get("text", "") or "")
        image_path = scene.get("image")
        audio_path = scene.get("audio")

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

        if image_path:
            image = Path(image_path)

            if not image.exists():
                raise FileNotFoundError(
                    f"Scene image does not exist: {image}"
                )

            if image.stat().st_size <= 0:
                raise RuntimeError(
                    f"Scene image is empty: {image}"
                )

            command.extend(
                [
                    "-loop",
                    "1",
                    "-i",
                    str(image),
                ]
            )

        else:
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
            audio = Path(audio_path)

            if not audio.exists():
                raise FileNotFoundError(
                    f"Scene audio does not exist: {audio}"
                )

            if audio.stat().st_size <= 0:
                raise RuntimeError(
                    f"Scene audio is empty: {audio}"
                )

            command.extend(
                [
                    "-i",
                    str(audio),
                ]
            )

            has_audio = True

        else:
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
        # Video encoding
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
                "23",
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
                "192k",
                "-ar",
                "44100",
                "-ac",
                "2",
            ]
        )

        if has_audio:
            command.extend(
                [
                    "-af",
                    f"atrim=0:{duration:.3f},"
                    f"asetpts=PTS-STARTPTS",
                ]
            )
        else:
            command.extend(
                [
                    "-af",
                    f"atrim=0:{duration:.3f},"
                    f"asetpts=PTS-STARTPTS",
                ]
            )

        command.extend(
            [
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

    async def _render_single_asset(
        self,
        project_id: uuid.UUID,
        timeline_data: dict,
        temp_dir: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Path:
        """
        Render a single input asset.
        """

        settings = timeline_data.get("settings", {}) or {}

        fps = int(settings.get("fps", 30))
        width = int(settings.get("width", 1920))
        height = int(settings.get("height", 1080))
        quality = str(settings.get("quality", "medium"))

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
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
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
                await progress_callback(1.0)
            except Exception as exc:
                _diag_err(
                    f"⚠️ Progress callback failed: {exc}"
                )

        return output_path

    async def generate_thumbnail(
        self,
        video_path: Path,
        output_path: Path,
        timestamp: float = 0.0,
    ) -> Path:
        """
        Generate a thumbnail from a video.
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

    @staticmethod
    def _get_preset(quality: str) -> str:
        """
        Convert application quality setting to x264 preset.
        """

        quality = str(quality or "medium").lower()

        presets = {
            "very_low": "ultrafast",
            "low": "veryfast",
            "medium": "fast",
            "high": "medium",
            "very_high": "slow",
        }

        return presets.get(
            quality,
            "fast",
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

