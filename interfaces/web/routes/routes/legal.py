"""Legal pages + video download API (hybrid: pytubefix for YouTube, yt-dlp for others)."""
from __future__ import annotations

import os
import re
import uuid
import asyncio
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl

from config.settings import settings

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

# استيراد pytubefix بشكل آمن (لو لم يكن مثبتاً، نتجاهل اليوتيوب عبره)
try:
    from pytubefix import YouTube as PyTubeYouTube
    from pytubefix.exceptions import PytubeFixException
    PYTUBEFIX_AVAILABLE = True
except ImportError:
    PYTUBEFIX_AVAILABLE = False
    PyTubeYouTube = None
    PytubeFixException = Exception


router = APIRouter()


# =====================================================================
#                            LEGAL PAGES
# =====================================================================

@router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy_page(request: Request):
    """صفحة سياسة الخصوصية."""
    return templates.TemplateResponse(request, "privacy_policy.html", {
        "active_page": "privacy_policy",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })


@router.get("/terms-of-service", response_class=HTMLResponse)
async def terms_of_service_page(request: Request):
    """صفحة شروط الخدمة."""
    return templates.TemplateResponse(request, "terms_of_service.html", {
        "active_page": "terms_of_service",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })


@router.get("/test-code", response_class=HTMLResponse)
async def test_code_page(request: Request):
    """صفحة تجريبية لتنزيل الفيديو من الرابط مع معاينة."""
    return templates.TemplateResponse(request, "test_code.html", {
        "active_page": "test_code",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })


# =====================================================================
#                            VIDEO API
# =====================================================================

MEDIA_ROOT = Path("media")
PREVIEW_DIR = MEDIA_ROOT / "preview"
DOWNLOAD_DIR = MEDIA_ROOT / "downloads"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Schemas ----------
class InfoRequest(BaseModel):
    url: HttpUrl


class FetchRequest(BaseModel):
    url: HttpUrl
    format_id: Optional[str] = None
    source: Optional[str] = None   # "youtube" أو "generic" (يُرسل من الـ info)


class SaveRequest(BaseModel):
    url: str
    title: Optional[str] = None
    filename: Optional[str] = None


# ---------- Helpers ----------
def is_youtube(url: str) -> bool:
    """يتحقق إن كان الرابط من يوتيوب."""
    return any(d in url.lower() for d in (
        "youtube.com", "youtu.be", "youtube-nocookie.com", "m.youtube.com"
    ))


def _safe_filename(name: str, fallback: str = "video") -> str:
    """ينظف اسم الملف من الرموز غير المسموحة."""
    if not name:
        return fallback
    name = re.sub(r"[^\w\s\-\.]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:120] or fallback


# =====================================================================
#                          YT-DLP (Generic)
# =====================================================================

def _ytdlp_extract_info(url: str) -> dict:
    """يستخرج معلومات الفيديو عبر yt-dlp بدون تحميل."""
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
    """يبني قائمة الجودات من yt-dlp."""
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
    """ينزّل الفيديو عبر yt-dlp."""
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
#                          PYTUBEFIX (YouTube)
# =====================================================================

def _pytubefix_info(url: str) -> dict:
    """يجلب معلومات فيديو يوتيوب + قائمة الجودات عبر pytubefix."""
    if not PYTUBEFIX_AVAILABLE:
        raise RuntimeError("pytubefix غير مثبت.")

    try:
        yt = PyTubeYouTube(url)
        title = yt.title
    except PytubeFixException as e:
        raise ValueError(f"تعذر جلب الفيديو: {e}")

    duration = yt.length or 0
    thumbnail = yt.thumbnail_url
    uploader = yt.author

    formats: list[dict] = []
    seen: set = set()

    # progressive streams (فيديو + صوت)
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

    # adaptive streams (فيديو فقط) - نعرض فقط ≥ 720p
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
    """ينزّل الفيديو عبر pytubefix."""
    if not PYTUBEFIX_AVAILABLE:
        raise RuntimeError("pytubefix غير مثبت.")

    yt = PyTubeYouTube(url)

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
#                          UNIFIED HELPERS
# =====================================================================

async def _get_info(url: str) -> dict:
    """
    يجلب المعلومات من المكتبة المناسبة:
    - YouTube → pytubefix (مع fallback إلى yt-dlp)
    - غيره → yt-dlp
    """
    if is_youtube(url) and PYTUBEFIX_AVAILABLE:
        try:
            data = await asyncio.to_thread(_pytubefix_info, url)
            data["source"] = "youtube"
            return data
        except Exception as e:
            # fallback إلى yt-dlp
            print(f"⚠️ pytubefix فشل، سيتم استخدام yt-dlp: {e}")

    # yt-dlp
    info = await asyncio.to_thread(_ytdlp_extract_info, url)
    return {
        "title": info.get("title") or "video",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "formats": _ytdlp_list_formats(info),
        "source": "generic",
    }


async def _download_video(
    url: str,
    out_path: Path,
    format_id: Optional[str],
    source: str,
) -> Path:
    """
    ينزّل الفيديو من المكتبة المناسبة حسب source.
    source: "youtube" أو "generic"
    """
    if source == "youtube" and PYTUBEFIX_AVAILABLE:
        try:
            return await asyncio.to_thread(
                _pytubefix_download, url, out_path, format_id
            )
        except Exception as e:
            print(f"⚠️ pytubefix فشل في التنزيل، سيتم استخدام yt-dlp: {e}")

    # yt-dlp
    info = await asyncio.to_thread(_ytdlp_download, url, out_path, format_id)
    return Path(info["_final_path"])


# =====================================================================
#                          ENDPOINTS
# =====================================================================

@router.post("/api/video/info", tags=["video"])
async def video_info(payload: InfoRequest):
    """يجلب معلومات الفيديو + قائمة الجودات بدون تنزيل."""
    url = str(payload.url)
    try:
        data = await _get_info(url)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")
    except Exception as e:
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
    source = payload.source

    # إذا لم يُرسل source، اكتشف تلقائياً
    if not source:
        source = "youtube" if is_youtube(url) and PYTUBEFIX_AVAILABLE else "generic"

    # 1) جلب الميتاداتا
    try:
        data = await _get_info(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")

    title = data.get("title") or "video"
    duration = data.get("duration") or 0

    # 2) تحديد اسم الجودة
    quality_label = "—"
    if format_id:
        for f in data.get("formats") or []:
            if str(f["format_id"]) == str(format_id):
                quality_label = f["label"]
                break

    # 3) التنزيل
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
    if not src.exists():
        raise HTTPException(status_code=404, detail="الملف غير موجود في المعاينة.")

    dst = DOWNLOAD_DIR / filename
    try:
        src.replace(dst)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل الحفظ: {e}")

    return {
        "success": True,
        "saved_to": f"/media/downloads/{filename}",
        "title": payload.title,
    }
