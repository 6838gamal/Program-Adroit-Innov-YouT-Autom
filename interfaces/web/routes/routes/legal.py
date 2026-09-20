"""Legal pages: privacy policy + terms of service + test code + video API."""
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

video_router = APIRouter(prefix="/api/video", tags=["video"])

MEDIA_ROOT = Path("media")
PREVIEW_DIR = MEDIA_ROOT / "preview"
DOWNLOAD_DIR = MEDIA_ROOT / "downloads"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Schemas ----------
class FetchRequest(BaseModel):
    url: HttpUrl


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
        "format": "best[ext=mp4]/best",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _download_video(url: str, out_path: Path) -> dict:
    """ينزّل الفيديو إلى المسار المحدد ويعيد المعلومات النهائية."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "format": "best[ext=mp4]/best",
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
@video_router.post("/fetch")
async def fetch_video(payload: FetchRequest):
    """يجلب معلومات الفيديو وينزّله مؤقتاً للمعاينة."""
    url = str(payload.url)

    # 1) استخراج الميتاداتا
    try:
        info = await asyncio.to_thread(_extract_info, url)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"تعذر جلب الفيديو: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ غير متوقع: {e}")

    video_id = info.get("id") or uuid.uuid4().hex[:10]
    title = info.get("title") or "video"
    duration = info.get("duration") or 0
    quality = f"{info.get('height', '?')}p" if info.get("height") else "—"

    # 2) تنزيل الفيديو مؤقتاً
    temp_name = f"{_safe_filename(title, 'video')}_{video_id}"
    out_path = PREVIEW_DIR / temp_name

    try:
        final_info = await asyncio.to_thread(_download_video, url, out_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل التنزيل: {e}")

    final_path = Path(final_info["_final_path"])
    size = final_path.stat().st_size if final_path.exists() else 0
    filename = final_path.name

    return {
        "success": True,
        "title": title,
        "duration": duration,
        "quality": quality,
        "size": size,
        "filename": filename,
        "url": url,
        "preview_url": f"/media/preview/{filename}",
        "download_url": f"/media/preview/{filename}",
    }


@video_router.post("/save")
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
