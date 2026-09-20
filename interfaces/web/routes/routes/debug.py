"""Debug endpoints."""
import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository

from ..core.directories import CACHE_DIR, JOBS_DIR, JOBS_STORAGE_PREFIX
from ..jobs.state import TALKING_HEAD_JOBS

router = APIRouter()


@router.get("/api/debug/project/{project_id}")
async def debug_project(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []
    saved_voices = data.get("cloned_voices", []) or []

    return {
        "project_id": project_id,
        "title": project.title,
        "data_keys": list(data.keys()),
        "clips_count": len(clips),
        "saved_voices_count": len(saved_voices),
        "saved_voices": saved_voices,
    }


@router.get("/api/debug/talking-head/jobs")
async def debug_talking_head_jobs():
    return {
        "success": True,
        "count": len(TALKING_HEAD_JOBS),
        "jobs": list(TALKING_HEAD_JOBS.values()),
        "local_files": (
            len(list(JOBS_DIR.glob("*.json")))
            if JOBS_DIR.exists() else 0
        ),
        "storage_prefix": JOBS_STORAGE_PREFIX,
    }


@router.get("/api/debug/jobs/list")
async def debug_jobs_list():
    """اعرض كل الـ jobs المحفوظة محلياً."""
    jobs = []
    if JOBS_DIR.exists():
        for f in JOBS_DIR.glob("*.json"):
            try:
                jobs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return {
        "success": True,
        "count": len(jobs),
        "jobs": jobs,
        "storage_prefix": JOBS_STORAGE_PREFIX,
    }


@router.get("/api/debug/voiceovers/{project_id}")
async def debug_voiceovers(
    project_id: str,
    session: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []
    saved_voices = data.get("cloned_voices", []) or []

    audio_clips = [
        c for c in clips
        if isinstance(c, dict) and c.get("type") == "audio"
    ]
    video_clips = [
        c for c in clips
        if isinstance(c, dict) and c.get("type") == "video"
    ]

    cache_files = list(CACHE_DIR.glob("*.mp3"))
    cache_size_mb = sum(f.stat().st_size for f in cache_files) / 1024 / 1024

    return {
        "project_id": project_id,
        "audio_clips_count": len(audio_clips),
        "video_clips_count": len(video_clips),
        "saved_voices_count": len(saved_voices),
        "saved_voices": saved_voices,
        "edge_tts_available": settings.EDGE_TTS_ENABLED,
        "huggingface_available": True,
        "elevenlabs_available": settings.elevenlabs_configured,
        "did_available": settings.did_configured,
        "cache_stats": {
            "files": len(cache_files),
            "size_mb": round(cache_size_mb, 2),
        },
    }
