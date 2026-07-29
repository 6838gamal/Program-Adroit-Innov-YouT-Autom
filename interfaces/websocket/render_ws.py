"""WebSocket endpoint for real-time render progress."""
import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session import get_session_factory

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/render/{job_id}")
async def render_progress_ws(websocket: WebSocket, job_id: UUID):
    await websocket.accept()
    factory = get_session_factory()

    try:
        while True:
            async with factory() as session:
                from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
                repo = SQLRenderJobRepository(session)
                job = await repo.get(job_id)

            if job is None:
                await websocket.send_json({"error": "Job not found"})
                break

            payload = {
                "job_id": str(job.id),
                "status": job.status.value,
                "progress": job.progress,
                "stage": job.current_stage,
            }
            await websocket.send_json(payload)

            if job.status.value in ("completed", "failed", "cancelled"):
                break

            await asyncio.sleep(1.5)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: render job %s", job_id)
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
