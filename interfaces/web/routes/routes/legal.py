"""Legal pages + image download API (gallery-dl based)."""
from __future__ import annotations

import os
import re
import uuid
import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl

from config.settings import settings

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

# ===== استيراد gallery-dl بشكل آمن =====
GALLERY_DL_AVAILABLE = False
GALLERY_DL_VERSION = "not installed"
try:
    import gallery_dl
    GALLERY_DL_AVAILABLE = True
    GALLERY_DL_VERSION = getattr(gallery_dl, "__version__", "unknown")
    print(f"✅ gallery-dl loaded successfully (version {GALLERY_DL_VERSION})", flush=True)
except ImportError as e:
    print(f"❌ gallery-dl NOT available: {e}", flush=True)
    print(f"   Install with: pip install gallery-dl", flush=True)

# ===== التحقق من وجود الأمر في النظام =====
GALLERY_DL_CLI = shutil.which("gallery-dl")
if GALLERY_DL_CLI:
    print(f"✅ gallery-dl CLI found: {GALLERY_DL_CLI}", flush=True)
else:
    print(f"⚠️ gallery-dl CLI not found in PATH", flush=True)


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
    """صفحة تجريبية لتنزيل الصور من الرابط مع معاينة."""
    return templates.TemplateResponse(request, "test_code.html", {
        "active_page": "test_code",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "gallery_dl_available": GALLERY_DL_AVAILABLE,
        "gallery_dl_version": GALLERY_DL_VERSION,
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })


# =====================================================================
#                            IMAGE API
# =====================================================================

MEDIA_ROOT = Path("media")
PREVIEW_DIR = MEDIA_ROOT / "preview"
DOWNLOAD_DIR = MEDIA_ROOT / "downloads"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Schemas ----------
class ImageInfoRequest(BaseModel):
    url: HttpUrl


class ImageFetchRequest(BaseModel):
    url: HttpUrl
    source: Optional[str] = None   # "facebook" | "instagram" | ...


class SaveImagesRequest(BaseModel):
    images: List[dict]
    source: Optional[str] = None


# ---------- Source detection ----------
def detect_source(url: str) -> str:
    """يكتشف مصدر الصور من الرابط."""
    u = url.lower()
    if any(d in u for d in ("facebook.com", "fb.watch", "fb.com", "m.facebook.com")):
        return "facebook"
    if "instagram.com" in u or "instagr.am" in u:
        return "instagram"
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    if "pinterest.com" in u or "pin.it" in u:
        return "pinterest"
    if "tiktok.com" in u:
        return "tiktok"
    if "reddit.com" in u:
        return "reddit"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "generic"


def source_label(src: str) -> str:
    labels = {
        "facebook": "فيسبوك",
        "instagram": "إنستغرام",
        "twitter": "تويتر / X",
        "pinterest": "بينتريست",
        "tiktok": "تيك توك",
        "reddit": "Reddit",
        "youtube": "يوتيوب",
        "generic": "رابط عام",
    }
    return labels.get(src, src)


def _safe_filename(name: str, fallback: str = "image") -> str:
    """ينظف اسم الملف من الرموز غير المسموحة."""
    if not name:
        return fallback
    name = re.sub(r"[^\w\s\-\.]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:120] or fallback


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".svg"}


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


# =====================================================================
#                       GALLERY-DL INTEGRATION
# =====================================================================

def _gallery_dl_run_sync(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """
    يشغّل gallery-dl CLI لتحميل الصور.
    يرجع dict يحتوي على: success, files, error, stdout, stderr
    """
    import subprocess
    import time

    start = time.perf_counter()

    if not GALLERY_DL_CLI:
        return {
            "success": False,
            "files": [],
            "error": "gallery-dl CLI غير مثبت (pip install gallery-dl)",
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
        }

    cmd = [
        GALLERY_DL_CLI,
        "--dest", str(out_dir),
        "--no-part",
        "-q",  # quiet
    ]
    if cookies_from_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_from_browser]
    cmd.append(url)

    print(f"🎬 [gallery-dl] Running: {' '.join(cmd)}", flush=True)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        duration = (time.perf_counter() - start) * 1000

        files = [p for p in out_dir.rglob("*") if p.is_file() and _is_image_file(p)]

        print(
            f"🎬 [gallery-dl] rc={result.returncode}, "
            f"files={len(files)}, {duration:.0f}ms",
            flush=True,
        )

        if result.stderr:
            print(f"🎬 [gallery-dl] stderr: {result.stderr[:500]}", flush=True)

        return {
            "success": result.returncode == 0 and len(files) > 0,
            "files": files,
            "error": None if result.returncode == 0 else f"exit={result.returncode}",
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "duration_ms": duration,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "files": [],
            "error": f"timeout after {timeout}s",
            "stdout": "",
            "stderr": "",
            "duration_ms": (time.perf_counter() - start) * 1000,
        }
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "duration_ms": (time.perf_counter() - start) * 1000,
        }


async def _gallery_dl_download(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
) -> dict:
    """غلاف async حول gallery-dl."""
    return await asyncio.to_thread(
        _gallery_dl_run_sync, url, out_dir, cookies_from_browser
    )


# =====================================================================
#                          ENDPOINTS
# =====================================================================

@router.get("/api/image/download-engines", tags=["image"])
async def download_engines():
    """يرجع المحركات المتاحة للتشخيص."""
    return {
        "success": True,
        "engines": {
            "gallery-dl": GALLERY_DL_AVAILABLE,
            "gallery-dl-cli": bool(GALLERY_DL_CLI),
            "gallery-dl-version": GALLERY_DL_VERSION,
        },
    }


@router.post("/api/image/info", tags=["image"])
async def image_info(payload: ImageInfoRequest):
    """
    يجلب معلومات أولية عن الرابط (المصدر، عدد الصور المتوقع).
    ملاحظة: gallery-dl لا يوفر info بدون تحميل، لذا نرجع بيانات أساسية.
    """
    url = str(payload.url)
    source = detect_source(url)

    return {
        "success": True,
        "source": source,
        "source_label": source_label(source),
        "gallery_dl_available": GALLERY_DL_AVAILABLE,
        "url": url,
    }


@router.post("/api/image/fetch", tags=["image"])
async def fetch_images(payload: ImageFetchRequest):
    """
    ينزّل كل الصور من الرابط عبر gallery-dl.
    يرجع قائمة بالصور المحمّلة.
    """
    url = str(payload.url)
    source = payload.source or detect_source(url)

    # تحقق من توفر gallery-dl
    if not GALLERY_DL_CLI:
        raise HTTPException(
            status_code=503,
            detail="gallery-dl غير مثبت على السيرفر. راسل المسؤول.",
        )

    # مجلد مؤقت فريد لكل طلب
    job_id = uuid.uuid4().hex[:10]
    out_dir = PREVIEW_DIR / f"job_{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # cookies من الإعدادات (إن وجدت)
    cookies_from_browser = getattr(settings, "cookies_from_browser", None)

    print(f"=" * 60, flush=True)
    print(f"🌐 [image/fetch] URL: {url}", flush=True)
    print(f"   source: {source}", flush=True)
    print(f"   out_dir: {out_dir}", flush=True)
    print(f"   cookies_from_browser: {cookies_from_browser}", flush=True)
    print(f"=" * 60, flush=True)

    # شغّل gallery-dl
    try:
        result = await _gallery_dl_download(
            url, out_dir, cookies_from_browser
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل التحميل: {e}")

    if not result["success"]:
        # فشل — أرجع تفاصيل
        raise HTTPException(
            status_code=422,
            detail={
                "error": "فشل تحميل الصور من الرابط",
                "reason": result.get("error"),
                "stderr": result.get("stderr", "")[:300],
                "source": source,
            },
        )

    # ابنِ قائمة الصور
    images = []
    for f in result["files"]:
        try:
            size = f.stat().st_size
        except Exception:
            size = 0

        # المسار النسبي داخل media
        rel_path = f.relative_to(MEDIA_ROOT)
        public_url = f"/media/{rel_path}"

        images.append({
            "url": public_url,
            "filename": f.name,
            "size": size,
            "path": str(f),
        })

    print(f"✅ [image/fetch] Downloaded {len(images)} images", flush=True)

    return {
        "success": True,
        "images": images,
        "count": len(images),
        "source": source,
        "source_label": source_label(source),
        "job_id": job_id,
        "duration_ms": result.get("duration_ms", 0),
    }


@router.post("/api/image/save", tags=["image"])
async def save_images(payload: SaveImagesRequest):
    """
    ينقل الصور المحددة من مجلد المعاينة إلى مكتبة التحميلات الدائمة.
    """
    images = payload.images or []
    if not images:
        raise HTTPException(status_code=400, detail="لا توجد صور للحفظ.")

    saved = []
    failed = []

    for img in images:
        filename = img.get("filename")
        if not filename:
            continue

        # ابحث عن الملف في مجلد المعاينة
        # (نستخدم rglob للبحث في كل مجلدات job_*)
        found = None
        for candidate in PREVIEW_DIR.rglob(filename):
            if candidate.is_file():
                found = candidate
                break

        if not found:
            failed.append({"filename": filename, "error": "not found"})
            continue

        # انسخ إلى مجلد التحميلات
        dst = DOWNLOAD_DIR / found.name
        try:
            shutil.copy2(found, dst)
            saved.append({
                "filename": dst.name,
                "url": f"/media/downloads/{dst.name}",
            })
            print(f"💾 [image/save] Saved: {dst}", flush=True)
        except Exception as e:
            failed.append({"filename": filename, "error": str(e)})

    return {
        "success": True,
        "saved": len(saved),
        "failed": failed,
        "images": saved,
    }


@router.post("/api/image/cleanup", tags=["image"])
async def cleanup_preview():
    """
    يحذف كل مجلدات المعاينة المؤقتة.
    يمكن استدعاؤه دورياً لتنظيف السيرفر.
    """
    deleted = 0
    try:
        for job_dir in PREVIEW_DIR.glob("job_*"):
            if job_dir.is_dir():
                shutil.rmtree(job_dir, ignore_errors=True)
                deleted += 1
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل التنظيف: {e}")

    return {"success": True, "deleted_dirs": deleted}
