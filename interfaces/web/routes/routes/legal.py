"""Legal pages + image download API (gallery-dl based).

نسخة محسّنة:
- تحقق حقيقي من الصور (Pillow + magic bytes + content-type + أبعاد)
- رفض صفحات HTML والملفات التالفة والصور صغيرة الأبعاد
- معالجة أفضل لأخطاء gallery-dl (تمييز الحالات)
- اكتشاف روابط المشاركة وتحذير المستخدم
- استخدام _safe_filename عند الحفظ
- save_images آمن (يعتمد على job_id + اسم الملف)
- cleanup_preview يحذف المجلدات القديمة فقط
- إزالة SVG من الامتدادات المسموحة
"""
from __future__ import annotations

import os
import re
import io
import time
import uuid
import asyncio
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl

from config.settings import settings

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

# ===== استيراد Pillow بشكل آمن =====
try:
    from PIL import Image, UnidentifiedImageError
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    UnidentifiedImageError = Exception
    print("❌ Pillow NOT available: pip install Pillow", flush=True)

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
    cookies_from_browser: Optional[str] = None  # اختياري: chrome|firefox|...


class SaveImagesRequest(BaseModel):
    job_id: str                    # مطلوب الآن لضمان الأمان
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


def is_share_link(url: str) -> bool:
    """
    يكتشف روابط المشاركة التي غالباً لا تكون روابط صور مباشرة.
    مثل: facebook.com/share/p/...  أو  instagram.com/share/...
    """
    u = url.lower()
    patterns = (
        "/share/p/",
        "/share/r/",
        "/share/v/",
        "/share/",
        "fb.watch/",
        "pin.it/",
    )
    return any(p in u for p in patterns)


def _safe_filename(name: str, fallback: str = "image") -> str:
    """ينظف اسم الملف من الرموز غير المسموحة."""
    if not name:
        return fallback
    # احتفظ فقط بالحروف والأرقام والشرطات والنقاط
    name = re.sub(r"[^\w\s\-\.]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    # أزل النقاط المتكررة في البداية
    name = name.lstrip(".")
    return name[:120] or fallback


# امتدادات مسموحة (SVG مرفوض لأسباب أمنية)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# إعدادات التحقق
MIN_IMAGE_BYTES = 2_000          # 2 KB
MAX_IMAGE_BYTES = 30_000_000     # 30 MB
MIN_IMAGE_DIMENSION = 50         # بكسل


def _is_image_extension(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _sniff_image_format(data: bytes) -> Optional[str]:
    """
    يكتشف صيغة الصورة من البايتات الأولى (magic bytes).
    يرجع اسم الصيغة أو None.
    """
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[:2] == b"BM":
        return "BMP"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    return None


def is_valid_previewable_image(path: Path) -> Tuple[bool, str, Optional[dict]]:
    """
    يتحقق أن الملف صورة فعلية قابلة للمعاينة.

    يرجع (صالح؟, سبب, معلومات_اختيارية)
    """
    if not PIL_AVAILABLE:
        # إذا لم تتوفر Pillow، نعتمد على magic bytes فقط
        try:
            with open(path, "rb") as fh:
                head = fh.read(32)
        except OSError as e:
            return False, f"unreadable: {e}", None
        fmt = _sniff_image_format(head)
        if not fmt:
            return False, "not a recognized image format", None
        return True, "ok (no Pillow)", {"format": fmt}

    try:
        size = path.stat().st_size
    except OSError as e:
        return False, f"unreadable: {e}", None

    if size < MIN_IMAGE_BYTES:
        return False, f"too small ({size} bytes)", None
    if size > MAX_IMAGE_BYTES:
        return False, f"too large ({size} bytes)", None

    # فحص magic bytes أولاً (سريع)
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
    except OSError as e:
        return False, f"unreadable: {e}", None

    sniffed = _sniff_image_format(head)
    if not sniffed:
        return False, "not a recognized image format (magic bytes)", None

    # فحص فعلي باستخدام Pillow
    try:
        with Image.open(path) as im:
            im.verify()
        # verify() يغلق الصورة، أعد الفتح للأبعاد
        with Image.open(path) as im:
            w, h = im.size
            fmt = (im.format or sniffed).upper()
            mode = im.mode
    except UnidentifiedImageError:
        return False, "Pillow: unidentified image", None
    except Exception as e:
        return False, f"Pillow verify failed: {e}", None

    if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
        return False, f"dimensions too small ({w}x{h})", None

    # رفض SVG صراحة (احتياطي)
    if fmt == "SVG":
        return False, "svg not allowed", None

    return True, "ok", {"format": fmt, "width": w, "height": h, "size": size, "mode": mode}


def _filter_valid_images(files: List[Path]) -> Tuple[List[dict], List[dict]]:
    """
    يفحص قائمة ملفات، يرجع (صالح, مرفوض).
    كل عنصر dict يحتوي على: path, filename, size, info/error
    """
    valid: List[dict] = []
    rejected: List[dict] = []

    for f in files:
        if not _is_image_extension(f):
            rejected.append({
                "path": str(f),
                "filename": f.name,
                "error": f"extension not allowed: {f.suffix}",
            })
            continue

        ok, reason, info = is_valid_previewable_image(f)
        if not ok:
            rejected.append({
                "path": str(f),
                "filename": f.name,
                "error": reason,
            })
            continue

        try:
            size = f.stat().st_size
        except OSError:
            size = 0

        valid.append({
            "path": str(f),
            "filename": f.name,
            "size": size,
            "info": info or {},
        })

    return valid, rejected


# =====================================================================
#                       GALLERY-DL INTEGRATION
# =====================================================================

# رموز خروج gallery-dl المهمة
GDL_EXIT_OK = 0
GDL_EXIT_UNSUPPORTED = 64
GDL_EXIT_AUTH = 77


def _classify_gallery_dl_error(returncode: int, stderr: str) -> str:
    """يترجم خطأ gallery-dl إلى رسالة مفهومة."""
    s = (stderr or "").lower()
    if returncode == GDL_EXIT_UNSUPPORTED or "unsupported url" in s:
        return "الرابط غير مدعوم من gallery-dl"
    if returncode == GDL_EXIT_AUTH or "login" in s or "authentication" in s or "cookies" in s:
        return "الرابط يتطلب تسجيل دخول أو كوكيز"
    if "not found" in s or "404" in s:
        return "الصفحة غير موجودة"
    if "private" in s:
        return "المحتوى خاص"
    if returncode != 0:
        return f"فشل gallery-dl (exit={returncode})"
    return "فشل غير معروف"


def _gallery_dl_run_sync(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """
    يشغّل gallery-dl CLI لتحميل الصور.
    يرجع dict يحتوي على: success, files, error, stdout, stderr, duration_ms
    """
    import subprocess

    start = time.perf_counter()

    if not GALLERY_DL_CLI:
        return {
            "success": False,
            "files": [],
            "error": "gallery-dl CLI غير مثبت (pip install gallery-dl)",
            "error_kind": "cli_missing",
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
        # يوضع قبل الرابط
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

        all_files = [p for p in out_dir.rglob("*") if p.is_file()]
        image_files = [p for p in all_files if _is_image_extension(p)]

        print(
            f"🎬 [gallery-dl] rc={result.returncode}, "
            f"files={len(all_files)} (images={len(image_files)}), {duration:.0f}ms",
            flush=True,
        )

        if result.stderr:
            print(f"🎬 [gallery-dl] stderr: {result.stderr[:500]}", flush=True)

        success = result.returncode == 0 and len(image_files) > 0
        error_kind = None
        error_msg = None
        if not success:
            if result.returncode != 0:
                error_kind = "gallery_dl_failed"
                error_msg = _classify_gallery_dl_error(result.returncode, result.stderr or "")
            else:
                error_kind = "no_images"
                error_msg = "لم يتم العثور على صور في الرابط"

        return {
            "success": success,
            "files": image_files,
            "all_files": all_files,
            "error": error_msg,
            "error_kind": error_kind,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "duration_ms": duration,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "files": [],
            "all_files": [],
            "error": f"timeout after {timeout}s",
            "error_kind": "timeout",
            "stdout": "",
            "stderr": "",
            "duration_ms": (time.perf_counter() - start) * 1000,
        }
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "all_files": [],
            "error": str(e),
            "error_kind": "exception",
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
            "pillow": PIL_AVAILABLE,
        },
    }


@router.post("/api/image/info", tags=["image"])
async def image_info(payload: ImageInfoRequest):
    """
    يجلب معلومات أولية عن الرابط (المصدر، نوع الرابط، التحذيرات).
    """
    url = str(payload.url)
    source = detect_source(url)
    share = is_share_link(url)

    warnings: List[str] = []
    if share:
        warnings.append(
            "هذا رابط مشاركة وليس رابط صورة مباشر. "
            "قد لا يعمل مع gallery-dl بدون معالجة إضافية."
        )
    if source == "facebook":
        warnings.append(
            "فيسبوك غالباً يتطلب كوكيز للوصول إلى الصور. "
            "قد تحتاج لتمرير cookies_from_browser."
        )

    return {
        "success": True,
        "source": source,
        "source_label": source_label(source),
        "is_share_link": share,
        "gallery_dl_available": GALLERY_DL_AVAILABLE,
        "gallery_dl_cli": bool(GALLERY_DL_CLI),
        "pillow_available": PIL_AVAILABLE,
        "warnings": warnings,
        "url": url,
    }


@router.post("/api/image/fetch", tags=["image"])
async def fetch_images(payload: ImageFetchRequest):
    """
    ينزّل كل الصور من الرابط عبر gallery-dl،
    ثم يتحقق أن كل ملف صورة فعلية قابلة للمعاينة.
    """
    url = str(payload.url)
    source = detect_source(url)

    # تحقق من توفر gallery-dl
    if not GALLERY_DL_CLI:
        raise HTTPException(
            status_code=503,
            detail="gallery-dl غير مثبت على السيرفر. راسل المسؤول.",
        )

    if not PIL_AVAILABLE:
        # نستمر لكن نحذّر (التحقق سيكون أضعف)
        print("⚠️ [image/fetch] Pillow غير متوفر، التحقق سيكون محدوداً", flush=True)

    # مجلد مؤقت فريد لكل طلب
    job_id = uuid.uuid4().hex[:10]
    out_dir = PREVIEW_DIR / f"job_{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # cookies من الطلب أو من الإعدادات
    cookies_from_browser = (
        payload.cookies_from_browser
        or getattr(settings, "cookies_from_browser", None)
    )

    print(f"=" * 60, flush=True)
    print(f"🌐 [image/fetch] URL: {url}", flush=True)
    print(f"   source: {source}", flush=True)
    print(f"   share_link: {is_share_link(url)}", flush=True)
    print(f"   out_dir: {out_dir}", flush=True)
    print(f"   cookies_from_browser: {cookies_from_browser}", flush=True)
    print(f"   pillow_available: {PIL_AVAILABLE}", flush=True)
    print(f"=" * 60, flush=True)

    # شغّل gallery-dl
    try:
        result = await _gallery_dl_download(
            url, out_dir, cookies_from_browser
        )
    except Exception as e:
        # نظّف المجلد عند الفشل الكامل
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"فشل التحميل: {e}")

    if not result["success"]:
        # نظّف المجلد
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "فشل تحميل الصور من الرابط",
                "reason": result.get("error"),
                "error_kind": result.get("error_kind"),
                "stderr": (result.get("stderr") or "")[:300],
                "source": source,
                "is_share_link": is_share_link(url),
                "hint": _fetch_failure_hint(source, result.get("error_kind")),
            },
        )

    # ===== التحقق الحقيقي من الصور =====
    valid, rejected = _filter_valid_images(result["files"])

    if not valid:
        # لم تنجُ أي صورة من الفحص
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "تم تنزيل ملفات لكن لا توجد صورة قابلة للمعاينة",
                "rejected": rejected[:10],
                "source": source,
                "is_share_link": is_share_link(url),
                "hint": (
                    "غالباً الرابط يعيد صفحة HTML (تسجيل دخول/محتوى غير متاح) "
                    "وليست صورة. جرّب رابط صورة مباشر أو مرّر كوكيز."
                ),
            },
        )

    # ابنِ قائمة الصور الصالحة
    images = []
    for item in valid:
        f = Path(item["path"])
        try:
            rel_path = f.relative_to(MEDIA_ROOT)
        except ValueError:
            rel_path = Path(f.name)
        public_url = f"/media/{rel_path.as_posix()}"

        images.append({
            "url": public_url,
            "filename": f.name,
            "size": item["size"],
            "path": str(f),
            "info": item["info"],
        })

    print(
        f"✅ [image/fetch] valid={len(images)}, rejected={len(rejected)}",
        flush=True,
    )
    if rejected:
        for r in rejected[:5]:
            print(f"   ⛔ {r['filename']}: {r['error']}", flush=True)

    return {
        "success": True,
        "images": images,
        "count": len(images),
        "rejected_count": len(rejected),
        "rejected": rejected[:10],
        "source": source,
        "source_label": source_label(source),
        "is_share_link": is_share_link(url),
        "job_id": job_id,
        "duration_ms": result.get("duration_ms", 0),
    }


def _fetch_failure_hint(source: str, error_kind: Optional[str]) -> str:
    """يرجع تلميحاً مفيداً حسب نوع الفشل."""
    if error_kind == "cli_missing":
        return "ثبّت gallery-dl: pip install gallery-dl"
    if error_kind == "timeout":
        return "انتهت المهلة. جرّب لاحقاً أو رابطاً أبسط."
    if error_kind == "no_images":
        return "gallery-dl لم يجد صوراً. تأكد أن الرابط يحتوي صوراً."
    if source == "facebook":
        return "فيسبوك غالباً يحتاج كوكيز. جرّب cookies_from_browser=chrome."
    if source == "instagram":
        return "إنستغرام يتطلب تسجيل دخول غالباً. مرّر كوكيز."
    return "تحقق من صحة الرابط أو جرّب مصدراً آخر."


@router.post("/api/image/save", tags=["image"])
async def save_images(payload: SaveImagesRequest):
    """
    ينقل الصور المحددة من مجلد المعاينة (job_id) إلى مكتبة التحميلات الدائمة.
    """
    images = payload.images or []
    if not images:
        raise HTTPException(status_code=400, detail="لا توجد صور للحفظ.")

    # تحقق أن job_id صالح
    job_id = (payload.job_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{6,32}", job_id):
        raise HTTPException(status_code=400, detail="job_id غير صالح.")

    job_dir = PREVIEW_DIR / f"job_{job_id}"
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="مجلد المعاينة غير موجود أو منتهي.")

    saved = []
    failed = []

    for img in images:
        filename = img.get("filename")
        if not filename:
            failed.append({"filename": None, "error": "missing filename"})
            continue

        # ابحث فقط داخل مجلد هذه المهمة (آمن)
        candidate = job_dir / filename
        if not candidate.is_file():
            # ابحث في المجلدات الفرعية داخل نفس المهمة
            matches = list(job_dir.rglob(filename))
            if not matches:
                failed.append({"filename": filename, "error": "not found in job"})
                continue
            candidate = matches[0]

        # تحقق مرة أخرى أن الملف صورة قابلة للمعاينة
        ok, reason, info = is_valid_previewable_image(candidate)
        if not ok:
            failed.append({"filename": filename, "error": f"invalid image: {reason}"})
            continue

        # اسم ملف آمن وفريد
        safe_name = _safe_filename(candidate.name, fallback="image")
        # أضف بادئة فريدة لتفادي التصادم
        unique_prefix = uuid.uuid4().hex[:8]
        stem = Path(safe_name).stem[:80] or "image"
        ext = Path(safe_name).suffix.lower() or ".jpg"
        dst = DOWNLOAD_DIR / f"{stem}_{unique_prefix}{ext}"

        try:
            shutil.copy2(candidate, dst)
            saved.append({
                "filename": dst.name,
                "url": f"/media/downloads/{dst.name}",
                "size": dst.stat().st_size,
                "info": info or {},
            })
            print(f"💾 [image/save] Saved: {dst}", flush=True)
        except Exception as e:
            failed.append({"filename": filename, "error": str(e)})

    return {
        "success": True,
        "saved": len(saved),
        "failed_count": len(failed),
        "failed": failed,
        "images": saved,
        "job_id": job_id,
    }


@router.post("/api/image/cleanup", tags=["image"])
async def cleanup_preview(max_age_minutes: int = 60):
    """
    يحذف مجلدات المعاينة الأقدم من max_age_minutes.
    الافتراضي: 60 دقيقة. لتجنب حذف مجلد قيد الاستخدام.
    """
    if max_age_minutes < 1:
        raise HTTPException(status_code=400, detail="max_age_minutes يجب أن يكون >= 1.")

    now = time.time()
    threshold = max_age_minutes * 60
    deleted = 0
    kept = 0
    errors = []

    try:
        for job_dir in PREVIEW_DIR.glob("job_*"):
            if not job_dir.is_dir():
                continue
            try:
                age = now - job_dir.stat().st_mtime
            except OSError:
                continue
            if age >= threshold:
                try:
                    shutil.rmtree(job_dir, ignore_errors=False)
                    deleted += 1
                except Exception as e:
                    errors.append({"dir": job_dir.name, "error": str(e)})
            else:
                kept += 1
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل التنظيف: {e}")

    return {
        "success": True,
        "deleted_dirs": deleted,
        "kept_dirs": kept,
        "max_age_minutes": max_age_minutes,
        "errors": errors,
    }
