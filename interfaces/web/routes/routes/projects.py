"""Projects pages: list, create, detail, timeline + Video API."""
import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository

from core.domain.project.project import Project
from shared.value_objects import ProjectStatus, BrandColors
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.config_helpers import (
    get_supabase_config,
    _resolve_thumbnail_url,
    _resolve_video_url,
)
from ..core.templates import templates

logger = logging.getLogger(__name__)

# ---------- yt-dlp ----------
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    yt_dlp = None
    YTDLP_AVAILABLE = False

# ---------- pytubefix (YouTube) ----------
try:
    from pytubefix import YouTube as PyTubeYouTube
    from pytubefix.exceptions import PytubeFixException
    import pytubefix
    PYTUBEFIX_AVAILABLE = True
    PYTUBEFIX_VERSION = getattr(pytubefix, "__version__", "unknown")
except ImportError:
    PyTubeYouTube = None
    PytubeFixException = Exception
    PYTUBEFIX_AVAILABLE = False
    PYTUBEFIX_VERSION = "not installed"


router = APIRouter()


# =====================================================================
#                       MEDIA DIRECTORIES
# =====================================================================
MEDIA_ROOT = Path("media")
PREVIEW_DIR = MEDIA_ROOT / "preview"
DOWNLOAD_DIR = MEDIA_ROOT / "downloads"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================================
#                       VIDEO — SCHEMAS
# =====================================================================
class InfoRequest(BaseModel):
    url: HttpUrl


class FetchRequest(BaseModel):
    url: HttpUrl
    format_id: Optional[str] = None
    source: Optional[str] = None


class SaveRequest(BaseModel):
    url: str
    title: Optional[str] = None
    filename: Optional[str] = None


# =====================================================================
#                       VIDEO — SOURCE DETECTION
# =====================================================================
def is_youtube(url: str) -> bool:
    return any(d in url.lower() for d in (
        "youtube.com", "youtu.be", "youtube-nocookie.com", "m.youtube.com"
    ))


def is_facebook(url: str) -> bool:
    return any(d in url.lower() for d in (
        "facebook.com", "fb.watch", "fb.com", "m.facebook.com"
    ))


def detect_source(url: str) -> str:
    if is_youtube(url):
        return "youtube"
    if is_facebook(url):
        return "facebook"
    return "generic"


def _safe_filename(name: str, fallback: str = "video") -> str:
    if not name:
        return fallback
    name = re.sub(r"[^\w\s\-\.]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:120] or fallback


# =====================================================================
#                       VIDEO — YT-DLP
# =====================================================================
def _ytdlp_extract_info(url: str) -> dict:
    if not YTDLP_AVAILABLE:
        raise RuntimeError("yt-dlp غير مثبت.")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        return info


def _ytdlp_list_formats(info: dict) -> list[dict]:
    formats = info.get("formats") or []
    results = []
    seen = set()

    for f in formats:
        if f.get("vcodec") in (None, "none"):
            continue

        height = f.get("height")
        ext = f.get("ext") or "mp4"
        format_id = f.get("format_id")
        if not format_id or not height:
            continue

        key = (height, ext, f.get("fps"))
        if key in seen:
            continue
        seen.add(key)

        has_audio = f.get("acodec") not in (None, "none")
        note = f.get("format_note") or ""
        filesize = f.get("filesize") or f.get("filesize_approx") or 0

        results.append({
            "format_id": format_id,
            "label": f"{height}p" + (f" {f.get('fps')}fps" if f.get("fps") else ""),
            "height": height,
            "ext": ext,
            "fps": f.get("fps"),
            "has_audio": has_audio,
            "filesize": filesize,
            "note": note,
        })

    results.sort(key=lambda x: (x["height"], x["fps"] or 0), reverse=True)
    return results


def _ytdlp_download(url: str, out_path: Path, format_id: Optional[str] = None) -> dict:
    if not YTDLP_AVAILABLE:
        raise RuntimeError("yt-dlp غير مثبت.")

    if format_id:
        fmt = f"{format_id}+bestaudio/best[format_id={format_id}]/best"
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "format": fmt,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        final_path = Path(ydl.prepare_filename(info))
        if not final_path.exists():
            for ext in ("mp4", "mkv", "webm"):
                candidate = final_path.with_suffix(f".{ext}")
                if candidate.exists():
                    final_path = candidate
                    break
        info["_final_path"] = str(final_path)
        return info


# =====================================================================
#                       VIDEO — PYTUBEFIX
# =====================================================================
def _pytubefix_build(url: str):
    if not PYTUBEFIX_AVAILABLE:
        raise RuntimeError("pytubefix غير مثبت.")

    try:
        return PyTubeYouTube(url, use_po_token=True)
    except TypeError:
        return PyTubeYouTube(url)
    except Exception as e:
        print(f"   ℹ️ use_po_token فشل ({e})، محاولة بدونها...", flush=True)
        return PyTubeYouTube(url)


def _pytubefix_info(url: str) -> dict:
    yt = _pytubefix_build(url)

    try:
        title = yt.title
    except PytubeFixException as e:
        raise ValueError(f"تعذر جلب الفيديو: {e}")

    duration = yt.length or 0
    thumbnail = yt.thumbnail_url
    uploader = yt.author

    formats: list = []
    seen: set = set()

    for s in yt.streams.filter(progressive=True, file_extension="mp4"):
        height_str = s.resolution or ""
        h = int(height_str.replace("p", "")) if height_str.endswith("p") else 0
        if h in seen:
            continue
        seen.add(h)
        formats.append({
            "format_id": str(s.itag),
            "label": height_str or "—",
            "height": h,
            "ext": s.subtype or "mp4",
            "fps": s.fps,
            "has_audio": True,
            "filesize": s.filesize or 0,
            "note": "progressive",
        })

    for s in yt.streams.filter(adaptive=True, file_extension="mp4", only_video=True):
        height_str = s.resolution or ""
        h = int(height_str.replace("p", "")) if height_str.endswith("p") else 0
        if h in seen or h < 720:
            continue
        seen.add(h)
        formats.append({
            "format_id": str(s.itag),
            "label": f"{height_str} (فيديو فقط)",
            "height": h,
            "ext": s.subtype or "mp4",
            "fps": s.fps,
            "has_audio": False,
            "filesize": s.filesize or 0,
            "note": "adaptive",
        })

    formats.sort(key=lambda x: (x["height"], x["fps"] or 0), reverse=True)

    return {
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "uploader": uploader,
        "formats": formats,
    }


def _pytubefix_download(url: str, out_path: Path, format_id: Optional[str] = None) -> Path:
    yt = _pytubefix_build(url)

    if format_id:
        stream = yt.streams.get_by_itag(int(format_id))
        if not stream:
            raise ValueError(f"الجودة {format_id} غير متاحة.")
    else:
        stream = (
            yt.streams
              .filter(progressive=True, file_extension="mp4")
              .order_by("resolution")
              .desc()
              .first()
        )
        if not stream:
            stream = yt.streams.get_highest_resolution()

    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = stream.download(output_path=str(out_dir), filename=out_path.name)
    return Path(filename)


# =====================================================================
#                       VIDEO — UNIFIED HELPERS
# =====================================================================
async def _get_info(url: str) -> dict:
    source = detect_source(url)

    print("=" * 60, flush=True)
    print(f"🔍 _get_info", flush=True)
    print(f"   URL: {url}", flush=True)
    print(f"   detect_source: {source}", flush=True)
    print(f"   PYTUBEFIX_AVAILABLE: {PYTUBEFIX_AVAILABLE}", flush=True)
    print(f"   PYTUBEFIX_VERSION: {PYTUBEFIX_VERSION}", flush=True)
    print("=" * 60, flush=True)

    if source == "youtube" and PYTUBEFIX_AVAILABLE:
        try:
            print("   → Using pytubefix...", flush=True)
            data = await asyncio.to_thread(_pytubefix_info, url)
            data["source"] = "youtube"
            print("   ✅ pytubefix succeeded!", flush=True)
            return data
        except Exception as e:
            print(f"   ⚠️ pytubefix failed: {type(e).__name__}: {e}", flush=True)
            print("   → Falling back to yt-dlp...", flush=True)

    print("   → Using yt-dlp...", flush=True)
    info = await asyncio.to_thread(_ytdlp_extract_info, url)
    return {
        "title": info.get("title") or "video",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "formats": _ytdlp_list_formats(info),
        "source": source,
    }


async def _download_video(
    url: str,
    out_path: Path,
    format_id: Optional[str],
    source: str,
) -> Path:
    if source == "youtube" and PYTUBEFIX_AVAILABLE:
        try:
            print(f"   → Downloading via pytubefix (format_id={format_id})", flush=True)
            return await asyncio.to_thread(
                _pytubefix_download, url, out_path, format_id
            )
        except Exception as e:
            print(f"   ⚠️ pytubefix download failed: {e}", flush=True)
            print("   → Falling back to yt-dlp...", flush=True)

    print(f"   → Downloading via yt-dlp (format_id={format_id})", flush=True)
    info = await asyncio.to_thread(_ytdlp_download, url, out_path, format_id)
    return Path(info["_final_path"])


# =====================================================================
#                       VIDEO — ENDPOINTS
# =====================================================================
@router.post("/api/video/info", tags=["video"])
async def video_info(payload: InfoRequest):
    """يجلب معلومات الفيديو + قائمة الجودات بدون تنزيل."""
    url = str(payload.url)
    try:
        data = await _get_info(url)
    except Exception as e:
        if YTDLP_AVAILABLE and isinstance(e, yt_dlp.utils.DownloadError):
            raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")
        raise HTTPException(status_code=500, detail=f"خطأ غير متوقع: {e}")

    return {
        "success": True,
        "title": data.get("title") or "video",
        "duration": data.get("duration") or 0,
        "thumbnail": data.get("thumbnail"),
        "uploader": data.get("uploader"),
        "formats": data.get("formats") or [],
        "source": data.get("source") or "generic",
    }


@router.post("/api/video/fetch", tags=["video"])
async def fetch_video(payload: FetchRequest):
    """ينزّل الفيديو مؤقتاً بالجودة المختارة."""
    url = str(payload.url)
    format_id = payload.format_id
    source = payload.source or detect_source(url)

    try:
        data = await _get_info(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")

    title = data.get("title") or "video"
    duration = data.get("duration") or 0

    quality_label = "—"
    if format_id:
        for f in data.get("formats") or []:
            if str(f["format_id"]) == str(format_id):
                quality_label = f["label"]
                break

    video_id = uuid.uuid4().hex[:10]
    safe_title = _safe_filename(title, "video")
    out_path = PREVIEW_DIR / f"{safe_title}_{video_id}"

    try:
        final_path = await _download_video(url, out_path, format_id, source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل التنزيل: {e}")

    size = final_path.stat().st_size if final_path.exists() else 0
    filename = final_path.name

    if quality_label == "—":
        quality_label = "تلقائي"

    return {
        "success": True,
        "title": title,
        "duration": duration,
        "quality": quality_label,
        "size": size,
        "filename": filename,
        "url": url,
        "source": source,
        "preview_url": f"/media/preview/{filename}",
        "download_url": f"/media/preview/{filename}",
    }


@router.post("/api/video/save", tags=["video"])
async def save_video(payload: SaveRequest):
    """ينقل الفيديو من مجلد المعاينة إلى مجلد المكتبة الدائم."""
    filename = payload.filename
    if not filename:
        raise HTTPException(status_code=400, detail="اسم الملف مفقود.")

    filename = os.path.basename(filename)
    src = PREVIEW_DIR / filename
    dst = DOWNLOAD_DIR / filename

    # ✅ إذا كان منقولاً مسبقاً، لا تفعل شيئاً
    if dst.exists():
        return {
            "success": True,
            "saved_to": f"/media/downloads/{filename}",
            "title": payload.title,
            "already_saved": True,
        }

    if not src.exists():
        raise HTTPException(status_code=404, detail="الملف غير موجود في المعاينة.")

    try:
        src.replace(dst)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل الحفظ: {e}")

    return {
        "success": True,
        "saved_to": f"/media/downloads/{filename}",
        "title": payload.title,
    }


# =====================================================================
#                    CREATE PROJECT FROM VIDEO
# =====================================================================
@router.post("/api/projects/create-from-video", tags=["projects"])
async def create_project_from_video(
    payload: dict,
    session: AsyncSession = Depends(get_db),
):
    """
    إنشاء Project من فيديو تم تنزيله.

    التدفق:
    1) نقل الفيديو من media/preview/ → media/downloads/
    2) رفع الفيديو إلى Supabase Storage (إذا مُهيأ)
    3) إنشاء Project مع data = {video_url, video_path, local_path, ...}
    4) إرجاع project_id
    """
    filename = payload.get("filename")
    title = payload.get("title") or "مشروع جديد"

    if not filename:
        raise HTTPException(status_code=400, detail="اسم الملف مفقود.")

    filename = os.path.basename(filename)
    src = PREVIEW_DIR / filename
    dst = DOWNLOAD_DIR / filename

    # 1) نقل الملف (إذا لم يكن منقولاً مسبقاً)
    if not dst.exists():
        if not src.exists():
            raise HTTPException(status_code=404, detail="الملف غير موجود.")
        try:
            src.replace(dst)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"فشل نقل الملف: {e}")

    # 2) رفع إلى Supabase Storage
    video_url = None
    video_path = None       # ← Supabase key فقط عند النجاح
    local_path = str(dst)   # ← المسار المحلي دائماً

    if settings.supabase_configured:
        try:
            storage = SupabaseStorageAdapter()
            storage_key = f"videos/{filename}"

            saved_key = await storage.save(dst, storage_key)

            if saved_key:
                video_path = saved_key
                video_url = await storage.get_url(saved_key)
                print(f"✅ تم رفع الفيديو إلى Supabase: {video_url}", flush=True)
        except Exception as e:
            logger.warning(f"⚠️ فشل الرفع إلى Supabase: {e}")
            video_url = None
            video_path = None

    # fallback: static URL
    if not video_url:
        video_url = f"/media/downloads/{filename}"

    # 3) إنشاء Project
    project = Project(
        title=title,
        description=payload.get("description") or "",
        script=payload.get("script") or "",
        tags=payload.get("tags") or ["video-download"],
        brand_colors=BrandColors(),
        settings={},
    )

    # ⭐ حفظ بيانات الفيديو في data blob
    project.update_data({
        "video_url": video_url,
        "video_path": video_path,        # ← None إذا فشل الرفع
        "local_path": local_path,        # ← المسار المحلي دائماً
        "original_filename": filename,
        "source": payload.get("source") or "generic",
        "platform": payload.get("platform"),
        "total_duration": payload.get("duration") or 0,
        "created_from": "video_download",
    })

    repo = SQLProjectRepository(session)
    await repo.save(project)
    await session.commit()

    return {
        "success": True,
        "project_id": str(project.id),
        "id": str(project.id),
        "video_url": video_url,
    }


# =====================================================================
#                       PROJECTS — LIST
# =====================================================================
@router.get("/projects", response_class=HTMLResponse)
async def projects_page(
    request: Request,
    search: str = "",
    status: str = "",
    session: AsyncSession = Depends(get_db),
):
    repo = SQLProjectRepository(session)
    projects = await repo.list_all(
        limit=20, offset=0,
        search=search or None,
        status=status or None,
    )
    total = await repo.count(status=status or None)
    return templates.TemplateResponse(request, "projects/list.html", {
        "projects": projects,
        "total": total,
        "search": search,
        "status_filter": status,
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


# =====================================================================
#                       PROJECTS — NEW
# =====================================================================
@router.get("/projects/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    return templates.TemplateResponse(request, "projects/create.html", {
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


# =====================================================================
#                       PROJECTS — DETAIL
# =====================================================================
@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    project_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLProjectRepository(session)
    job_repo = SQLRenderJobRepository(session)

    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        return HTMLResponse("معرّف المشروع غير صالح", status_code=400)

    project = await repo.get(pid)
    if not project:
        return HTMLResponse("المشروع غير موجود", status_code=404)

    try:
        render_jobs = await job_repo.list_for_project(project.id)
    except Exception as e:
        print(f"⚠️ فشل جلب render_jobs: {e}", flush=True)
        render_jobs = []

    try:
        video_url = await _resolve_video_url(project)
    except Exception as e:
        print(f"⚠️ فشل _resolve_video_url: {e}", flush=True)
        video_url = None

    try:
        thumbnail_url = await _resolve_thumbnail_url(project)
    except Exception as e:
        print(f"⚠️ فشل _resolve_thumbnail_url: {e}", flush=True)
        thumbnail_url = None

    return templates.TemplateResponse(request, "projects/detail.html", {
        "project": project,
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "render_jobs": render_jobs,
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })


# =====================================================================
#                       PROJECTS — TIMELINE
# =====================================================================
@router.get("/projects/{project_id}/timeline", response_class=HTMLResponse)
async def project_timeline(
    project_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLProjectRepository(session)

    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        return HTMLResponse("معرّف المشروع غير صالح", status_code=400)

    project = await repo.get(pid)
    if not project:
        return HTMLResponse("المشروع غير موجود", status_code=404)

    # بناء scenes
    scenes = []
    try:
        if hasattr(project, "timeline") and project.timeline:
            tl = project.timeline
            for scene in (tl.scenes if hasattr(tl, "scenes") else []):
                scenes.append({
                    "id": str(scene.id),
                    "title": getattr(scene, "title", None) or f"مشهد {len(scenes)+1}",
                    "start_time": float(getattr(scene, "start_time", 0)),
                    "end_time": float(getattr(scene, "end_time", 0)),
                    "duration": float(getattr(scene, "duration", 0)),
                    "content": getattr(scene, "content", ""),
                })
    except Exception as e:
        print(f"⚠️ فشل استخراج timeline: {e}", flush=True)

    # fallback: تقسيم السكريبت
    if not scenes and project.script:
        paragraphs = [p.strip() for p in project.script.split("\n\n") if p.strip()]
        t = 0.0
        for i, para in enumerate(paragraphs):
            words = len(para.split())
            duration = max(words / 2.5, 2.0)
            scenes.append({
                "id": str(i),
                "title": f"مشهد {i+1}",
                "start_time": round(t, 2),
                "end_time": round(t + duration, 2),
                "duration": round(duration, 2),
                "content": para[:120],
            })
            t += duration

    # voice data
    voiceover_clips = []
    saved_voices = []
    try:
        if hasattr(project, "data") and isinstance(project.data, dict):
            voiceover_clips = [
                c for c in (project.data.get("clips") or [])
                if isinstance(c, dict) and c.get("type") == "audio"
            ]
            saved_voices = project.data.get("cloned_voices", []) or []
    except Exception as e:
        print(f"⚠️ فشل استخراج voice data: {e}", flush=True)

    return templates.TemplateResponse(request, "projects/timeline.html", {
        "project": project,
        "scenes": scenes,
        "scenes_json": json.dumps(scenes, ensure_ascii=False),
        "voiceover_clips": voiceover_clips,
        "saved_voices": saved_voices,
        "elevenlabs_configured": settings.elevenlabs_configured,
        "did_configured": settings.did_configured,
        "edge_tts_enabled": settings.EDGE_TTS_ENABLED,
        "active_page": "projects",
        "supabase": get_supabase_config(),
    })
