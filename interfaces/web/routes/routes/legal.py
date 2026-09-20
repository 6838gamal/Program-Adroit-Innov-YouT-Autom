"""Legal pages + video download API (all in one router)."""
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


class SaveRequest(BaseModel):
    url: str
    title: Optional[str] = None
    filename: Optional[str] = None


# ---------- Helpers ----------
def _safe_filename(name: str, fallback: str = "video") -> str:
    """ينظف اسم الملف من الرموز غير المسموحة."""
    if not name:
        return fallback
    name = re.sub(r"[^\w\s\-\.]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:120] or fallback


def _extract_info(url: str) -> dict:
    """يستخرج معلومات الفيديو بدون تحميله (metadata only)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        # لو كان playlist، خذ أول فيديو
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        return info


def _list_formats(info: dict) -> list[dict]:
    """يبني قائمة الجودات المتاحة (فيديو فقط أو فيديو+صوت)."""
    formats = info.get("formats") or []
    results = []
    seen = set()

    for f in formats:
        # تجاهل الصوت فقط
        if f.get("vcodec") in (None, "none"):
            continue

        height = f.get("height")
        ext = f.get("ext") or "mp4"
        format_id = f.get("format_id")
        if not format_id or not height:
            continue

        # مفتاح فريد لكل جودة
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

    # ترتيب من الأعلى للأدنى
    results.sort(key=lambda x: (x["height"], x["fps"] or 0), reverse=True)
    return results


def _download_video(url: str, out_path: Path, format_id: Optional[str] = None) -> dict:
    """
    ينزّل الفيديو:
    - إذا format_id محدد → استخدمه مع أفضل صوت
    - خلاف ذلك → أفضل جودة mp4 مع صوت مدموج
    """
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


# ---------- Endpoints ----------

@router.post("/api/video/info", tags=["video"])
async def video_info(payload: InfoRequest):
    """يجلب معلومات الفيديو + قائمة الجودات بدون تنزيل."""
    url = str(payload.url)
    try:
        info = await asyncio.to_thread(_extract_info, url)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ غير متوقع: {e}")

    formats = _list_formats(info)

    return {
        "success": True,
        "title": info.get("title") or "video",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "formats": formats,
    }


@router.post("/api/video/fetch", tags=["video"])
async def fetch_video(payload: FetchRequest):
    """ينزّل الفيديو مؤقتاً بالجودة المختارة (أو الأفضل افتراضياً)."""
    url = str(payload.url)
    format_id = payload.format_id

    # 1) الميتاداتا
    try:
        info = await asyncio.to_thread(_extract_info, url)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ غير متوقع: {e}")

    video_id = info.get("id") or uuid.uuid4().hex[:10]
    title = info.get("title") or "video"
    duration = info.get("duration") or 0

    # 2) تحديد اسم الجودة
    quality_label = "—"
    if format_id:
        for f in _list_formats(info):
            if f["format_id"] == format_id:
                quality_label = f["label"]
                break

    # 3) التنزيل
    temp_name = f"{_safe_filename(title, 'video')}_{video_id}"
    out_path = PREVIEW_DIR / temp_name

    try:
        final_info = await asyncio.to_thread(_download_video, url, out_path, format_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل التنزيل: {e}")

    final_path = Path(final_info["_final_path"])
    size = final_path.stat().st_size if final_path.exists() else 0
    filename = final_path.name

    if quality_label == "—":
        quality_label = (
            final_info.get("format_note")
            or (f"{final_info.get('height')}p" if final_info.get("height") else None)
            or final_info.get("resolution")
            or "—"
        )

    return {
        "success": True,
        "title": title,
        "duration": duration,
        "quality": quality_label,
        "size": size,
        "filename": filename,
        "url": url,
        "preview_url": f"/media/preview/{filename}",
        "download_url": f"/media/preview/{filename}",
    }


@router.post("/api/video/save", tags=["video"])
async def save_video(payload: SaveRequest):
    """ينقل الفيديو من مجلد المعاينة إلى مجلد المكتبة الدائم."""
    filename = payload.filename
    if not filename:
        raise HTTPException(status_code=400, detail="اسم الملف مفقود.")

    # منع Path Traversal
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
