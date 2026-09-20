"""Media endpoints: voiceover CRUD, transcribe, process-audio, upload-media, align-script."""
import json
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.directories import VOICEOVER_MAX_SIZE
from ..media.ffmpeg_helpers import _get_audio_duration
from ..media.voiceover_storage import _upload_voiceover_to_storage

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# MEDIA — VOICEOVER UPLOAD
# ============================================================

@router.post("/api/media/upload-voiceover")
async def upload_voiceover(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    title: str = Form(""),
    script: str = Form(""),
    script_segments: str = Form("[]"),
    source: str = Form("recording"),
    start: float = Form(0.0),
    duration: float = Form(0.0),
    processed: str = Form("false"),
    processing_options: str = Form("{}"),
):
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )
        if len(content) > VOICEOVER_MAX_SIZE:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"حجم الملف يتجاوز "
                        f"{VOICEOVER_MAX_SIZE // (1024*1024)}MB"
                    ),
                },
                status_code=413,
            )

        content_type = file.content_type or "audio/webm"
        suffix = (
            Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        )

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            if duration <= 0:
                duration = await _get_audio_duration(tmp_path)

            uploaded = await _upload_voiceover_to_storage(
                tmp_path, project_id, content_type
            )

            try:
                segments = (
                    json.loads(script_segments) if script_segments else []
                )
            except json.JSONDecodeError:
                segments = []

            try:
                proc_opts = (
                    json.loads(processing_options)
                    if processing_options else {}
                )
            except json.JSONDecodeError:
                proc_opts = {}

            return {
                "success": True,
                "url": uploaded["url"],
                "path": uploaded["path"],
                "media_id": uploaded["media_id"],
                "duration": duration,
                "title": title,
                "script": script,
                "script_segments": segments,
                "source": source,
                "start": start,
                "processed": processed.lower() == "true",
                "processing_options": proc_opts,
            }
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Voiceover upload failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@router.post("/api/media/transcribe")
async def transcribe_voiceover(
    file: UploadFile = File(...),
    language: str = Form("ar"),
    with_timestamps: str = Form("true"),
    model_size: str = Form("base"),
):
    """استخراج النص من ملف صوتي (Whisper)."""
    tmp_path = None
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        suffix = (
            Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        )
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        segments: List[Dict[str, Any]] = []
        full_text = ""
        detected_lang = language

        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(
                model_size, device="cpu", compute_type="int8"
            )
            segments_gen, info = model.transcribe(
                str(tmp_path),
                language=language if language != "auto" else None,
                beam_size=5,
                vad_filter=True,
            )
            for seg in segments_gen:
                segments.append({
                    "text": seg.text.strip(),
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                })
            full_text = " ".join(
                s["text"] for s in segments
            ).strip()
            detected_lang = getattr(info, "language", language) or language

        except ImportError:
            import whisper
            model = whisper.load_model(model_size)
            result = model.transcribe(
                str(tmp_path),
                language=language if language != "auto" else None,
                verbose=False,
            )
            if with_timestamps.lower() == "true":
                for seg in result.get("segments", []):
                    segments.append({
                        "text": seg["text"].strip(),
                        "start": round(float(seg["start"]), 3),
                        "end": round(float(seg["end"]), 3),
                    })
            full_text = result.get("text", "").strip()
            detected_lang = result.get("language", language) or language

        duration = segments[-1]["end"] if segments else 0.0

        return {
            "success": True,
            "text": full_text,
            "language": detected_lang,
            "segments": segments,
            "duration": duration,
        }

    except ImportError:
        return JSONResponse(
            {
                "success": False,
                "error": "Whisper غير مثبّت. شغّل: pip install faster-whisper",
            },
            status_code=500,
        )
    except Exception as e:
        logger.exception("Transcription failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@router.post("/api/media/process-audio")
async def process_audio_endpoint(
    file: UploadFile = File(...),
    options: str = Form("{}"),
):
    """معالجة الصوت بـ ffmpeg."""
    import asyncio

    tmp_in = None
    tmp_out = None
    try:
        content = await file.read()
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        try:
            opts = json.loads(options) if options else {}
        except json.JSONDecodeError:
            opts = {}

        normalize = opts.get("normalize", True)
        denoise = opts.get("denoise", False)
        trim_silence = opts.get("trim_silence", True)
        compress = opts.get("compress", False)
        target_lufs = float(
            opts.get("target_lufs", settings.AUDIO_TARGET_LUFS)
        )

        suffix = (
            Path(file.filename or "audio.webm").suffix.lower() or ".webm"
        )
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(content)
            tmp_in = Path(tmp.name)

        tmp_out = tmp_in.with_name(
            f"processed_{uuid.uuid4().hex[:8]}.webm"
        )

        filters = []
        if denoise:
            filters.append("afftdn=nf=-25")
        if trim_silence:
            filters.append(
                "silenceremove=start_periods=1:start_duration=0.1:"
                "start_threshold=-45dB:detection=peak,"
                "areverse,"
                "silenceremove=start_periods=1:start_duration=0.1:"
                "start_threshold=-45dB:detection=peak,"
                "areverse"
            )
        if compress:
            filters.append(
                "acompressor=threshold=-18dB:ratio=3:attack=5:release=50"
            )
        if normalize:
            filters.append(f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11")

        cmd = [
            "ffmpeg", "-y", "-i", str(tmp_in),
            "-vn", "-c:a", "libopus", "-b:a", "128k",
        ]
        if filters:
            cmd += ["-af", ",".join(filters)]
        cmd.append(str(tmp_out))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg error: {stderr.decode()[-500:]}"
            )

        if not tmp_out.exists():
            raise RuntimeError("لم يتم إنشاء الملف المعالج")

        return FileResponse(
            path=str(tmp_out),
            media_type="audio/webm",
            filename="processed.webm",
            headers={
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )

    except FileNotFoundError:
        return JSONResponse(
            {"success": False, "error": "ffmpeg غير مثبّت"},
            status_code=500,
        )
    except Exception as e:
        logger.exception("Audio processing failed")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )
    finally:
        if tmp_in:
            tmp_in.unlink(missing_ok=True)


# ============================================================
# VOICEOVER CRUD
# ============================================================

@router.get("/api/media/voiceover/{project_id}")
async def list_voiceovers(
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

    voiceovers = [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "url": c.get("url"),
            "start": c.get("start", 0),
            "duration": c.get("duration", 0),
            "script": c.get("script", ""),
            "script_segments": c.get("script_segments", []),
            "source": c.get("source", "unknown"),
            "voice_id": c.get("voice_id"),
            "processed": c.get("processed", False),
        }
        for c in clips
        if isinstance(c, dict) and c.get("type") == "audio"
    ]

    return {
        "success": True,
        "count": len(voiceovers),
        "voiceovers": voiceovers,
    }


@router.delete("/api/media/voiceover/{project_id}/{clip_id}")
async def delete_voiceover(
    project_id: str,
    clip_id: str,
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

    target = next(
        (c for c in clips if isinstance(c, dict) and c.get("id") == clip_id),
        None,
    )
    if not target:
        return JSONResponse({"error": "Clip not found"}, status_code=404)

    path = target.get("path") or target.get("mediaId")
    if path and settings.supabase_configured:
        try:
            storage = SupabaseStorageAdapter()
            if hasattr(storage, "delete_file"):
                await storage.delete_file(path)
        except Exception as e:
            logger.warning(f"Failed to delete storage: {e}")

    local_path = target.get("path")
    if local_path and isinstance(local_path, str) and local_path.startswith("/"):
        try:
            p = Path(local_path)
            if p.exists() and p.is_file():
                p.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete local: {e}")

    data["clips"] = [c for c in clips if c.get("id") != clip_id]
    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "deleted_id": clip_id}


@router.patch("/api/media/voiceover/{project_id}/{clip_id}")
async def update_voiceover(
    project_id: str,
    clip_id: str,
    payload: Dict[str, Any],
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

    target = next(
        (c for c in clips if isinstance(c, dict) and c.get("id") == clip_id),
        None,
    )
    if not target:
        return JSONResponse({"error": "Clip not found"}, status_code=404)

    for field in (
        "title", "script", "script_segments",
        "start", "duration", "tts", "voice_id",
    ):
        if field in payload:
            target[field] = payload[field]

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "clip": target}


@router.post("/api/media/voiceover/{project_id}")
async def add_voiceover_clip(
    project_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    """إضافة clip صوتي للمشروع."""
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

    clip_id = payload.get("id") or f"clip-{uuid.uuid4().hex[:12]}"
    payload["id"] = clip_id
    payload.setdefault("type", "audio")

    clips.append(payload)
    data["clips"] = clips

    if hasattr(project, "data"):
        project.data = data
    if hasattr(repo, "update"):
        await repo.update(project)
    elif hasattr(repo, "save"):
        await repo.save(project)
    await session.commit()

    return {"success": True, "clip": payload}


# ============================================================
# MEDIA UPLOAD (عام)
# ============================================================

@router.post("/api/v1/storage/upload-media")
async def upload_media(
    file: UploadFile = File(...),
    project_id: str = Form(...),
):
    try:
        from application.services.production_service import (
            _upload_to_supabase, _build_public_url,
        )

        storage = SupabaseStorageAdapter()
        content = await file.read()

        if not content:
            return JSONResponse({"error": "الملف فارغ"}, status_code=400)

        suffix = Path(file.filename or "file").suffix.lower() or ".bin"
        unique = f"{uuid.uuid4().hex}{suffix}"
        remote_path = f"media/{project_id}/{unique}"

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            content_type = (
                file.content_type or "application/octet-stream"
            )
            await _upload_to_supabase(
                storage=storage,
                local_path=tmp_path,
                remote_path=remote_path,
                content_type=content_type,
            )
            url = await _build_public_url(storage, remote_path)
            if not url:
                raise RuntimeError("فشل بناء الرابط")

            return {"url": url, "path": remote_path}
        finally:
            tmp_path.unlink(missing_ok=True)

    except Exception as e:
        logger.exception("Failed to upload media")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# ALIGN SCRIPT (Backward Compatible)
# ============================================================

@router.post("/api/media/align-script")
async def align_script_with_audio(
    file: UploadFile = File(...),
    script: str = Form(...),
    language: str = Form("ar"),
    voice_id: str = Form(""),
    project_id: str = Form(""),
):
    """🎙️ Voice Cloning — توافق مع الكود القديم."""
    from .voice import generate_with_cache, generate_with_cloned_voice

    if voice_id:
        return await generate_with_cloned_voice(
            voice_id=voice_id,
            script=script,
            project_id=project_id,
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=1.0,
            model_id=settings.ELEVENLABS_MODEL_ID,
        )

    return await generate_with_cache(
        voice_id="ar-SA-HamedNeural",
        script=script,
        project_id=project_id,
        use_cache="true",
        speed=1.0,
    )
