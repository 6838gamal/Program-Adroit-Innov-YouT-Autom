"""Property video generation endpoints."""
import asyncio
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.downloaders.media_downloader import (
    MediaDownloader,
    detect_engines,
)
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.diagnostics import _diag
from ..core.directories import PROPERTY_ASSETS_DIR
from ..jobs.age import _compute_job_age_seconds
from ..jobs.persistence import (
    create_job_async,
    get_job_async,
    update_job_async,
)
from ..schemas.property import PropertyVideoRequest
from ..services.property_video_service import run_property_video_job

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────
# مساعد: إعدادات cookies
# ─────────────────────────────────────────────────────────

def _get_cookies_from_browser() -> Optional[str]:
    """يرجع اسم المتصفح لاستخراج cookies منه (إن وُجد في الإعدادات)."""
    return getattr(settings, "cookies_from_browser", None)


# ─────────────────────────────────────────────────────────
# تشخيص: محركات التحميل المتاحة
# ─────────────────────────────────────────────────────────

@router.get("/api/property/download-engines")
async def list_download_engines():
    """
    يرجع المحركات المتاحة للتحميل (gallery-dl / yt-dlp / direct).
    مفيد للتشخيص والتأكد من التثبيت.
    """
    engines = detect_engines()
    return {
        "success": True,
        "engines": engines,
        "cookies_from_browser": _get_cookies_from_browser(),
    }


# ─────────────────────────────────────────────────────────
# رفع صور العقار (ملف أو URL)
# ─────────────────────────────────────────────────────────

@router.post("/api/property/upload-image")
async def upload_property_image(
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    project_id: str = Form(...),
):
    """
    يرفع صورة عقار (ملف مرفوع) أو يحمّلها من رابط URL.

    - إذا أُرسل `file` → يُرفع مباشرة.
    - إذا أُرسل `image_url` → يُحمَّل عبر MediaDownloader
      (gallery-dl → yt-dlp → direct) مع طباعة كل محاولة على الكونسول.

    يرجع رابطاً دائماً (Supabase) أو محلياً + المسار.
    """
    tmp_path: Optional[Path] = None
    content: bytes = b""
    suffix = ".jpg"
    source = "file"
    attempts_info: Optional[list] = None

    try:
        # ── الحالة 1: رابط URL ────────────────────────────
        if image_url and not file:
            source = "url"
            print(f"\n🌐 [upload-image] Downloading from URL: {image_url}")

            tmp_dir = Path(tempfile.mkdtemp(prefix="prop_img_"))

            dl = MediaDownloader(
                cookies_from_browser=_get_cookies_from_browser(),
                prefer=getattr(
                    settings, "downloader_prefer",
                    ["gallery-dl", "yt-dlp", "direct"],
                ),
            )
            bundle = await dl.download(image_url, out_dir=tmp_dir)
            attempts_info = bundle.to_dict()["attempts"]

            if not bundle.all_files:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "فشل تحميل الصورة من الرابط",
                        "attempts": attempts_info,
                    },
                    status_code=422,
                )

            tmp_path = bundle.all_files[0]
            content = tmp_path.read_bytes()
            suffix = tmp_path.suffix.lower() or ".jpg"

            print(
                f"✅ [upload-image] Downloaded via "
                f"{bundle.chosen.engine if bundle.chosen else '?'} "
                f"({len(content)} bytes)"
            )

        # ── الحالة 2: ملف مرفوع ──────────────────────────
        elif file:
            source = "file"
            content = await file.read()
            suffix = (
                Path(file.filename or "image.jpg").suffix.lower() or ".jpg"
            )

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            print(
                f"📎 [upload-image] Received file: "
                f"{file.filename} ({len(content)} bytes)"
            )

        else:
            return JSONResponse(
                {
                    "success": False,
                    "error": "أرسل `file` أو `image_url`",
                },
                status_code=400,
            )

        # ── التحقق ───────────────────────────────────────
        if not content:
            return JSONResponse(
                {"success": False, "error": "الملف فارغ"},
                status_code=400,
            )

        if len(content) > 10 * 1024 * 1024:
            return JSONResponse(
                {"success": False, "error": "حجم الصورة > 10MB"},
                status_code=413,
            )

        # ── التخزين ──────────────────────────────────────
        unique = f"{uuid.uuid4().hex}{suffix}"
        remote_path = f"property_assets/{project_id}/{unique}"

        # 1) محاولة Supabase
        if settings.supabase_configured:
            try:
                from application.services.production_service import (
                    _upload_to_supabase, _build_public_url,
                )
                storage = SupabaseStorageAdapter()

                content_type = (
                    file.content_type if file
                    else "image/jpeg"
                )

                await _upload_to_supabase(
                    storage=storage,
                    local_path=tmp_path,
                    remote_path=remote_path,
                    content_type=content_type,
                )
                url = await _build_public_url(storage, remote_path)

                if url:
                    print(f"☁️  [upload-image] Uploaded to Supabase: {url}")
                    return {
                        "success": True,
                        "url": url,
                        "path": remote_path,
                        "size": len(content),
                        "source": source,
                        "attempts": attempts_info,
                    }
            except Exception as e:
                logger.warning(f"Supabase image upload failed: {e}")
                print(f"⚠️  [upload-image] Supabase failed: {e}")

        # 2) Fallback محلي
        local_dest = PROPERTY_ASSETS_DIR / f"{project_id}_{unique}"
        local_dest.write_bytes(content)
        print(f"💾 [upload-image] Saved locally: {local_dest}")

        return {
            "success": True,
            "url": f"/static/media/property_assets/{local_dest.name}",
            "path": str(local_dest),
            "size": len(content),
            "local": True,
            "source": source,
            "attempts": attempts_info,
        }

    except Exception as e:
        logger.exception("Property image upload failed")
        print(f"❌ [upload-image] Error: {e}")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )

    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────
# بدء التوليد
# ─────────────────────────────────────────────────────────

@router.post("/api/property/generate")
async def generate_property_video(
    payload: PropertyVideoRequest,
    session: AsyncSession = Depends(get_db),
):
    """
    🏠 يبدأ توليد فيديو عقاري في الخلفية.

    يستخدم create_job_async (يحفظ في Supabase Storage)
    ويستخدم asyncio.create_task (أكثر موثوقية).
    """
    try:
        project_uuid = uuid.UUID(payload.project_id)
    except ValueError:
        return JSONResponse(
            {"success": False, "error": "Invalid project_id"},
            status_code=400,
        )

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse(
            {"success": False, "error": "Project not found"},
            status_code=404,
        )

    if not payload.images:
        return JSONResponse(
            {"success": False, "error": "أضف صورة واحدة على الأقل"},
            status_code=400,
        )

    job_id = f"prop_{uuid.uuid4().hex[:12]}"

    await create_job_async(
        job_id,
        project_id=payload.project_id,
        status="queued",
        progress=0.0,
        stage="queued",
        video_url=None,
        path=None,
        duration=0.0,
        error=None,
        kind="property_video",
    )

    asyncio.create_task(
        run_property_video_job(job_id, payload.model_dump())
    )

    _diag(f"🏠 Property video queued: {job_id}")
    _diag(f"   voiceover_enabled: {payload.voiceover_enabled}")
    _diag(f"   show_price: {payload.show_price}")
    _diag(f"   show_location: {payload.show_location}")
    _diag(f"   show_area: {payload.show_area}")
    _diag(f"   show_contact: {payload.show_contact}")

    print(f"🏠 [generate] Queued job: {job_id}")

    return {
        "success": True,
        "job_id": job_id,
        "status": "queued",
        "message": "✅ جاري التوليد في الخلفية...",
    }


# ─────────────────────────────────────────────────────────
# حالة التوليد
# ─────────────────────────────────────────────────────────

@router.get("/api/property/status/{job_id}")
async def get_property_video_status(job_id: str):
    """
    يرجع حالة job توليد العقار.
    يقرأ من الذاكرة أو Supabase Storage.
    يكشف jobs الميتة (restart) ويعلّمها failed.
    """
    job = await get_job_async(job_id)
    if not job:
        return JSONResponse(
            {"success": False, "error": "Job not found"},
            status_code=404,
        )

    # كشف jobs الميتة (restart)
    status_now = job.get("status")
    if status_now in ("running", "queued", "created"):
        age_seconds = _compute_job_age_seconds(job)

        _diag(
            f"⏱️ Job {job_id}: status={status_now}, age={age_seconds}s"
        )

        # إذا تجاوز 5 دقائق، اعتبره فشل
        if age_seconds is not None and age_seconds > 300:
            _diag(
                f"⚠️ Job {job_id} ميت ({age_seconds:.0f}s) — mark as failed"
            )

            await update_job_async(
                job_id,
                status="failed",
                error=(
                    f"انتهت المهمة (توقف الخادم قبل الإكمال بعد "
                    f"{int(age_seconds)}ث)"
                ),
                progress=0.0,
                stage="failed",
            )

            job = await get_job_async(job_id)

    return {
        "success": True,
        **job,
    }


# ─────────────────────────────────────────────────────────
# حفظ الـ clip في المشروع
# ─────────────────────────────────────────────────────────

@router.post("/api/property/save/{project_id}")
async def save_property_video_to_project(
    project_id: str,
    payload: Dict[str, Any],
    session: AsyncSession = Depends(get_db),
):
    """يحفظ الفيديو المولَّد في project.data["clips"]."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return JSONResponse({"error": "Invalid project_id"}, status_code=400)

    repo = SQLProjectRepository(session)
    project = await repo.get(project_uuid)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    video_url = payload.get("video_url")
    if not video_url:
        return JSONResponse({"error": "video_url مطلوب"}, status_code=400)

    data = getattr(project, "data", None) or {}
    clips = data.get("clips", []) or []

    clip_id = payload.get("id") or f"clip-{uuid.uuid4().hex[:12]}"

    new_clip = {
        "id": clip_id,
        "type": "video",
        "title": payload.get("title", "فيديو عقاري"),
        "url": video_url,
        "src": video_url,
        "path": payload.get("path"),
        "start": payload.get("start", 0),
        "duration": payload.get("duration", 0),
        "source": "property_video",
        "property_meta": payload.get("property_meta", {}),
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

    print(f"💾 [save] Saved clip {clip_id} to project {project_id}")

    return {
        "success": True,
        "clip": new_clip,
        "message": "✅ تم إضافة الفيديو العقاري للمشروع",
    }
