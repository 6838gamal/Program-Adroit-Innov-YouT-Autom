"""Application service for Production / Render use cases.

✅ دعم كامل لمصادر الصوت:
   1. clip.type == "audio"     → clip.url (TTS / Edge TTS / Cloned / Recording)
   2. clip.metadata.audioRecordings[] → تسجيلات مرفقة بـ image/video clip
   3. لا TTS تلقائي — الصوت فقط من مصادر المُستخدم.
"""
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
from shared.ports.renderer_port import RenderSettings, ThumbnailConfig
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
            if not isinstance(existing_data, dict):
                existing_data = {}

            # ✅ احتفظ بـ cloned_voices المحفوظة (لا تحذفها)
            preserved_keys = ["cloned_voices", "voiceovers", "rendered_at",
                              "video_url", "video_path", "thumbnail",
                              "thumbnail_path", "output_local_path"]

            preserved = {
                k: existing_data.get(k)
                for k in preserved_keys
                if k in existing_data
            }

            existing_data.update({
                "clips": clips,
                "layers": layers,
                "total_duration": total_duration,
                "media_files": media_files,
                "updated_at": datetime.utcnow().isoformat(),
            })

            # أعد القيم المحفوظة
            for k, v in preserved.items():
                if v is not None and k not in ["rendered_at", "video_url", "video_path",
                                                "thumbnail", "thumbnail_path",
                                                "output_local_path"]:
                    existing_data[k] = v

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
        """Start a render job for a project."""
        _diag(f"🔥 start_render called: project_id={project_id}")
        _diag(f"🔥 render_settings={render_settings}")
        _diag(f"🔥 project_data keys={list(project_data.keys()) if project_data else None}")

        try:
            project = await self._projects.get(project_id)
        except Exception as e:
            _diag_err(f"💥 project_repo.get failed: {e}", e)
            raise

        _diag(f"🔥 project found={project is not None}")
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

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
            status_value = getattr(current_status, "value", current_status)
            if status_value == "in_production":
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

        _diag(f"🔥 RenderJob.__init__ signature: {inspect.signature(RenderJob.__init__)}")

        renderer = (render_settings or {}).get("renderer", "ffmpeg")
        job = self._create_render_job(project_id, renderer, render_settings or {})
        _diag(f"🔥 job created id={job.id} renderer={renderer}")

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

        try:
            await self._jobs.save(job)
            await self._projects.save(project)
            _diag(f"🔥 job + project saved")
        except Exception as e:
            _diag_err(f"💥 Failed to save job/project: {e}", e)
            raise

        try:
            await self._bus.publish(
                ProductionStarted(project_id=project_id, render_job_id=job.id)
            )
        except Exception as e:
            _diag_err(f"⚠️ Failed to publish ProductionStarted: {e}", e)

        try:
            background_data = project.to_dict() if hasattr(project, "to_dict") else {"id": str(project_id)}
        except Exception as e:
            _diag_err(f"⚠️ project.to_dict() failed: {e}", e)
            background_data = {"id": str(project_id)}

        if "id" not in background_data:
            background_data["id"] = str(project_id)

        _diag(f"🔥 background_data keys={list(background_data.keys())}")

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
        """Create a RenderJob using whatever signature it actually has."""
        try:
            return RenderJob(
                project_id=project_id,
                renderer=renderer,
                settings=settings_dict,
            )
        except TypeError as e:
            _diag(f"⚠️ RenderJob(project_id, renderer, settings) failed: {e}")

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

            project_id_str = project_data.get("id")
            if not project_id_str:
                project_id_str = str(job.project_id) if job else str(job_id)
            _diag(f"🔥 project_id_str={project_id_str}")

            try:
                project_id_obj = uuid.UUID(str(project_id_str))
            except Exception as e:
                _diag_err(f"💥 Invalid project_id '{project_id_str}': {e}", e)
                raise

            try:
                renderer = self._registry.get_renderer()
                _diag(f"🔥 renderer obtained: {renderer}")
            except Exception as e:
                _diag_err(f"💥 registry.get_renderer() failed: {e}", e)
                raise

            temp_dir = settings.TEMP_DIR / str(job_id)
            temp_dir.mkdir(parents=True, exist_ok=True)
            _diag(f"🔥 temp_dir={temp_dir}")

            job_settings = getattr(job, "settings", None) or {}
            fps = job_settings.get("fps", 30)
            width = job_settings.get("width", 1920)
            height = job_settings.get("height", 1080)
            quality = job_settings.get("quality", "medium")
            _diag(f"🔥 job_settings fps={fps} width={width} height={height} quality={quality}")

            rs = RenderSettings(
                fps=fps,
                resolution_width=width,
                resolution_height=height,
                quality=quality,
            )

            await save_progress(5.0, "تحليل المشاهد")

            # ═══════════════════════════════════════════════════════════════
            # ── Build scenes from clips OR script ────────────────────────
            # ═══════════════════════════════════════════════════════════════
            script = project_data.get("script", "") or ""
            title = project_data.get("title", "") or ""
            brand_colors = project_data.get("brand_colors", {}) or {}
            brand_color = None
            if isinstance(brand_colors, dict):
                brand_color = brand_colors.get("primary")

            # ✅ ابحث عن clips في أماكن متعددة
            clips = []
            project_data_data = project_data.get("data", {}) or {}
            if isinstance(project_data_data, dict):
                clips = project_data_data.get("clips", []) or []

            # fallback: إذا لم توجد، ابحث في project_data مباشرة
            if not clips:
                clips = project_data.get("clips", []) or []

            _diag(f"🔥 Found {len(clips)} clips in project_data")

            # ✅ إحصائيات clips
            if clips:
                audio_clips_count = sum(
                    1 for c in clips
                    if isinstance(c, dict) and (c.get("type") or "").lower() == "audio"
                )
                image_clips_count = sum(
                    1 for c in clips
                    if isinstance(c, dict) and (c.get("type") or "").lower() == "image"
                )
                video_clips_count = sum(
                    1 for c in clips
                    if isinstance(c, dict) and (c.get("type") or "").lower() == "video"
                )
                text_clips_count = sum(
                    1 for c in clips
                    if isinstance(c, dict) and (c.get("type") or "").lower() == "text"
                )
                _diag(
                    f"🔥 Clips breakdown: audio={audio_clips_count}, "
                    f"image={image_clips_count}, video={video_clips_count}, "
                    f"text={text_clips_count}"
                )

            if clips:
                # ✅ scenes من clips (مع الصوت)
                scene_objects = self._build_scenes_from_clips(clips)
                _diag(f"📽️ Using {len(scene_objects)} scenes from client clips")
            else:
                # ⚠️ لا clips → مشهد واحد صامت
                _diag("⚠️ No clips found — creating single silent scene")
                scene_objects = [{
                    "text": "",
                    "type": "text",
                    "media_url": None,
                    "recorded_audio_url": None,
                    "recorded_audio_duration": None,
                    "original_text": title or "مشهد",
                    "title": title or "مشهد",
                    "duration": max(3.0, float(project_data.get("duration", 5.0) or 5.0)),
                    "start": 0.0,
                    "layer": 0,
                }]

            await save_progress(10.0, f"تحضير {len(scene_objects)} مشهد")

            # ── Resolve active HF models (image only, لا voice) ──────────────
            try:
                image_generator = await _resolve_image_generator(rs)
                _diag(f"🔥 image_generator={image_generator}")
            except Exception as e:
                _diag_err(f"💥 _resolve_image_generator failed: {e}", e)
                raise

            scenes_data: list[dict] = []
            total = len(scene_objects)

            for i, scene_obj in enumerate(scene_objects):
                pct = 10.0 + (i / max(total, 1)) * 50.0
                await save_progress(pct, f"معالجة المشهد {i + 1}/{total}")

                scene_text = scene_obj["text"]
                scene_type = scene_obj["type"]
                scene_media_url = scene_obj.get("media_url")
                scene_title = scene_obj.get("title") or f"مشهد {i + 1}"
                scene_duration = float(scene_obj.get("duration", 3.0))

                recorded_audio_url = scene_obj.get("recorded_audio_url")
                recorded_audio_duration = scene_obj.get("recorded_audio_duration")
                audio_source = scene_obj.get("source", "unknown")

                actual_audio: Optional[Path] = None
                duration = scene_duration

                # ══════════════════════════════════════════════════════════
                # ✅ تحميل الصوت (من أي مصدر)
                # ══════════════════════════════════════════════════════════
                if recorded_audio_url:
                    recorded_ext = _guess_audio_ext(recorded_audio_url)
                    recorded_path = temp_dir / f"audio_{i:04d}{recorded_ext}"

                    _diag(
                        f"🎙️ Scene {i}: downloading audio (source={audio_source}) "
                        f"from: {recorded_audio_url[:80]}..."
                    )
                    ok = await _download_media_to_file(recorded_audio_url, recorded_path)

                    if ok:
                        actual_audio = recorded_path
                        if recorded_audio_duration and recorded_audio_duration > 0.5:
                            duration = recorded_audio_duration
                        _diag(
                            f"✅ Scene {i}: using audio "
                            f"({duration:.2f}s) → {recorded_path}"
                        )
                    else:
                        _diag_err(
                            f"⚠️ Scene {i}: audio download failed → silent"
                        )
                else:
                    _diag(f"🔇 Scene {i}: silent (no audio)")

                # ── الوسائط الحقيقية أو توليد صورة ──────────────────────
                image_path = temp_dir / f"scene_{i:04d}.jpg"
                used_real_media = False

                if scene_media_url and scene_type in ("image", "video"):
                    ext = ".mp4" if scene_type == "video" else ".jpg"
                    media_path = temp_dir / f"scene_{i:04d}{ext}"

                    ok = await _download_media_to_file(scene_media_url, media_path)
                    if ok:
                        image_path = media_path
                        used_real_media = True
                        _diag(f"✅ Scene {i}: using real {scene_type} from Supabase")
                    else:
                        _diag_err(f"⚠️ Scene {i}: media download failed, falling back")

                # ── إذا كان audio-only scene (لا صورة) → صورة سوداء ──────
                if not used_real_media and scene_type == "text" and actual_audio:
                    # أنشئ صورة سوداء بسيطة
                    try:
                        from PIL import Image
                        img = Image.new('RGB', (rs.resolution_width, rs.resolution_height), color='black')
                        img.save(image_path, 'JPEG', quality=85)
                        used_real_media = True
                        _diag(f"🎨 Scene {i}: created black background for audio")
                    except Exception as e:
                        _diag_err(f"⚠️ Black image failed: {e}", e)

                # ── وإلا: ولّد صورة بـ HF/Pillow ──────────────────────
                if not used_real_media:
                    try:
                        await image_generator.generate_scene_image(
                            text=scene_title,
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
                    "type": scene_type,
                    "media_url": scene_media_url,
                    "audio_source": audio_source if actual_audio else "silent",
                })

            # ✅ تشخيص نهائي
            audio_scenes = sum(1 for s in scenes_data if s.get("audio_path"))
            _diag(
                f"🎙️ Render summary: {len(scenes_data)} scenes, "
                f"{audio_scenes} with audio, "
                f"{len(scenes_data) - audio_scenes} silent"
            )

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

            # ══════════════════════════════════════════════════════════════════
            # ── Upload video + thumbnail to Supabase ─────────────────────────
            # ══════════════════════════════════════════════════════════════════
            from infrastructure.storage.supabase_storage_adapter import (
                SupabaseStorageAdapter,
            )

            storage = SupabaseStorageAdapter()
            video_url: Optional[str] = None
            video_storage_path: Optional[str] = None
            thumbnail_url: Optional[str] = None
            thumb_storage_path: Optional[str] = None

            try:
                video_local = Path(result.output_path)
                if video_local.exists() and video_local.stat().st_size > 0:
                    video_storage_path = f"renders/{job_id}/{video_local.name}"

                    _diag(
                        f"📤 Uploading video: {video_local} "
                        f"({video_local.stat().st_size} bytes) → {video_storage_path}"
                    )

                    await _upload_to_supabase(
                        storage=storage,
                        local_path=video_local,
                        remote_path=video_storage_path,
                        content_type="video/mp4",
                    )

                    video_url = await _build_public_url(storage, video_storage_path)
                    _diag(f"✅ Video uploaded: {video_url}")
                else:
                    _diag_err(f"⚠️ Rendered video missing or empty: {video_local}")
            except Exception as e:
                _diag_err(f"❌ Video upload failed: {e}", e)

            thumb_path = settings.THUMBNAILS_DIR / f"{job_id}.jpg"
            thumb_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                await renderer.generate_thumbnail(
                    result.output_path,
                    ThumbnailConfig(title=title),
                    thumb_path,
                )
                _diag(f"🔥 thumbnail generated: {thumb_path}")

                if thumb_path.exists() and thumb_path.stat().st_size > 0:
                    thumb_storage_path = f"thumbnails/{job_id}.jpg"

                    await _upload_to_supabase(
                        storage=storage,
                        local_path=thumb_path,
                        remote_path=thumb_storage_path,
                        content_type="image/jpeg",
                    )

                    thumbnail_url = await _build_public_url(storage, thumb_storage_path)
                    _diag(f"✅ Thumbnail uploaded: {thumbnail_url}")
                else:
                    _diag_err(f"⚠️ Thumbnail missing or empty: {thumb_path}")
            except Exception as e:
                _diag_err(f"⚠️ Thumbnail pipeline failed: {e}", e)

            await save_progress(100.0, "اكتمل")

            # ── Persist to DB ────────────────────────────────────────────────
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

                    try:
                        if video_url:
                            try:
                                project.video_url = video_url
                            except Exception:
                                pass
                            try:
                                project.storage_path = video_storage_path
                            except Exception:
                                pass
                            try:
                                project.output_path = str(result.output_path)
                            except Exception:
                                pass

                        if thumbnail_url:
                            try:
                                project.thumbnail_url = thumbnail_url
                            except Exception:
                                pass

                        try:
                            data = getattr(project, "data", None) or {}
                            if not isinstance(data, dict):
                                data = {}
                            if video_url:
                                data["video_url"] = video_url
                                data["video_path"] = video_storage_path
                            if thumbnail_url:
                                data["thumbnail"] = thumbnail_url
                                data["thumbnail_path"] = thumb_storage_path
                            data["rendered_at"] = datetime.utcnow().isoformat()
                            data["output_local_path"] = str(result.output_path)

                            if hasattr(project, "update_data"):
                                project.update_data(data)
                            else:
                                project.data = data
                        except Exception as e:
                            _diag_err(f"⚠️ Could not update project.data: {e}", e)

                        _diag(
                            f"💾 Persisted — video_url={bool(video_url)} "
                            f"thumbnail_url={bool(thumbnail_url)}"
                        )
                    except Exception as e:
                        _diag_err(f"⚠️ Failed to persist URLs in project: {e}", e)

                    await proj_repo.save(project)

                await session.commit()
                _diag("💾 DB committed")

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

    # ═════════════════════════════════════════════════════════════════════════
    # ── Scene builder from clips ─────────────────────────────────────────────
    # ═════════════════════════════════════════════════════════════════════════
    def _build_scenes_from_clips(
        self,
        clips: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        ✅ يتبع التحرير حرفياً:
           - audio clip (type="audio") → يُشغّل صوته (TTS/Edge/Cloned/Recording)
           - image/video clip → يُشغّل صورته
           - metadata.audioRecordings[] → تسجيلات مرفقة بـ image/video
           - لا TTS تلقائي

        Returns:
            list of scene dicts with:
                text, type, media_url, recorded_audio_url,
                recorded_audio_duration, original_text, title,
                duration, start, layer, source
        """
        scenes: list[dict] = []

        if not clips:
            return [{
                "text": "",
                "type": "text",
                "media_url": None,
                "recorded_audio_url": None,
                "recorded_audio_duration": None,
                "original_text": "",
                "title": "مشهد",
                "duration": 3.0,
                "start": 0.0,
                "layer": 0,
            }]

        # ── رتّب حسب (الطبقة، البداية) ─────────────────────────
        try:
            sorted_clips = sorted(
                clips,
                key=lambda c: (
                    int(c.get("layer", 0) or 0),
                    float(c.get("start", 0.0) or 0.0),
                ),
            )
        except Exception:
            sorted_clips = list(clips)

        # ══════════════════════════════════════════════════════════════════
        # ✅ الخطوة 1: استخرج كل clips الصوت (type == "audio")
        # ══════════════════════════════════════════════════════════════════
        audio_clips_map: list[dict] = []
        for clip in sorted_clips:
            clip_type = (clip.get("type") or "").lower()
            if clip_type != "audio":
                continue

            audio_url = clip.get("url") or clip.get("content")
            if not isinstance(audio_url, str) or not audio_url.startswith("http"):
                _diag(
                    f"⚠️ Audio clip {clip.get('id')}: no valid url "
                    f"(url={str(audio_url)[:60]}) — skipped"
                )
                continue

            start = float(clip.get("start", 0.0) or 0.0)
            duration = float(clip.get("duration", 3.0) or 3.0)
            source = clip.get("source", "unknown")

            audio_clips_map.append({
                "id": clip.get("id"),
                "url": audio_url,
                "start": start,
                "end": start + duration,
                "duration": duration,
                "source": source,
                "title": clip.get("title") or "مقطع صوتي",
                "script": clip.get("script") or "",
                "script_segments": clip.get("script_segments") or [],
                "voice_id": clip.get("voice_id"),
                "metadata": clip.get("metadata") or {},
            })

            _diag(
                f"🎵 Found audio clip: id={clip.get('id')} "
                f"source={source} start={start:.2f}s dur={duration:.2f}s "
                f"voice_id={clip.get('voice_id')}"
            )

        _diag(f"🎵 Total audio clips: {len(audio_clips_map)}")

        # ══════════════════════════════════════════════════════════════════
        # ✅ الخطوة 2: حوّل كل clip إلى scene
        # ══════════════════════════════════════════════════════════════════
        for clip in sorted_clips:
            clip_type = (clip.get("type") or "text").lower()
            metadata = clip.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}

            # ── إذا كان clip صوتياً → أنشئ scene خاصة به ──
            if clip_type == "audio":
                audio_url = clip.get("url") or clip.get("content")
                if not isinstance(audio_url, str) or not audio_url.startswith("http"):
                    continue

                start = float(clip.get("start", 0.0) or 0.0)
                duration = float(clip.get("duration", 3.0) or 3.0)
                source = clip.get("source", "unknown")
                title = clip.get("title") or "مقطع صوتي"

                _diag(
                    f"🎙️ Audio-only scene: '{title}' "
                    f"(source={source}, {duration:.2f}s)"
                )

                scenes.append({
                    "text": "",
                    "type": "text",  # مشهد أسود (بلا صورة)
                    "media_url": None,
                    "recorded_audio_url": audio_url,
                    "recorded_audio_duration": duration,
                    "original_text": title,
                    "title": title,
                    "duration": duration,
                    "start": start,
                    "layer": int(clip.get("layer", 0) or 0),
                    "source": source,
                })
                continue

            # ── لغير الصوت: image/video/text ──
            media_url = None
            if clip_type in ("image", "video"):
                candidate = (
                    clip.get("content")
                    or clip.get("url")
                    or metadata.get("url")
                )
                if isinstance(candidate, str) and candidate.startswith("http") and "blob:" not in candidate:
                    media_url = candidate

            # ── استخراج التسجيل الصوتي (من metadata) ──────────
            audio_recordings = metadata.get("audioRecordings") or []
            recorded_audio_url: Optional[str] = None
            recorded_audio_duration: Optional[float] = None

            if isinstance(audio_recordings, list) and audio_recordings:
                valid_recs = [
                    r for r in audio_recordings
                    if isinstance(r, dict)
                    and isinstance(r.get("url"), str)
                    and r["url"].startswith("http")
                    and "blob:" not in r["url"]
                ]
                if valid_recs:
                    best_rec = max(
                        valid_recs,
                        key=lambda r: float(r.get("duration", 0) or 0),
                    )
                    recorded_audio_url = best_rec["url"]
                    recorded_audio_duration = float(best_rec.get("duration", 0) or 0)

            # ── ✅ إذا لم يكن هناك تسجيل، ابحث عن audio clip متقاطع ──
            clip_start = float(clip.get("start", 0.0) or 0.0)
            clip_end = clip_start + float(clip.get("duration", 3.0) or 3.0)

            if not recorded_audio_url and audio_clips_map:
                for audio_clip in audio_clips_map:
                    overlap_start = max(clip_start, audio_clip["start"])
                    overlap_end = min(clip_end, audio_clip["end"])

                    if overlap_end > overlap_start:
                        recorded_audio_url = audio_clip["url"]
                        recorded_audio_duration = overlap_end - overlap_start
                        _diag(
                            f"🔗 Scene {len(scenes)}: linked audio clip "
                            f"'{audio_clip['title']}' "
                            f"(overlap {overlap_start:.2f}→{overlap_end:.2f}s)"
                        )
                        break

            # ── النص الأصلي ────────────────
            if clip_type == "text":
                original_text = (clip.get("content") or clip.get("title") or "").strip()
            else:
                original_text = (clip.get("title") or "").strip()

            # ── السجلات التشخيصية ────────────
            if recorded_audio_url:
                _diag(
                    f"🎤 Scene {len(scenes)}: has audio "
                    f"({recorded_audio_duration or 0:.1f}s) — '{original_text[:40]}'"
                )
            else:
                _diag(
                    f"🔇 Scene {len(scenes)}: silent — '{original_text[:40]}'"
                )

            # ── المدة ────────────────────────
            duration = float(clip.get("duration", 3.0) or 3.0)
            if recorded_audio_duration and recorded_audio_duration > duration:
                duration = recorded_audio_duration

            scenes.append({
                "text": "",
                "type": clip_type,
                "media_url": media_url,
                "recorded_audio_url": recorded_audio_url,
                "recorded_audio_duration": recorded_audio_duration,
                "original_text": original_text,
                "title": clip.get("title") or f"مقطع {len(scenes) + 1}",
                "duration": duration,
                "start": clip_start,
                "layer": int(clip.get("layer", 0) or 0),
                "source": metadata.get("source", "user"),
            })

        if not scenes:
            scenes = [{
                "text": "",
                "type": "text",
                "media_url": None,
                "recorded_audio_url": None,
                "recorded_audio_duration": None,
                "original_text": "",
                "title": "مشهد",
                "duration": 3.0,
                "start": 0.0,
                "layer": 0,
            }]

        _diag(f"📽️ Built {len(scenes)} scenes from {len(clips)} clips")
        audio_scenes = sum(1 for s in scenes if s.get("recorded_audio_url"))
        _diag(f"🎙️ Scenes with audio: {audio_scenes}/{len(scenes)}")

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
        if job and hasattr(job, "status"):
            status_value = getattr(job.status, "value", job.status)
            if status_value in ("pending", "processing"):
                try:
                    job.cancel()
                    await self._jobs.save(job)
                    _diag(f"🛑 Marked job as cancelled in DB: {job_id}")
                except Exception as e:
                    _diag_err(f"⚠️ Could not mark job as cancelled: {e}", e)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _guess_audio_ext(url: str) -> str:
    """Determine the audio file extension from the URL."""
    if not url:
        return ".webm"
    lower = url.lower().split("?")[0]
    for ext in (".webm", ".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".flac"):
        if lower.endswith(ext):
            return ext
    return ".webm"


# ═════════════════════════════════════════════════════════════════════════════
# Media download helper
# ═════════════════════════════════════════════════════════════════════════════

async def _download_media_to_file(url: str, output_path: Path) -> bool:
    """
    حمّل ملف وسائط (صورة/فيديو/صوت) من URL إلى مسار محلي.

    Returns:
        True إذا نجح التحميل.
    """
    import httpx

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)
            _diag(
                f"✅ Downloaded media: {url[:80]}... → {output_path} "
                f"({len(resp.content)} bytes)"
            )
            return True
    except Exception as e:
        _diag_err(f"❌ Failed to download media: {url[:80]}... → {e}", e)
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Supabase upload helpers
# ═════════════════════════════════════════════════════════════════════════════

async def _upload_to_supabase(
    storage,
    local_path: Path,
    remote_path: str,
    content_type: str = "application/octet-stream",
) -> None:
    """Upload a local file to Supabase Storage."""
    local_path = Path(local_path)

    if hasattr(storage, "upload_file"):
        try:
            result = storage.upload_file(
                local_path=str(local_path),
                remote_path=remote_path,
                content_type=content_type,
            )
            if inspect.isawaitable(result):
                await result
            return
        except TypeError:
            pass
        except Exception as e:
            _diag_err(f"upload_file(str,str,str) failed: {e}", e)

    if hasattr(storage, "upload_file"):
        try:
            result = storage.upload_file(str(local_path), remote_path)
            if inspect.isawaitable(result):
                await result
            return
        except Exception as e:
            _diag_err(f"upload_file(str,str) failed: {e}", e)

    if hasattr(storage, "upload"):
        with open(local_path, "rb") as f:
            data = f.read()
        try:
            result = storage.upload(remote_path, data, content_type)
            if inspect.isawaitable(result):
                await result
            return
        except TypeError:
            try:
                result = storage.upload(remote_path, data)
                if inspect.isawaitable(result):
                    await result
                return
            except Exception as e:
                _diag_err(f"upload(path,data) failed: {e}", e)
        except Exception as e:
            _diag_err(f"upload(path,data,ct) failed: {e}", e)

    try:
        from infrastructure.storage.supabase_storage import get_supabase_client
        client = get_supabase_client()
        if client is None:
            raise RuntimeError("No Supabase client available")

        bucket = settings.SUPABASE_BUCKET
        with open(local_path, "rb") as f:
            data = f.read()

        try:
            client.storage.from_(bucket).upload(
                path=remote_path,
                file=data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
        except TypeError:
            client.storage.from_(bucket).upload(remote_path, data)
        return
    except Exception as e:
        _diag_err(f"raw supabase upload failed: {e}", e)
        raise


async def _build_public_url(storage, remote_path: str) -> Optional[str]:
    """Build the public URL for a file in Supabase Storage."""
    if hasattr(storage, "get_public_url"):
        try:
            result = storage.get_public_url(remote_path)
            if inspect.isawaitable(result):
                result = await result
            if result:
                return result
        except Exception as e:
            _diag_err(f"adapter.get_public_url failed: {e}", e)

    if settings.SUPABASE_URL:
        base = settings.SUPABASE_URL.rstrip("/")
        bucket = settings.SUPABASE_BUCKET
        return f"{base}/storage/v1/object/public/{bucket}/{remote_path.lstrip('/')}"

    return None


# ═════════════════════════════════════════════════════════════════════════════
# Image generation helpers
# ═════════════════════════════════════════════════════════════════════════════

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
