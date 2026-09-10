"""Application service for Production / Render use cases."""
import asyncio
import inspect
import logging
import re
import traceback
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from core.domain.rendering.render_job import RenderJob
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from infrastructure.database.session import get_session_factory
from plugins.registry import PluginRegistry
from shared.domain_events import (
    ProductionStarted, RenderProgressUpdated,
    RenderCompleted, RenderFailed,
)
from shared.exceptions import ProjectNotFoundError, RenderJobNotFoundError
from shared.ports.renderer_port import RenderSettings
from config.settings import settings

logger = logging.getLogger(__name__)

# Global registry for active render tasks (job_id -> asyncio.Task)
_active_renders: dict[str, asyncio.Task] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic helpers
# ─────────────────────────────────────────────────────────────────────────────

def _diag(msg: str) -> None:
    """Print + log a diagnostic message immediately (flushed)."""
    print(msg, flush=True)
    logger.info(msg)


def _diag_err(msg: str, exc: Optional[BaseException] = None) -> None:
    """Print + log an error with optional traceback."""
    print(msg, flush=True)
    if exc is not None:
        logger.error(msg, exc_info=exc)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    else:
        logger.error(msg)


def _task_done_callback(task: asyncio.Task) -> None:
    """Log any exception raised by a background render task."""
    job_hint = "unknown"
    try:
        # Best-effort: find which job this task belongs to
        for jid, t in list(_active_renders.items()):
            if t is task:
                job_hint = jid
                break
    except Exception:
        pass

    if task.cancelled():
        _diag(f"🛑 Render task cancelled: job={job_hint}")
        return

    exc = task.exception()
    if exc is not None:
        _diag_err(f"💥 Render task crashed: job={job_hint} error={exc!r}", exc)
    else:
        _diag(f"✅ Render task finished cleanly: job={job_hint}")


# ─────────────────────────────────────────────────────────────────────────────
# ProductionService
# ─────────────────────────────────────────────────────────────────────────────

class ProductionService:
    def __init__(
        self,
        project_repo: SQLProjectRepository,
        job_repo: SQLRenderJobRepository,
        event_bus: InMemoryEventBus,
        plugin_registry: PluginRegistry,
    ):
        self._projects = project_repo
        self._jobs = job_repo
        self._bus = event_bus
        self._registry = plugin_registry

    # ── Save project data ────────────────────────────────────────────────────
    async def save_project_data(
        self,
        project_id: uuid.UUID,
        clips: List[Dict[str, Any]],
        layers: List[Dict[str, Any]],
        total_duration: float,
        media_files: List[Dict[str, Any]],
    ) -> None:
        """
        Save project data from client (clips, layers, media files).
        Called before rendering if the client sends full project data.
        """
        try:
            project = await self._projects.get(project_id)
            if not project:
                raise ProjectNotFoundError(f"Project {project_id} not found")

            project_data = project.to_dict() if hasattr(project, "to_dict") else {}

            existing_data = project_data.get("data", {}) or {}
            existing_data.update({
                "clips": clips,
                "layers": layers,
                "total_duration": total_duration,
                "media_files": media_files,
                "updated_at": datetime.utcnow().isoformat(),
            })

            if hasattr(project, "update_data"):
                project.update_data(existing_data)
            else:
                project.data = existing_data

            await self._projects.save(project)
            logger.info(
                "✅ Project data saved: %s with %d clips, %d layers",
                project_id, len(clips), len(layers),
            )
        except Exception as e:
            _diag_err(f"❌ Failed to save project data: {e}", e)
            raise

    # ── Start render ─────────────────────────────────────────────────────────
    async def start_render(
        self,
        project_id: uuid.UUID,
        render_settings: Optional[dict] = None,
        project_data: Optional[Dict[str, Any]] = None,
    ) -> RenderJob:
        """
        Start a render job for a project.

        Args:
            project_id: ID of the project to render.
            render_settings: Render settings (fps, width, height, quality).
            project_data: Optional project data from client (clips, layers, etc.).
        """
        _diag(f"🔥 start_render called: project_id={project_id}")
        _diag(f"🔥 render_settings={render_settings}")
        _diag(f"🔥 project_data keys={list(project_data.keys()) if project_data else None}")

        # Get project from database
        try:
            project = await self._projects.get(project_id)
        except Exception as e:
            _diag_err(f"💥 project_repo.get failed: {e}", e)
            raise

        _diag(f"🔥 project found={project is not None}")
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        # If client sent project data, update the project first
        if project_data:
            try:
                await self.save_project_data(
                    project_id=project_id,
                    clips=project_data.get("clips", []),
                    layers=project_data.get("layers", []),
                    total_duration=project_data.get("total_duration", 10.0),
                    media_files=project_data.get("media_files", []),
                )
                project = await self._projects.get(project_id)
                _diag(f"🔥 project refreshed after save_project_data")
            except Exception as e:
                _diag_err(f"⚠️ Could not save project data: {e}", e)

        # ====== Reset project status if already in production ======
        if hasattr(project, "status"):
            current_status = project.status
            if current_status == "in_production":
                logger.info(
                    "🔄 Project %s is already in production. Resetting status.",
                    project_id,
                )
                if hasattr(project, "reset_production"):
                    project.reset_production()
                elif hasattr(project, "mark_draft"):
                    project.mark_draft()
                else:
                    try:
                        project.status = "draft"
                    except Exception as e:
                        _diag_err(f"⚠️ Could not reset project status: {e}", e)

        # ====== Inspect RenderJob signature (once) ======
        _diag(f"🔥 RenderJob.__init__ signature: {inspect.signature(RenderJob.__init__)}")

        # ====== Create RenderJob correctly ======
        renderer = (render_settings or {}).get("renderer", "ffmpeg")

        job = self._create_render_job(project_id, renderer, render_settings or {})
        _diag(f"🔥 job created id={job.id} renderer={renderer}")

        # ====== Start production ======
        if hasattr(project, "start_production"):
            try:
                project.start_production()
            except Exception as e:
                _diag_err(f"⚠️ Could not start production: {e}", e)
                if hasattr(project, "status"):
                    try:
                        project.status = "in_production"
                    except Exception:
                        pass

        # Save job and project
        try:
            await self._jobs.save(job)
            await self._projects.save(project)
            _diag(f"🔥 job + project saved")
        except Exception as e:
            _diag_err(f"💥 Failed to save job/project: {e}", e)
            raise

        # Publish event
        try:
            await self._bus.publish(
                ProductionStarted(project_id=project_id, render_job_id=job.id)
            )
        except Exception as e:
            _diag_err(f"⚠️ Failed to publish ProductionStarted: {e}", e)

        # Build project_data dict for the background task
        try:
            background_data = project.to_dict() if hasattr(project, "to_dict") else {"id": str(project_id)}
        except Exception as e:
            _diag_err(f"⚠️ project.to_dict() failed: {e}", e)
            background_data = {"id": str(project_id)}

        # Ensure 'id' is present (critical for _run_render)
        if "id" not in background_data:
            background_data["id"] = str(project_id)

        _diag(f"🔥 background_data keys={list(background_data.keys())}")

        # Start background render task
        try:
            task = asyncio.create_task(
                self._run_render(job.id, background_data),
                name=f"render-{job.id}",
            )
        except Exception as e:
            _diag_err(f"💥 asyncio.create_task failed: {e}", e)
            raise

        _active_renders[str(job.id)] = task
        task.add_done_callback(_task_done_callback)
        _diag(f"🚀 Render job started: {job.id} for project {project_id}")

        return job

    # ── Factory helper for RenderJob ─────────────────────────────────────────
    def _create_render_job(
        self,
        project_id: uuid.UUID,
        renderer: str,
        settings_dict: dict,
    ) -> RenderJob:
        """
        Create a RenderJob using whatever signature it actually has.
        Tries several strategies to be resilient to domain-model variations.
        """
        # Strategy 1: full kwargs
        try:
            return RenderJob(
                project_id=project_id,
                renderer=renderer,
                settings=settings_dict,
            )
        except TypeError as e:
            _diag(f"⚠️ RenderJob(project_id, renderer, settings) failed: {e}")

        # Strategy 2: project_id only, then set attributes
        try:
            job = RenderJob(project_id=project_id)
            try:
                job.renderer = renderer
            except Exception:
                pass
            try:
                job.settings = settings_dict
            except Exception:
                pass
            return job
        except TypeError as e:
            _diag(f"⚠️ RenderJob(project_id=...) failed: {e}")

        # Strategy 3: keyword-only via factory method
        for factory_name in ("create", "new", "for_project"):
            factory = getattr(RenderJob, factory_name, None)
            if callable(factory):
                try:
                    job = factory(project_id=project_id)
                    try:
                        job.renderer = renderer
                    except Exception:
                        pass
                    try:
                        job.settings = settings_dict
                    except Exception:
                        pass
                    return job
                except Exception as e:
                    _diag(f"⚠️ RenderJob.{factory_name}(...) failed: {e}")

        # Strategy 4: positional
        try:
            job = RenderJob(project_id)
            try:
                job.renderer = renderer
            except Exception:
                pass
            try:
                job.settings = settings_dict
            except Exception:
                pass
            return job
        except Exception as e:
            _diag_err(f"💥 All RenderJob construction strategies failed: {e}", e)
            raise

    # ── Background render ────────────────────────────────────────────────────
    async def _run_render(self, job_id: uuid.UUID, project_data: dict) -> None:
        """Background render task — runs independently of the request."""
        _diag(f"🔥 _run_render START job_id={job_id}")
        factory = None

        async def save_progress(progress: float, stage: str) -> None:
            try:
                async with factory() as session:
                    from infrastructure.repositories.sql_render_job_repository import (
                        SQLRenderJobRepository,
                    )
                    repo = SQLRenderJobRepository(session)
                    j = await repo.get(job_id)
                    if j:
                        j.update_progress(progress, stage)
                        await repo.save(j)
                        await session.commit()
                await self._bus.publish(
                    RenderProgressUpdated(job_id=job_id, progress=progress, stage=stage)
                )
            except Exception as e:
                _diag_err(f"⚠️ save_progress failed ({progress}%, {stage}): {e}", e)

        try:
            factory = get_session_factory()
            _diag(f"🔥 session factory obtained: {factory}")

            async with factory() as session:
                from infrastructure.repositories.sql_render_job_repository import (
                    SQLRenderJobRepository,
                )
                job_repo = SQLRenderJobRepository(session)

                job = await job_repo.get(job_id)
                if not job:
                    _diag_err(f"💥 job not found in _run_render: {job_id}")
                    return

                job.start()
                await job_repo.save(job)
                await session.commit()

            # ====== Extract project_id once ======
            project_id_str = project_data.get("id")
            if not project_id_str:
                project_id_str = str(job.project_id) if job else str(job_id)
            _diag(f"🔥 project_id_str={project_id_str}")

            try:
                project_id_obj = uuid.UUID(str(project_id_str))
            except Exception as e:
                _diag_err(f"💥 Invalid project_id '{project_id_str}': {e}", e)
                raise

            # ── Renderer ─────────────────────────────────────────────────────
            try:
                renderer = self._registry.get_renderer()
                _diag(f"🔥 renderer obtained: {renderer}")
            except Exception as e:
                _diag_err(f"💥 registry.get_renderer() failed: {e}", e)
                raise

            temp_dir = settings.TEMP_DIR / str(job_id)
            temp_dir.mkdir(parents=True, exist_ok=True)
            _diag(f"🔥 temp_dir={temp_dir}")

            # Get render settings from the job
            job_settings = getattr(job, "settings", None) or {}
            fps = job_settings.get("fps", 30)
            width = job_settings.get("width", 1920)
            height = job_settings.get("height", 1080)
            _diag(f"🔥 job_settings fps={fps} width={width} height={height}")

            rs = RenderSettings(
                fps=fps,
                resolution_width=width,
                resolution_height=height,
            )

            await save_progress(5.0, "تحليل النص وتقسيمه إلى مشاهد")

            # ── Build scenes from project script ─────────────────────────────
            script = project_data.get("script", "")
            title = project_data.get("title", "")
            brand_colors = project_data.get("brand_colors", {}) or {}
            brand_color = brand_colors.get("primary") if brand_colors else None

            project_data_data = project_data.get("data", {}) or {}
            clips = project_data_data.get("clips", []) or []

            if clips:
                raw_scenes = self._build_scenes_from_clips(clips)
                _diag(f"📽️ Using {len(raw_scenes)} scenes from client clips")
            else:
                raw_scenes = _split_script_to_scenes(script, title)
                _diag(f"📝 Using {len(raw_scenes)} scenes from script")

            await save_progress(10.0, f"توليد {len(raw_scenes)} مشهد")

            # ── Resolve active HF models (if any) ────────────────────────────
            try:
                voice_plugin = await _resolve_voice_plugin(self._registry)
                _diag(f"🔥 voice_plugin={voice_plugin}")
            except Exception as e:
                _diag_err(f"💥 _resolve_voice_plugin failed: {e}", e)
                raise

            try:
                image_generator = await _resolve_image_generator(rs)
                _diag(f"🔥 image_generator={image_generator}")
            except Exception as e:
                _diag_err(f"💥 _resolve_image_generator failed: {e}", e)
                raise

            from shared.ports.voice_port import VoiceConfig
            voice_config = VoiceConfig(language="ar", speed=1.0, pitch=1.0)

            scenes_data: list[dict] = []
            total = len(raw_scenes)

            for i, scene_text in enumerate(raw_scenes):
                pct = 10.0 + (i / max(total, 1)) * 50.0
                await save_progress(pct, f"معالجة المشهد {i + 1}/{total}")

                # TTS audio
                audio_path = temp_dir / f"audio_{i:04d}.mp3"
                try:
                    voice_result = await voice_plugin.generate(
                        text=scene_text,
                        config=voice_config,
                        output_path=audio_path,
                    )
                    actual_audio = voice_result.audio_path
                    duration = voice_result.duration
                except Exception as e:
                    _diag_err(f"⚠️ TTS failed for scene {i}: {e}", e)
                    actual_audio = None
                    words = len(scene_text.split())
                    duration = max(3.0, (words / 150) * 60)

                # Scene image
                image_path = temp_dir / f"scene_{i:04d}.jpg"
                try:
                    await image_generator.generate_scene_image(
                        text=scene_text,
                        output_path=image_path,
                        scene_index=i,
                        title=title,
                        brand_color=brand_color,
                    )
                except Exception as e:
                    _diag_err(f"⚠️ Image gen failed for scene {i}: {e}", e)
                    image_path = None

                scenes_data.append({
                    "text": scene_text,
                    "image_path": str(image_path) if image_path else "",
                    "audio_path": str(actual_audio) if actual_audio else "",
                    "duration": duration,
                    "transition": "fade",
                })

            await save_progress(62.0, "تركيب الفيديو النهائي")

            # ── Render ───────────────────────────────────────────────────────
            _diag(f"🔥 Calling renderer.render(...) for job={job_id}")
            result = await renderer.render(
                project_id=project_id_obj,
                timeline_data={"scenes": scenes_data},
                assets={},
                settings=rs,
                temp_dir=temp_dir,
                progress_callback=save_progress,
            )
            _diag(f"🔥 renderer.render done output={result.output_path}")

            # ── Thumbnail ────────────────────────────────────────────────────
            output_dir = settings.EXPORTS_DIR / str(job_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            thumb_path = settings.THUMBNAILS_DIR / f"{job_id}.jpg"

            from shared.ports.renderer_port import ThumbnailConfig
            try:
                await renderer.generate_thumbnail(
                    result.output_path,
                    ThumbnailConfig(title=title),
                    thumb_path,
                )
                _diag(f"🔥 thumbnail generated: {thumb_path}")
            except Exception as e:
                _diag_err(f"⚠️ Thumbnail generation failed: {e}", e)

            await save_progress(100.0, "اكتمل")

            async with factory() as session:
                job_repo = SQLRenderJobRepository(session)
                proj_repo = SQLProjectRepository(session)
                job = await job_repo.get(job_id)
                project = await proj_repo.get(project_id_obj)
                if job:
                    job.complete(str(result.output_path))
                    await job_repo.save(job)
                if project:
                    try:
                        project.mark_rendered()
                    except Exception as e:
                        _diag_err(f"⚠️ project.mark_rendered failed: {e}", e)
                    await proj_repo.save(project)
                await session.commit()

            try:
                await self._bus.publish(RenderCompleted(
                    job_id=job_id,
                    project_id=project_id_obj,
                    output_path=str(result.output_path),
                ))
            except Exception as e:
                _diag_err(f"⚠️ RenderCompleted publish failed: {e}", e)

            _diag(f"✅ Render completed: job={job_id} output={result.output_path}")

        except asyncio.CancelledError:
            _diag(f"🛑 _run_render cancelled: job={job_id}")
            # Mark job as cancelled in DB
            if factory is not None:
                try:
                    async with factory() as session:
                        job_repo = SQLRenderJobRepository(session)
                        j = await job_repo.get(job_id)
                        if j and hasattr(j, "cancel"):
                            j.cancel()
                            await job_repo.save(j)
                            await session.commit()
                except Exception as e:
                    _diag_err(f"⚠️ Could not mark cancelled job: {e}", e)
            raise

        except Exception as exc:
            _diag_err(f"💥 Render failed: job={job_id} error={exc!r}", exc)

            if factory is not None:
                try:
                    async with factory() as session:
                        job_repo = SQLRenderJobRepository(session)
                        proj_repo = SQLProjectRepository(session)
                        job = await job_repo.get(job_id)
                        project = None
                        try:
                            project = await proj_repo.get(
                                uuid.UUID(str(project_data.get("id") or job_id))
                            )
                        except Exception as e:
                            _diag_err(f"⚠️ Could not fetch project for failure: {e}", e)

                        if job:
                            job.fail(str(exc))
                            await job_repo.save(job)
                        if project:
                            try:
                                project.mark_failed()
                            except Exception as e:
                                _diag_err(f"⚠️ project.mark_failed failed: {e}", e)
                            await proj_repo.save(project)
                        await session.commit()
                except Exception as inner:
                    _diag_err(f"💥 Could not mark job as failed: {inner}", inner)

            try:
                await self._bus.publish(RenderFailed(
                    job_id=job_id,
                    project_id=uuid.UUID(str(project_data.get("id") or job_id)),
                    error=str(exc),
                ))
            except Exception as e:
                _diag_err(f"⚠️ RenderFailed publish failed: {e}", e)

        finally:
            _active_renders.pop(str(job_id), None)
            _diag(f"🔥 _run_render END job_id={job_id}")

    # ── Scene builder from clips ─────────────────────────────────────────────
    def _build_scenes_from_clips(self, clips: List[Dict[str, Any]]) -> List[str]:
        """Convert client clips to scene text list."""
        scenes: list[str] = []
        for clip in clips:
            clip_type = clip.get("type", "")
            if clip_type == "text":
                content = clip.get("content", "")
                if content:
                    scenes.append(content)
                else:
                    scenes.append(clip.get("title", "نص"))
            elif clip_type == "image":
                scenes.append(f"[صورة] {clip.get('title', 'صورة')}")
            elif clip_type == "video":
                scenes.append(f"[فيديو] {clip.get('title', 'فيديو')}")
            elif clip_type == "audio":
                scenes.append(f"[صوت] {clip.get('title', 'صوت')}")
            else:
                scenes.append(clip.get("title", "مقطع"))

        if not scenes:
            scenes = ["مشهد بدون نص"]

        return scenes

    # ── Job queries ──────────────────────────────────────────────────────────
    async def get_job(self, job_id: uuid.UUID) -> RenderJob:
        """Get a render job by ID."""
        job = await self._jobs.get(job_id)
        if not job:
            raise RenderJobNotFoundError(f"Render job {job_id} not found")
        return job

    async def list_jobs(self, limit: int = 20) -> list[RenderJob]:
        """List recent render jobs."""
        return await self._jobs.list_recent(limit=limit)

    async def cancel_job(self, job_id: uuid.UUID) -> None:
        """Cancel a running render job."""
        task = _active_renders.get(str(job_id))
        if task and not task.done():
            task.cancel()
            _diag(f"🛑 Cancelled render task: {job_id}")

        job = await self._jobs.get(job_id)
        if job and hasattr(job, "status") and job.status in ["pending", "processing"]:
            try:
                job.cancel()
                await self._jobs.save(job)
                _diag(f"🛑 Marked job as cancelled in DB: {job_id}")
            except Exception as e:
                _diag_err(f"⚠️ Could not mark job as cancelled: {e}", e)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _split_script_to_scenes(script: str, title: str = "") -> list[str]:
    """
    Split project script into scenes.
    Strategy:
    1. Split by double newline (explicit paragraphs).
    2. If only one paragraph, split by sentence-ending punctuation.
    3. If script is empty, create a single title card.
    """
    if not script or not script.strip():
        return [title or "مشهد بدون نص"]

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", script.strip()) if p.strip()]

    if len(paragraphs) >= 2:
        return paragraphs

    sentences = re.split(r"(?<=[.!?؟،\n])\s+", paragraphs[0])
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return [paragraphs[0]]

    scenes, current, current_words = [], [], 0
    for sentence in sentences:
        words = len(sentence.split())
        if current_words + words > 80 and current:
            scenes.append(" ".join(current))
            current, current_words = [], 0
        current.append(sentence)
        current_words += words

    if current:
        scenes.append(" ".join(current))

    return scenes or [script.strip()]


async def _resolve_voice_plugin(registry):
    """Return active HF TTS plugin if configured, else fallback to edge_tts."""
    try:
        from infrastructure.database.session import get_session_factory
        from infrastructure.repositories.sql_hf_model_repository import SQLHFModelRepository

        factory = get_session_factory()
        async with factory() as session:
            repo = SQLHFModelRepository(session)
            active = await repo.get_active("tts")
            if active:
                from plugins.hf.hf_tts_plugin import HFTTSPlugin
                _diag(f"✅ Using HF TTS model: {active.hf_model_id}")
                return HFTTSPlugin(model_id=active.hf_model_id, config=active.config)
    except Exception as e:
        _diag_err(f"⚠️ HF TTS lookup failed: {e} — using edge_tts", e)

    try:
        return registry.get_voice_provider()
    except Exception as e:
        _diag_err(f"💥 registry.get_voice_provider() failed: {e}", e)
        raise


async def _resolve_image_generator(rs: RenderSettings):
    """Return active HF image plugin if configured, else fallback to Pillow."""
    try:
        from infrastructure.database.session import get_session_factory
        from infrastructure.repositories.sql_hf_model_repository import SQLHFModelRepository

        factory = get_session_factory()
        async with factory() as session:
            repo = SQLHFModelRepository(session)
            active = await repo.get_active("text-to-image")
            if active:
                from plugins.hf.hf_image_plugin import HFImagePlugin
                _diag(f"✅ Using HF image model: {active.hf_model_id}")
                return _HFImageAdapter(
                    HFImagePlugin(model_id=active.hf_model_id, config=active.config),
                    rs,
                )
    except Exception as e:
        _diag_err(f"⚠️ HF image lookup failed: {e} — using Pillow", e)

    return _get_pillow_generator(rs)


def _get_pillow_generator(rs: RenderSettings):
    from plugins.image_gen.pillow_generator import SceneImageGenerator
    return SceneImageGenerator(
        width=rs.resolution_width,
        height=rs.resolution_height,
    )


class _HFImageAdapter:
    """Wraps HFImagePlugin to match SceneImageGenerator.generate_scene_image() interface."""

    def __init__(self, plugin, rs: RenderSettings):
        self._plugin = plugin
        self._rs = rs
        self._fallback = _get_pillow_generator(rs)

    async def generate_scene_image(
        self,
        text,
        output_path,
        scene_index=0,
        title="",
        brand_color=None,
        logo_path=None,
    ):
        prompt = f"{title}: {text}" if title else text
        try:
            return await self._plugin.generate_image(
                prompt=prompt,
                output_path=output_path,
                width=min(self._rs.resolution_width, 1024),
                height=min(self._rs.resolution_height, 576),
            )
        except Exception as e:
            _diag_err(f"⚠️ HF image adapter failed: {e} — using Pillow", e)
            return await self._fallback.generate_scene_image(
                text=text,
                output_path=output_path,
                scene_index=scene_index,
                title=title,
                brand_color=brand_color,
            )
