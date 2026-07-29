"""Application service for Production / Render use cases."""
import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

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

    async def start_render(
        self,
        project_id: uuid.UUID,
        render_settings: Optional[dict] = None,
    ) -> RenderJob:
        project = await self._projects.get(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)

        job = RenderJob(project_id=project_id, settings=render_settings or {})
        project.start_production()

        await self._jobs.save(job)
        await self._projects.save(project)
        await self._bus.publish(ProductionStarted(project_id=project_id, render_job_id=job.id))

        task = asyncio.create_task(
            self._run_render(job.id, project.to_dict())
        )
        _active_renders[str(job.id)] = task
        return job

    async def _run_render(self, job_id: uuid.UUID, project_data: dict) -> None:
        """Background render task — runs independently of the request."""
        factory = get_session_factory()

        async def save_progress(progress: float, stage: str) -> None:
            async with factory() as session:
                from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
                repo = SQLRenderJobRepository(session)
                j = await repo.get(job_id)
                if j:
                    j.update_progress(progress, stage)
                    await repo.save(j)
                    await session.commit()
            await self._bus.publish(RenderProgressUpdated(
                job_id=job_id, progress=progress, stage=stage
            ))

        async with factory() as session:
            from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
            job_repo = SQLRenderJobRepository(session)

            job = await job_repo.get(job_id)
            if not job:
                return

            job.start()
            await job_repo.save(job)
            await session.commit()

        try:
            renderer = self._registry.get_renderer()
            temp_dir = settings.TEMP_DIR / str(job_id)
            temp_dir.mkdir(parents=True, exist_ok=True)

            rs = RenderSettings(fps=30, resolution_width=1920, resolution_height=1080)

            await save_progress(5.0, "تحليل النص وتقسيمه إلى مشاهد")

            # ── Build scenes from project script ──────────────────────────────
            script    = project_data.get("script", "")
            title     = project_data.get("title", "")
            brand_colors = project_data.get("brand_colors", {})
            brand_color  = (brand_colors.get("primary") if brand_colors else None)

            raw_scenes = _split_script_to_scenes(script, title)

            await save_progress(10.0, f"توليد {len(raw_scenes)} مشهد")

            # ── Generate TTS audio + scene images per scene ───────────────────
            voice_plugin    = self._registry.get_voice_provider()
            image_generator = _get_image_generator(rs)

            from shared.ports.voice_port import VoiceConfig
            voice_config = VoiceConfig(language="ar", speed=1.0, pitch=1.0)

            scenes_data: list[dict] = []
            total = len(raw_scenes)

            for i, scene_text in enumerate(raw_scenes):
                pct = 10.0 + (i / total) * 50.0
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
                    duration     = voice_result.duration
                except Exception as e:
                    logger.warning("TTS failed for scene %d: %s", i, e)
                    actual_audio = None
                    words    = len(scene_text.split())
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
                    logger.warning("Image gen failed for scene %d: %s", i, e)
                    image_path = None

                scenes_data.append({
                    "text":       scene_text,
                    "image_path": str(image_path) if image_path else "",
                    "audio_path": str(actual_audio) if actual_audio else "",
                    "duration":   duration,
                    "transition": "fade",
                })

            await save_progress(62.0, "تركيب الفيديو النهائي")

            # ── Render ────────────────────────────────────────────────────────
            result = await renderer.render(
                project_id=uuid.UUID(project_data["id"]),
                timeline_data={"scenes": scenes_data},
                assets={},
                settings=rs,
                temp_dir=temp_dir,
                progress_callback=save_progress,
            )

            # ── Thumbnail ─────────────────────────────────────────────────────
            output_dir = settings.EXPORTS_DIR / str(job_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            thumb_path = settings.THUMBNAILS_DIR / f"{job_id}.jpg"

            from shared.ports.renderer_port import ThumbnailConfig
            await renderer.generate_thumbnail(
                result.output_path,
                ThumbnailConfig(title=title),
                thumb_path,
            )

            await save_progress(100.0, "اكتمل")

            async with factory() as session:
                job_repo  = SQLRenderJobRepository(session)
                proj_repo = SQLProjectRepository(session)
                job       = await job_repo.get(job_id)
                project_id = uuid.UUID(project_data["id"])
                project   = await proj_repo.get(project_id)
                if job:
                    job.complete(str(result.output_path))
                    await job_repo.save(job)
                if project:
                    project.mark_rendered()
                    await proj_repo.save(project)
                await session.commit()

            await self._bus.publish(RenderCompleted(
                job_id=job_id,
                project_id=uuid.UUID(project_data["id"]),
                output_path=str(result.output_path),
            ))
            logger.info("Render completed: job=%s output=%s", job_id, result.output_path)

        except Exception as exc:
            logger.exception("Render failed: job=%s error=%s", job_id, exc)
            async with factory() as session:
                job_repo  = SQLRenderJobRepository(session)
                proj_repo = SQLProjectRepository(session)
                job       = await job_repo.get(job_id)
                project_id = uuid.UUID(project_data["id"])
                project   = await proj_repo.get(project_id)
                if job:
                    job.fail(str(exc))
                    await job_repo.save(job)
                if project:
                    project.mark_failed()
                    await proj_repo.save(project)
                await session.commit()
            await self._bus.publish(RenderFailed(
                job_id=job_id,
                project_id=uuid.UUID(project_data["id"]),
                error=str(exc),
            ))
        finally:
            _active_renders.pop(str(job_id), None)

    async def get_job(self, job_id: uuid.UUID) -> RenderJob:
        job = await self._jobs.get(job_id)
        if not job:
            raise RenderJobNotFoundError(job_id)
        return job

    async def list_jobs(self, limit: int = 20) -> list[RenderJob]:
        return await self._jobs.list_recent(limit=limit)


# ── Helpers ───────────────────────────────────────────────────────────────────

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

    # Split by double newline first
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", script.strip()) if p.strip()]

    if len(paragraphs) >= 2:
        return paragraphs

    # Single paragraph — split by sentence punctuation (Arabic + Latin)
    sentences = re.split(r"(?<=[.!?؟،\n])\s+", paragraphs[0])
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return [paragraphs[0]]

    # Group sentences into scenes of ~80 words each
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


def _get_image_generator(rs: RenderSettings):
    from plugins.image_gen.pillow_generator import SceneImageGenerator
    return SceneImageGenerator(width=rs.resolution_width, height=rs.resolution_height)
