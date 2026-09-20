"""Talking Head endpoints (D-ID)."""
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.diagnostics import _diag, _diag_err
from ..core.directories import JOBS_DIR, TALKING_HEADS_DIR
from ..jobs.persistence import create_job_async, update_job_async
from ..jobs.state import TALKING_HEAD_JOBS
from ..media.ffmpeg_helpers import _get_video_duration
from ..services.did_service import (
    DID_API_BASE,
    did_create_talk,
    did_get_talk_status,
)
from ..services.edge_tts_service import edge_tts_generate

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 🎭 TALKING HEAD ENDPOINTS
# ============================================================

@router.post("/api/talking-head/create")
async def create_talking_head(
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    project_id: str = Form(""),
):
    """🎭 أنشئ فيديو talking head من صورة + صوت جاهز."""
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID غير مهيأ. أضف DID_API_KEY."},
                status_code=503,
            )

        img_content = await image.read()
        aud_content = await audio.read()

        if not img_content:
            return JSONResponse(
                {"success": False, "error": "الصورة فارغة"},
                status_code=400,
            )

        if not aud_content:
            return JSONResponse(
                {"success": False, "error": "الصوت فارغ"},
                status_code=400,
            )

        _diag(f"🎭 Talking Head (image+audio):")
        _diag(f"   Image: {len(img_content) / 1024:.1f} KB")
        _diag(f"   Audio: {len(aud_content) / 1024:.1f} KB")

        talk_id = await did_create_talk(
            image_content=img_content,
            audio_content=aud_content,
            image_filename=image.filename or "image.jpg",
        )

        await create_job_async(
            talk_id,
            project_id=project_id,
            status="created",
            result_url=None,
            error=None,
            kind="talking_head",
        )

        return {
            "success": True,
            "talk_id": talk_id,
            "status": "created",
            "message": "✅ تم إنشاء الفيديو. جاري المعالجة...",
        }

    except HTTPException as e:
        return JSONResponse(
            {"success": False, "error": e.detail},
            status_code=e.status_code,
        )
    except Exception as e:
        logger.exception("Talking head creation failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/talking-head/generate")
async def generate_talking_head(
    image: UploadFile = File(...),
    text: str = Form(...),
    voice_id: str = Form("ar-SA-HamedNeural"),
    use_edge_tts: str = Form("true"),
    language: str = Form("ar"),
    project_id: str = Form(""),
):
    """🎭 توليد فيديو ناطق من صورة + نص."""
    from fastapi import HTTPException

    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID غير مهيأ — أضف DID_API_KEY"},
                status_code=503,
            )

        text = text.strip()
        if not text:
            return JSONResponse(
                {"success": False, "error": "النص فارغ"},
                status_code=400,
            )

        if len(text) > settings.DID_MAX_TEXT_CHARS:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"النص طويل جداً ({len(text)} حرف). "
                        f"الحد الأقصى {settings.DID_MAX_TEXT_CHARS} حرف."
                    ),
                },
                status_code=400,
            )

        img_content = await image.read()
        if not img_content:
            return JSONResponse(
                {"success": False, "error": "الصورة فارغة"},
                status_code=400,
            )

        img_size_mb = len(img_content) / 1024 / 1024
        if img_size_mb > 5:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"الصورة كبيرة جداً ({img_size_mb:.1f} MB). "
                        f"الحد 5 MB. جرّب صورة أصغر."
                    ),
                },
                status_code=400,
            )

        _diag(f"🎭 Talking Head request:")
        _diag(f"   Text: {len(text)} chars")
        _diag(f"   Image: {img_size_mb:.2f} MB ({image.filename})")
        _diag(f"   Voice: {voice_id}")

        _diag(f"🎙️ Generating audio via Edge TTS...")

        try:
            audio_bytes = await edge_tts_generate(
                text=text,
                voice=voice_id,
            )
        except Exception as e:
            _diag_err(f"❌ Edge TTS failed: {e}", e)
            return JSONResponse(
                {
                    "success": False,
                    "error": f"فشل توليد الصوت: {str(e)}",
                },
                status_code=500,
            )

        aud_size_mb = len(audio_bytes) / 1024 / 1024
        _diag(f"✅ Audio generated: {aud_size_mb:.2f} MB")

        if aud_size_mb > 10:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"الصوت المُولَّد كبير جداً ({aud_size_mb:.1f} MB). "
                        f"استخدم نصاً أقصر."
                    ),
                },
                status_code=400,
            )

        _diag(f"🎭 Creating talking head on D-ID...")

        try:
            talk_id = await did_create_talk(
                image_content=img_content,
                audio_content=audio_bytes,
                image_filename=image.filename or "image.jpg",
            )
        except HTTPException as e:
            return JSONResponse(
                {
                    "success": False,
                    "error": e.detail,
                },
                status_code=e.status_code,
            )

        await create_job_async(
            talk_id,
            project_id=project_id,
            status="created",
            text=text,
            voice_id=voice_id,
            provider="edge_tts",
            kind="talking_head",
        )

        _diag(f"✅ Talking head started: {talk_id}")

        return {
            "success": True,
            "talk_id": talk_id,
            "status": "created",
            "message": "✅ تم إنشاء الفيديو. جاري المعالجة...",
        }

    except Exception as e:
        _diag_err(f"❌ Talking head failed: {e}", e)
        return JSONResponse(
            {
                "success": False,
                "error": f"خطأ غير متوقع: {str(e)}",
            },
            status_code=500,
        )


@router.get("/api/talking-head/status/{talk_id}")
async def get_talking_head_status(talk_id: str):
    try:
        if not settings.did_configured:
            return JSONResponse(
                {"success": False, "error": "D-ID غير مهيأ"},
                status_code=503,
            )

        data = await did_get_talk_status(talk_id)

        status = data.get("status", "unknown")
        result_url = data.get("result_url")
        error = data.get("error")
        duration = data.get("duration")

        if status == "done" and result_url and not duration:
            try:
                _diag(f"⏱️ Probing duration for {talk_id}...")

                async with httpx.AsyncClient(
                    timeout=60.0, follow_redirects=True
                ) as client:
                    headers = {"Range": "bytes=0-3145728"}
                    r = await client.get(result_url, headers=headers)
                    if r.status_code in (200, 206):
                        tmp = (
                            Path(tempfile.gettempdir())
                            / f"probe_{talk_id}.mp4"
                        )
                        tmp.write_bytes(r.content)
                        duration = await _get_video_duration(tmp)
                        tmp.unlink(missing_ok=True)
                        _diag(f"✅ Duration extracted: {duration:.2f}s")
            except Exception as e:
                _diag_err(f"⚠️ Failed to probe duration: {e}", e)

        await update_job_async(
            talk_id,
            status=status,
            result_url=result_url,
            duration=duration,
            error=error,
        )

        return {
            "success": True,
            "talk_id": talk_id,
            "status": status,
            "result_url": result_url,
            "duration": duration,
            "error": error,
        }

    except Exception as e:
        logger.exception("Get status failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/talking-head/save/{project_id}")
async def save_talking_head_to_project(
    project_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    """🎭 حفظ Talking Head في المشروع."""
    from datetime import datetime

    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    source_url = payload.get("video_url") or payload.get("result_url")
    if not source_url:
        return JSONResponse({"error": "video_url مطلوب"}, status_code=400)

    _diag(f"📥 Saving talking head: {source_url[:100]}...")

    video_bytes = None
    local_video_path = None

    try:
        _diag("⬇️ Downloading video from D-ID...")
        async with httpx.AsyncClient(
            timeout=300.0, follow_redirects=True
        ) as client:
            r = await client.get(source_url)
            if r.status_code != 200:
                raise RuntimeError(f"Download failed: HTTP {r.status_code}")
            video_bytes = r.content
            _diag(f"✅ Downloaded: {len(video_bytes) / 1024 / 1024:.2f} MB")
    except Exception as e:
        _diag_err(f"❌ Failed to download video: {e}", e)
        return JSONResponse(
            {"success": False, "error": f"فشل تنزيل الفيديو من D-ID: {e}"},
            status_code=502,
        )

    if not video_bytes or len(video_bytes) < 10000:
        return JSONResponse(
            {"success": False, "error": "الفيديو المُنزَّل فارغ أو تالف"},
            status_code=502,
        )

    unique = uuid.uuid4().hex[:12]
    local_tmp = (
        Path(tempfile.gettempdir()) / f"talking_head_{unique}.mp4"
    )
    local_tmp.write_bytes(video_bytes)
    local_video_path = local_tmp

    real_duration = await _get_video_duration(local_tmp)
    _diag(f"⏱️ Real duration: {real_duration:.2f}s")

    permanent_url = None
    remote_path = None

    if settings.supabase_configured:
        try:
            from application.services.production_service import (
                _upload_to_supabase, _build_public_url,
            )

            storage = SupabaseStorageAdapter()
            remote_path = f"talking_heads/{project_id}/{unique}.mp4"

            await _upload_to_supabase(
                storage=storage,
                local_path=local_tmp,
                remote_path=remote_path,
                content_type="video/mp4",
            )
            permanent_url = await _build_public_url(storage, remote_path)
            _diag(f"✅ Uploaded to Supabase: {permanent_url[:80]}...")
        except Exception as e:
            _diag_err(f"⚠️ Supabase upload failed: {e}", e)

    if not permanent_url:
        local_dest = TALKING_HEADS_DIR / f"{project_id}_{unique}.mp4"
        local_dest.write_bytes(video_bytes)
        permanent_url = f"/static/media/talking_heads/{local_dest.name}"
        remote_path = str(local_dest)
        _diag(f"⚠️ Using local fallback: {permanent_url}")

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []

    clip_id = payload.get("id") or f"clip-{uuid.uuid4().hex[:12]}"

    new_clip = {
        "id": clip_id,
        "type": "video",
        "title": payload.get("title", "Talking Head"),
        "url": permanent_url,
        "src": permanent_url,
        "path": remote_path,
        "start": payload.get("start", 0),
        "duration": real_duration,
        "source": "talking_head",
        "text": payload.get("text", ""),
        "voice_id": payload.get("voice_id"),
        "image_url": payload.get("image_url"),
        "created_at": datetime.utcnow().isoformat(),
    }

    clips.append(new_clip)
    data["clips"] = clips

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    if local_video_path and local_video_path.exists():
        local_video_path.unlink(missing_ok=True)

    _diag(f"✅ Talking head saved: {clip_id} ({real_duration:.2f}s)")

    return {
        "success": True,
        "clip": new_clip,
        "message": "✅ تم الحفظ مع الرابط الدائم والمدة الحقيقية",
    }


@router.delete("/api/talking-head/delete/{talk_id}")
async def delete_talking_head(talk_id: str):
    """احذف talking head job."""
    if settings.did_configured:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.delete(
                    f"{DID_API_BASE}/talks/{talk_id}",
                    headers={"Authorization": settings.did_api_key_value},
                )
        except Exception as e:
            logger.warning(f"Failed to delete talk: {e}")

    if talk_id in TALKING_HEAD_JOBS:
        del TALKING_HEAD_JOBS[talk_id]

    try:
        job_file = JOBS_DIR / f"{talk_id}.json"
        if job_file.exists():
            job_file.unlink()
    except Exception:
        pass

    return {"success": True, "talk_id": talk_id}


@router.get("/api/talking-head/list")
async def list_talking_head_jobs():
    return {
        "success": True,
        "count": len(TALKING_HEAD_JOBS),
        "jobs": list(TALKING_HEAD_JOBS.values()),
    }
