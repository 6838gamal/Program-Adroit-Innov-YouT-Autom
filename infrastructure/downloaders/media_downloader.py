"""
مكتبة تحميل موحّدة للصور والفيديوهات.

المحركات:
  - facebook   → مستخرج مخصص (curl_cffi + httpx fallback)
  - gallery-dl → إنستغرام/تويتر/بينتريست...
  - yt-dlp     → فيديوهات
  - direct     → رابط مباشر (fallback)

النسخة المحدّثة:
- دعم curl_cffi لمحاكاة بصمة متصفح حقيقي (يتجاوز حظر فيسبوك)
- سقوط آمن إلى httpx مع ترويسات محسّنة
- كشف دقيق لحالات فيسبوك (400، 403، 404، login wall)
- تحقق حقيقي من الصور (magic bytes + Pillow + content-type + أبعاد)
- رسائل خطأ عربية دقيقة لكل حالة
- دعم كوكيز من ملف JSON
- رفض SVG نهائياً
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Pillow
# ─────────────────────────────────────────────────────────
try:
    from PIL import Image, UnidentifiedImageError
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    UnidentifiedImageError = Exception
    print("⚠️ Pillow غير متوفر — التحقق سيكون محدوداً. ثبّته: pip install Pillow")


# ─────────────────────────────────────────────────────────
# curl_cffi (اختياري لكن مُوصى به بشدة لفيسبوك)
# ─────────────────────────────────────────────────────────
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
    print("✅ curl_cffi متوفر — محاكاة بصمة المتصفح مُفعّلة")
except ImportError:
    CURL_CFFI_AVAILABLE = False
    CurlAsyncSession = None
    print("⚠️ curl_cffi غير متوفر — يُنصح بتثبيته لدعم أفضل لفيسبوك")
    print("   pip install curl_cffi")


# ─────────────────────────────────────────────────────────
# ثوابت
# ─────────────────────────────────────────────────────────
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

MIN_IMAGE_BYTES = 2_000
MAX_IMAGE_BYTES = 30_000_000
MIN_IMAGE_DIMENSION = 50

SHARE_LINK_PATTERNS = (
    "/share/p/",
    "/share/r/",
    "/share/v/",
    "/share/",
    "fb.watch/",
    "pin.it/",
)

FACEBOOK_HOSTS = (
    "facebook.com", "fb.com", "fb.watch",
    "m.facebook.com", "web.facebook.com",
)

# رموز خروج gallery-dl
GDL_EXIT_OK = 0
GDL_EXIT_UNSUPPORTED = 64
GDL_EXIT_AUTH = 77

# ترويسات فيسبوك المحسّنة (محاكاة Chrome حقيقي)
FB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


# ─────────────────────────────────────────────────────────
# نماذج البيانات
# ─────────────────────────────────────────────────────────

@dataclass
class DownloadResult:
    engine: str
    success: bool
    files: List[Path] = field(default_factory=list)
    error: Optional[str] = None
    error_ar: Optional[str] = None
    error_kind: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    used_client: Optional[str] = None  # "curl_cffi" | "httpx"

    @property
    def count(self) -> int:
        return len(self.files)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "engine": self.engine,
            "success": self.success,
            "count": self.count,
            "files": [str(f) for f in self.files],
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.error_ar:
            d["error_ar"] = self.error_ar
        if self.error_kind:
            d["error_kind"] = self.error_kind
        if self.used_client:
            d["used_client"] = self.used_client
        if self.rejected:
            d["rejected"] = self.rejected[:10]
        return d


@dataclass
class DownloadBundle:
    url: str
    results: List[DownloadResult] = field(default_factory=list)
    chosen: Optional[DownloadResult] = None

    @property
    def all_files(self) -> List[Path]:
        files: List[Path] = []
        for r in self.results:
            if r.success:
                files.extend(r.files)
        return files

    @property
    def success(self) -> bool:
        return self.chosen is not None and len(self.all_files) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "attempts": [r.to_dict() for r in self.results],
            "chosen_engine": self.chosen.engine if self.chosen else None,
            "total_files": len(self.all_files),
            "success": self.success,
        }

    def user_message_ar(self) -> Dict[str, Any]:
        if self.success:
            return {
                "success": True,
                "message": (
                    f"تم التحميل بنجاح عبر {self.chosen.engine} "
                    f"({len(self.all_files)} ملف)."
                ),
                "engine": self.chosen.engine,
                "files_count": len(self.all_files),
            }

        share = is_share_link(self.url)
        source = detect_source(self.url)

        reasons = []
        for r in self.results:
            if r.success or r.error_kind == "skipped":
                continue
            reasons.append({
                "engine": r.engine,
                "reason": r.error_ar or r.error or "فشل غير معروف",
                "kind": r.error_kind,
                "used_client": r.used_client,
            })

        return {
            "success": False,
            "message": "تعذّر تحميل الصورة من الرابط.",
            "is_share_link": share,
            "source": source,
            "source_label": source_label(source),
            "reasons": reasons,
            "hint": _build_hint_ar(source, share, self.results),
        }


# ─────────────────────────────────────────────────────────
# كشف المحركات
# ─────────────────────────────────────────────────────────

def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def detect_engines() -> Dict[str, bool]:
    engines = {
        "gallery-dl": _which("gallery-dl") is not None,
        "yt-dlp": _which("yt-dlp") is not None,
        "requests": True,
        "pillow": PIL_AVAILABLE,
        "curl_cffi": CURL_CFFI_AVAILABLE,
        "facebook": True,
    }
    logger.info("🔍 Detected download engines: %s", engines)
    print(f"🔍 Detected download engines: {engines}")
    return engines


# ─────────────────────────────────────────────────────────
# كشف المصدر
# ─────────────────────────────────────────────────────────

def detect_source(url: str) -> str:
    u = url.lower()
    if any(d in u for d in FACEBOOK_HOSTS):
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
    return {
        "facebook": "فيسبوك",
        "instagram": "إنستغرام",
        "twitter": "تويتر / X",
        "pinterest": "بينتريست",
        "tiktok": "تيك توك",
        "reddit": "Reddit",
        "youtube": "يوتيوب",
        "generic": "رابط عام",
    }.get(src, src)


def is_share_link(url: str) -> bool:
    u = url.lower()
    return any(p in u for p in SHARE_LINK_PATTERNS)


# ─────────────────────────────────────────────────────────
# التحقق من الصور
# ─────────────────────────────────────────────────────────

def _sniff_image_format(data: bytes) -> Optional[str]:
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


def is_valid_image_bytes(
    data: bytes,
    content_type: str = "",
) -> Tuple[bool, str, Optional[dict]]:
    if not data:
        return False, "empty response", None

    size = len(data)
    if size < MIN_IMAGE_BYTES:
        return False, f"too small ({size} bytes)", None
    if size > MAX_IMAGE_BYTES:
        return False, f"too large ({size} bytes)", None

    ct = (content_type or "").lower()
    if ct and any(x in ct for x in ("html", "text/", "xml", "json")):
        return False, f"content-type is not an image: {ct}", None

    sniffed = _sniff_image_format(data[:32])
    if not sniffed:
        return False, "not a recognized image format (magic bytes)", None

    if sniffed == "SVG":
        return False, "svg not allowed", None

    if PIL_AVAILABLE:
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
                fmt = (im.format or sniffed).upper()
        except UnidentifiedImageError:
            return False, "Pillow: unidentified image", None
        except Exception as e:
            return False, f"Pillow verify failed: {e}", None

        if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
            return False, f"dimensions too small ({w}x{h})", None

        return True, "ok", {"format": fmt, "width": w, "height": h, "size": size}

    return True, "ok (no Pillow)", {"format": sniffed, "size": size}


def is_valid_image_file(path: Path) -> Tuple[bool, str, Optional[dict]]:
    if not path.is_file():
        return False, "not a file", None
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return False, "svg not allowed", None
    if suffix not in IMAGE_EXTENSIONS:
        try:
            head = path.read_bytes()[:32]
        except OSError as e:
            return False, f"unreadable: {e}", None
        if not _sniff_image_format(head):
            return False, f"extension not allowed and not a known image: {suffix}", None
    try:
        data = path.read_bytes()
    except OSError as e:
        return False, f"unreadable: {e}", None
    return is_valid_image_bytes(data)


def _filter_valid_files(
    files: List[Path],
    expect: str = "image",
) -> Tuple[List[Path], List[Dict[str, Any]]]:
    valid: List[Path] = []
    rejected: List[Dict[str, Any]] = []

    for f in files:
        if not f.is_file():
            continue
        suffix = f.suffix.lower()

        if expect in ("video", "any") and suffix in VIDEO_EXTENSIONS:
            valid.append(f)
            continue

        if expect in ("image", "any"):
            ok, reason, info = is_valid_image_file(f)
            if ok:
                valid.append(f)
                continue
            if expect == "any" and suffix in VIDEO_EXTENSIONS:
                valid.append(f)
                continue
            rejected.append({
                "file": f.name,
                "error": reason,
                "size": f.stat().st_size if f.exists() else 0,
            })
            continue

        rejected.append({
            "file": f.name,
            "error": f"unexpected type: {suffix}",
            "size": f.stat().st_size if f.exists() else 0,
        })

    return valid, rejected


# ─────────────────────────────────────────────────────────
# مستخرج فيسبوك
# ─────────────────────────────────────────────────────────

def _extract_fb_image_urls(html: str) -> List[str]:
    urls: List[str] = []
    seen = set()

    def add(u: str):
        if not u:
            return
        u = u.replace("\\/", "/").replace("\\u0025", "%").replace("\\u0026", "&")
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            return
        if any(x in u for x in ("emoji.php", "rsrc.php", "/images/", "static.xx")):
            return
        # تجاهل الصور الصغيرة جداً (تُحدد لاحقاً بالتحقق)
        if u in seen:
            return
        seen.add(u)
        urls.append(u)

    for m in re.finditer(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    ):
        add(m.group(1))

    for m in re.finditer(
        r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    ):
        add(m.group(1))

    for m in re.finditer(
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    ):
        add(m.group(1))

    for m in re.finditer(
        r'"(?:image|image_url|uri|url|src)"\s*:\s*"(https?:[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        html, re.IGNORECASE,
    ):
        add(m.group(1))

    for m in re.finditer(
        r'(https?://[^"\'\s<>]+scontent[^"\'\s<>]+\.(?:jpg|jpeg|png|webp)[^"\'\s<>]*)',
        html, re.IGNORECASE,
    ):
        add(m.group(1))

    return urls


def _detect_fb_page_kind(html: str, status: int) -> Optional[Tuple[str, str]]:
    """
    يكتشف نوع صفحة فيسبوك.
    يرجع (error_kind, error_ar) أو None إذا كانت الصفحة تبدو عادية.
    """
    if status == 400:
        return (
            "http_400",
            "فيسبوك رفض الطلب (400). يحتاج النظام إلى كوكيز أو محاكاة متصفح حقيقي.",
        )
    if status == 403:
        return (
            "http_403",
            "فيسبوك منع الوصول (403). المحتوى محمي أو الرابط محظور.",
        )
    if status == 404:
        return "http_404", "الصفحة غير موجودة (404)."
    if status >= 500:
        return "http_5xx", f"خطأ في سيرفر فيسبوك (HTTP {status})."

    low = html.lower()
    if "login" in low and ("password" in low or "email" in low):
        return (
            "login_wall",
            "فيسبوك يعرض صفحة تسجيل دخول. المحتوى خاص أو يتطلب حساباً.",
        )
    if "content isn't available" in low or "content not available" in low:
        return (
            "content_unavailable",
            "المحتوى غير متاح. قد يكون محذوفاً أو خاصاً.",
        )
    if "group" in low and ("private" in low or "members" in low):
        return (
            "private_group",
            "المنشور في مجموعة خاصة. يتطلب عضوية أو كوكيز.",
        )
    return None


async def _fetch_html_curl_cffi(
    url: str,
    cookies: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> Tuple[str, str, int]:
    """
    يجلب HTML عبر curl_cffi مع محاكاة Chrome.
    يرجع (html, final_url, status).
    """
    session = CurlAsyncSession(impersonate="chrome124", timeout=timeout)
    try:
        if cookies:
            for k, v in cookies.items():
                session.cookies.set(k, v, domain=".facebook.com")
        resp = await session.get(url)
        return resp.text, str(resp.url), resp.status_code
    finally:
        await session.close()


async def _fetch_html_httpx(
    url: str,
    cookies: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> Tuple[str, str, int]:
    """يجلب HTML عبر httpx مع ترويسات محسّنة."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers=FB_HEADERS,
    ) as client:
        if cookies:
            for k, v in cookies.items():
                client.cookies.set(k, v, domain=".facebook.com")
        resp = await client.get(url)
        return resp.text, str(resp.url), resp.status_code


async def _run_facebook(
    url: str,
    out_dir: Path,
    cookies_file: Optional[Path] = None,
    timeout: int = 30,
) -> DownloadResult:
    """
    مستخرج فيسبوك:
    1. يجلب HTML عبر curl_cffi (أو httpx كبديل).
    2. يكتشف نوع الصفحة (تسجيل دخول، محتوى غير متاح، مجموعة خاصة).
    3. يستخرج og:image وروابط scontent.
    4. يحمّل كل مرشح ويتحقق منه.
    """
    import time
    start = time.perf_counter()

    print(f"🎬 [facebook] Extracting from {url}")

    # اقرأ كوكيز
    cookies = None
    if cookies_file and cookies_file.is_file():
        try:
            cookies = json.loads(cookies_file.read_text(encoding="utf-8"))
            print(f"🎬 [facebook] cookies loaded: {len(cookies)} entries")
        except Exception as e:
            print(f"🎬 [facebook] failed to read cookies: {e}")

    used_client = "curl_cffi" if CURL_CFFI_AVAILABLE else "httpx"

    try:
        # 1) اجلب HTML
        if CURL_CFFI_AVAILABLE:
            print("🎬 [facebook] using curl_cffi (impersonate=chrome124)")
            html, final_url, status = await _fetch_html_curl_cffi(url, cookies, timeout)
        else:
            print("🎬 [facebook] using httpx (fallback — أقل فعالية)")
            html, final_url, status = await _fetch_html_httpx(url, cookies, timeout)

        duration = (time.perf_counter() - start) * 1000

        print(
            f"🎬 [facebook] final_url={final_url[:100]}, "
            f"status={status}, size={len(html)}, client={used_client}"
        )

        # 2) اكتشف نوع الصفحة
        kind = _detect_fb_page_kind(html, status)
        if kind:
            error_kind, error_ar = kind
            return DownloadResult(
                engine="facebook",
                success=False,
                error=f"facebook page: {error_kind}",
                error_ar=error_ar,
                error_kind=error_kind,
                duration_ms=duration,
                used_client=used_client,
            )

        # 3) استخرج روابط الصور
        candidate_urls = _extract_fb_image_urls(html)
        print(f"🎬 [facebook] found {len(candidate_urls)} candidate image urls")

        if not candidate_urls:
            return DownloadResult(
                engine="facebook",
                success=False,
                error="no image urls found in page",
                error_ar=(
                    "لم يتم العثور على صور في الصفحة. "
                    "قد يكون المنشور نصياً أو يحتوي فيديو فقط."
                ),
                error_kind="no_images",
                duration_ms=(time.perf_counter() - start) * 1000,
                used_client=used_client,
            )

        # 4) حمّل كل مرشح وتحقّق منه
        downloaded: List[Path] = []
        rejected: List[Dict[str, Any]] = []

        # استخدم نفس العميل لتحميل الصور
        if CURL_CFFI_AVAILABLE:
            session = CurlAsyncSession(impersonate="chrome124", timeout=timeout)
            try:
                if cookies:
                    for k, v in cookies.items():
                        session.cookies.set(k, v, domain=".facebook.com")
                for i, img_url in enumerate(candidate_urls[:8]):
                    try:
                        r = await session.get(img_url)
                        if r.status_code != 200:
                            rejected.append({
                                "url": img_url[:120],
                                "error": f"HTTP {r.status_code}",
                            })
                            continue
                        ct = r.headers.get("content-type", "")
                        data = r.content
                        ok, reason, info = is_valid_image_bytes(data, ct)
                        if not ok:
                            rejected.append({
                                "url": img_url[:120],
                                "error": reason,
                                "content_type": ct,
                                "size": len(data),
                            })
                            continue
                        fmt = (info or {}).get("format", "JPEG")
                        ext = {
                            "JPEG": ".jpg", "PNG": ".png", "GIF": ".gif",
                            "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff",
                        }.get(fmt, ".jpg")
                        dest = out_dir / f"facebook_{i:02d}_{uuid.uuid4().hex[:6]}{ext}"
                        dest.write_bytes(data)
                        downloaded.append(dest)
                        print(
                            f"🎬 [facebook] ✅ saved {dest.name} "
                            f"({len(data)} bytes, {fmt})"
                        )
                    except Exception as e:
                        rejected.append({"url": img_url[:120], "error": str(e)})
            finally:
                await session.close()
        else:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout, headers=FB_HEADERS,
            ) as client:
                if cookies:
                    for k, v in cookies.items():
                        client.cookies.set(k, v, domain=".facebook.com")
                for i, img_url in enumerate(candidate_urls[:8]):
                    try:
                        r = await client.get(img_url)
                        if r.status_code != 200:
                            rejected.append({
                                "url": img_url[:120],
                                "error": f"HTTP {r.status_code}",
                            })
                            continue
                        ct = r.headers.get("content-type", "")
                        data = r.content
                        ok, reason, info = is_valid_image_bytes(data, ct)
                        if not ok:
                            rejected.append({
                                "url": img_url[:120],
                                "error": reason,
                                "content_type": ct,
                                "size": len(data),
                            })
                            continue
                        fmt = (info or {}).get("format", "JPEG")
                        ext = {
                            "JPEG": ".jpg", "PNG": ".png", "GIF": ".gif",
                            "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff",
                        }.get(fmt, ".jpg")
                        dest = out_dir / f"facebook_{i:02d}_{uuid.uuid4().hex[:6]}{ext}"
                        dest.write_bytes(data)
                        downloaded.append(dest)
                        print(
                            f"🎬 [facebook] ✅ saved {dest.name} "
                            f"({len(data)} bytes, {fmt})"
                        )
                    except Exception as e:
                        rejected.append({"url": img_url[:120], "error": str(e)})

        duration = (time.perf_counter() - start) * 1000

        if not downloaded:
            return DownloadResult(
                engine="facebook",
                success=False,
                error="no valid images after validation",
                error_ar=(
                    "تم العثور على روابط لكن لا توجد صورة صالحة. "
                    "قد تكون الصور محمية أو انتهت صلاحيتها."
                ),
                error_kind="no_valid_images",
                duration_ms=duration,
                rejected=rejected,
                used_client=used_client,
            )

        return DownloadResult(
            engine="facebook",
            success=True,
            files=downloaded,
            duration_ms=duration,
            rejected=rejected,
            used_client=used_client,
        )

    except httpx.HTTPStatusError as e:
        return DownloadResult(
            engine="facebook",
            success=False,
            error=f"HTTP {e.response.status_code}",
            error_ar=f"فيسبوك أرجع خطأ HTTP {e.response.status_code}.",
            error_kind="http_error",
            duration_ms=(time.perf_counter() - start) * 1000,
            used_client=used_client,
        )
    except httpx.TimeoutException:
        return DownloadResult(
            engine="facebook",
            success=False,
            error="timeout",
            error_ar="انتهت المهلة أثناء الاتصال بفيسبوك.",
            error_kind="timeout",
            duration_ms=(time.perf_counter() - start) * 1000,
            used_client=used_client,
        )
    except Exception as e:
        return DownloadResult(
            engine="facebook",
            success=False,
            error=str(e),
            error_ar=f"فشل المستخرج: {e}",
            error_kind="exception",
            duration_ms=(time.perf_counter() - start) * 1000,
            used_client=used_client,
        )


# ─────────────────────────────────────────────────────────
# gallery-dl
# ─────────────────────────────────────────────────────────

def _classify_gallery_dl_error(returncode: int, stderr: str) -> Tuple[str, str]:
    s = (stderr or "").lower()
    if returncode == GDL_EXIT_UNSUPPORTED or "unsupported url" in s:
        return "unsupported_url", "الرابط غير مدعوم من gallery-dl."
    if returncode == GDL_EXIT_AUTH or "login" in s or "cookies" in s or "authentication" in s:
        return "auth_required", "الرابط يتطلب تسجيل دخول أو كوكيز."
    if "not found" in s or "404" in s:
        return "not_found", "الصفحة غير موجودة."
    if "private" in s:
        return "private", "المحتوى خاص."
    if returncode != 0:
        return "gallery_dl_failed", f"فشل gallery-dl (exit={returncode})."
    return "unknown", "فشل غير معروف."


async def _run_gallery_dl(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[Path] = None,
    timeout: int = 120,
) -> DownloadResult:
    import time
    start = time.perf_counter()

    if not _which("gallery-dl"):
        return DownloadResult(
            engine="gallery-dl",
            success=False,
            error="gallery-dl not installed",
            error_ar="gallery-dl غير مثبّت على السيرفر.",
            error_kind="cli_missing",
        )

    cmd = ["gallery-dl", "--dest", str(out_dir), "--no-part", "-q"]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    elif cookies_file and cookies_file.is_file():
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(url)

    print(f"🎬 [gallery-dl] Running: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout = stdout_b.decode(errors="ignore")
        stderr = stderr_b.decode(errors="ignore")

        all_files = [p for p in out_dir.rglob("*") if p.is_file()]
        duration = (time.perf_counter() - start) * 1000
        valid, rejected = _filter_valid_files(all_files, expect="image")

        success = proc.returncode == 0 and len(valid) > 0
        error_kind = None
        error_ar = None
        error_msg = None
        if not success:
            if proc.returncode != 0:
                error_kind, error_ar = _classify_gallery_dl_error(proc.returncode, stderr)
                error_msg = f"exit={proc.returncode}"
            else:
                error_kind = "no_valid_images"
                error_ar = "لم يتم العثور على صور صالحة."
                error_msg = "no valid images after validation"

        result = DownloadResult(
            engine="gallery-dl",
            success=success,
            files=valid,
            error=error_msg,
            error_ar=error_ar,
            error_kind=error_kind,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration,
            rejected=rejected,
        )

        print(
            f"🎬 [gallery-dl] rc={proc.returncode}, "
            f"files={len(all_files)} (valid={len(valid)}, rejected={len(rejected)}), "
            f"{duration:.0f}ms"
        )
        if stderr:
            print(f"🎬 [gallery-dl] stderr: {stderr[:500]}")

        return result

    except asyncio.TimeoutError:
        return DownloadResult(
            engine="gallery-dl",
            success=False,
            error=f"timeout after {timeout}s",
            error_ar="انتهت المهلة أثناء التحميل.",
            error_kind="timeout",
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return DownloadResult(
            engine="gallery-dl",
            success=False,
            error=str(e),
            error_ar=f"فشل gallery-dl: {e}",
            error_kind="exception",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────
# yt-dlp
# ─────────────────────────────────────────────────────────

async def _run_yt_dlp(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[Path] = None,
    timeout: int = 300,
) -> DownloadResult:
    import time
    start = time.perf_counter()

    if not _which("yt-dlp"):
        return DownloadResult(
            engine="yt-dlp",
            success=False,
            error="yt-dlp not installed",
            error_ar="yt-dlp غير مثبّت على السيرفر.",
            error_kind="cli_missing",
        )

    cmd = [
        "yt-dlp", "--no-playlist",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "-o", str(out_dir / "%(id)s.%(ext)s"),
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    elif cookies_file and cookies_file.is_file():
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(url)

    print(f"🎬 [yt-dlp] Running: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout = stdout_b.decode(errors="ignore")
        stderr = stderr_b.decode(errors="ignore")

        all_files = [p for p in out_dir.rglob("*") if p.is_file()]
        duration = (time.perf_counter() - start) * 1000
        valid, rejected = _filter_valid_files(all_files, expect="any")

        success = proc.returncode == 0 and len(valid) > 0
        error_kind = None
        error_ar = None
        error_msg = None
        if not success:
            if proc.returncode != 0:
                error_kind = "yt_dlp_failed"
                error_ar = f"فشل yt-dlp (exit={proc.returncode})."
                error_msg = f"exit={proc.returncode}"
            else:
                error_kind = "no_valid_media"
                error_ar = "لم يتم العثور على وسائط صالحة."
                error_msg = "no valid media after validation"

        result = DownloadResult(
            engine="yt-dlp",
            success=success,
            files=valid,
            error=error_msg,
            error_ar=error_ar,
            error_kind=error_kind,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration,
            rejected=rejected,
        )

        print(
            f"🎬 [yt-dlp] rc={proc.returncode}, "
            f"files={len(all_files)} (valid={len(valid)}, rejected={len(rejected)}), "
            f"{duration:.0f}ms"
        )
        return result

    except asyncio.TimeoutError:
        return DownloadResult(
            engine="yt-dlp",
            success=False,
            error=f"timeout after {timeout}s",
            error_ar="انتهت المهلة أثناء التحميل.",
            error_kind="timeout",
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return DownloadResult(
            engine="yt-dlp",
            success=False,
            error=str(e),
            error_ar=f"فشل yt-dlp: {e}",
            error_kind="exception",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────
# direct
# ─────────────────────────────────────────────────────────

async def _run_direct(
    url: str,
    out_dir: Path,
    timeout: int = 60,
) -> DownloadResult:
    import time
    start = time.perf_counter()

    print(f"🎬 [direct] GET {url}")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            ct = resp.headers.get("content-type", "")
            data = resp.content
            duration = (time.perf_counter() - start) * 1000

            if "html" in ct.lower() or "text/" in ct.lower():
                return DownloadResult(
                    engine="direct",
                    success=False,
                    error=f"content-type is not media: {ct}",
                    error_ar="الرابط يعيد صفحة HTML وليس صورة.",
                    error_kind="html_page",
                    duration_ms=duration,
                    rejected=[{
                        "error": "HTML page, not an image",
                        "content_type": ct,
                        "size": len(data),
                    }],
                )

            sniffed = _sniff_image_format(data[:32])
            is_video = False
            if not sniffed:
                if data[4:8] == b"ftyp" or data[:4] in (b"\x1a\x45\xdf\xa3",):
                    is_video = True

            if not sniffed and not is_video:
                return DownloadResult(
                    engine="direct",
                    success=False,
                    error="not a recognized image/video format",
                    error_ar="المحتوى ليس صورة أو فيديو معروفاً.",
                    error_kind="unknown_format",
                    duration_ms=duration,
                    rejected=[{
                        "error": "unknown format (magic bytes)",
                        "content_type": ct,
                        "size": len(data),
                    }],
                )

            if sniffed and not is_video:
                ok, reason, info = is_valid_image_bytes(data, ct)
                if not ok:
                    return DownloadResult(
                        engine="direct",
                        success=False,
                        error=f"invalid image: {reason}",
                        error_ar="المحتوى ليس صورة صالحة.",
                        error_kind="invalid_image",
                        duration_ms=duration,
                        rejected=[{
                            "error": reason,
                            "content_type": ct,
                            "size": len(data),
                        }],
                    )

            suffix = Path(urlparse(url).path).suffix.lower()
            if suffix not in IMAGE_EXTENSIONS and suffix not in VIDEO_EXTENSIONS:
                if sniffed:
                    suffix = {
                        "JPEG": ".jpg", "PNG": ".png", "GIF": ".gif",
                        "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff",
                    }.get(sniffed, ".jpg")
                elif is_video:
                    suffix = ".mp4"
                else:
                    suffix = ".jpg"

            dest = out_dir / f"direct_{uuid.uuid4().hex[:8]}{suffix}"
            dest.write_bytes(data)

            print(
                f"🎬 [direct] OK, {len(data)} bytes, "
                f"{duration:.0f}ms, format={sniffed or ('video' if is_video else '?')}"
            )
            return DownloadResult(
                engine="direct",
                success=True,
                files=[dest],
                duration_ms=duration,
            )

    except httpx.HTTPStatusError as e:
        return DownloadResult(
            engine="direct",
            success=False,
            error=f"HTTP {e.response.status_code}",
            error_ar=f"الرابط أرجع خطأ HTTP {e.response.status_code}.",
            error_kind="http_error",
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return DownloadResult(
            engine="direct",
            success=False,
            error=str(e),
            error_ar=f"فشل التحميل المباشر: {e}",
            error_kind="exception",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────
# تلميح عربي
# ─────────────────────────────────────────────────────────

def _build_hint_ar(
    source: str,
    share: bool,
    results: List[DownloadResult],
) -> str:
    kinds = {r.error_kind for r in results if r.error_kind}

    # أولوية خاصة لفيسبوك
    if source == "facebook":
        if "login_wall" in kinds or "auth_required" in kinds:
            return (
                "فيسبوك يطلب تسجيل دخول لهذا المحتوى. "
                "الحل: صدّر كوكيز فيسبوك من متصفحك إلى ملف JSON "
                "وأضفه إلى الإعدادات، أو استخدم رابط صورة مباشر."
            )
        if "private_group" in kinds:
            return (
                "المنشور في مجموعة خاصة. "
                "تحتاج عضوية المجموعة وكوكيز للوصول. "
                "أو احفظ الصورة يدوياً وارفعها مباشرة."
            )
        if "http_400" in kinds:
            return (
                "فيسبوك رفض الطلب. "
                "هذا يحدث غالباً مع روابط المشاركة. "
                "افتح المنشور في المتصفح، انقر بزر الفأرة الأيمن على الصورة، "
                "اختر «نسخ عنوان الصورة»، ثم الصق الرابط المباشر هنا."
            )
        if "content_unavailable" in kinds:
            return "المحتوى غير متاح. قد يكون محذوفاً أو خاصاً."
        if share:
            return (
                "هذا رابط مشاركة وليس رابط صورة مباشر. "
                "افتح المنشور في المتصفح، انقر بزر الفأرة الأيمن على الصورة، "
                "ثم اختر «نسخ عنوان الصورة» والصق الرابط المباشر هنا. "
                "أو فعّل كوكيز فيسبوك ليعمل المستخرج التلقائي."
            )
        return (
            "جرّب نسخ رابط الصورة المباشر من المتصفح، "
            "أو أضف كوكيز فيسبوك إلى الإعدادات."
        )

    if "auth_required" in kinds:
        return "المحتوى يتطلب تسجيل دخول. أضف كوكيز أو استخدم رابطاً عاماً."
    if "unsupported_url" in kinds:
        return "الرابط غير مدعوم. تأكد أنه رابط منشور مباشر."
    if "no_valid_images" in kinds or "no_images" in kinds:
        return "لم يتم العثور على صور. قد يكون المنشور نصياً أو فيديو فقط."
    if source == "instagram":
        return "إنستغرام يتطلب تسجيل دخول غالباً. مرّر كوكيز."
    if source == "youtube":
        return "تأكد أن الرابط لفيديو وليس قناة أو قائمة تشغيل."
    return "تحقق من صحة الرابط، أو جرّب رابطاً مباشراً للصورة."


# ─────────────────────────────────────────────────────────
# الواجهة الموحّدة
# ─────────────────────────────────────────────────────────

class MediaDownloader:
    def __init__(
        self,
        cookies_from_browser: Optional[str] = None,
        cookies_file: Optional[Path] = None,
        prefer: Optional[List[str]] = None,
        allow_direct_for_share_links: bool = False,
    ):
        self.cookies_from_browser = cookies_from_browser
        self.cookies_file = Path(cookies_file) if cookies_file else None
        self.prefer = prefer or ["facebook", "gallery-dl", "yt-dlp", "direct"]
        self.allow_direct_for_share_links = allow_direct_for_share_links

    async def download(
        self,
        url: str,
        out_dir: Optional[Path] = None,
        engines: Optional[List[str]] = None,
    ) -> DownloadBundle:
        out_dir = out_dir or Path(tempfile.mkdtemp(prefix="dl_"))
        out_dir.mkdir(parents=True, exist_ok=True)

        source = detect_source(url)
        share = is_share_link(url)
        engines_to_try = engines or self._order_engines(source, share)

        available = detect_engines()
        bundle = DownloadBundle(url=url)

        print(f"\n{'='*60}")
        print(f"📥 Downloading: {url}")
        print(f"   source: {source}, share_link: {share}")
        print(f"📁 Output dir: {out_dir}")
        print(f"🧩 Engines to try: {engines_to_try}")
        print(f"{'='*60}")

        for engine in engines_to_try:
            if engine == "direct" and share and not self.allow_direct_for_share_links:
                print(f"⏭️  Skipping direct (share link, likely HTML)")
                bundle.results.append(DownloadResult(
                    engine="direct",
                    success=False,
                    error="skipped: share link likely returns HTML",
                    error_ar="تم تخطي التحميل المباشر لأن الرابط صفحة وليس صورة.",
                    error_kind="skipped",
                ))
                continue

            if engine not in ("direct", "facebook") and not available.get(engine, False):
                print(f"⏭️  Skipping {engine} (not installed)")
                bundle.results.append(DownloadResult(
                    engine=engine,
                    success=False,
                    error="not installed",
                    error_ar=f"{engine} غير مثبّت.",
                    error_kind="cli_missing",
                ))
                continue

            if engine == "facebook":
                res = await _run_facebook(url, out_dir, self.cookies_file)
            elif engine == "gallery-dl":
                res = await _run_gallery_dl(
                    url, out_dir,
                    self.cookies_from_browser, self.cookies_file,
                )
            elif engine == "yt-dlp":
                res = await _run_yt_dlp(
                    url, out_dir,
                    self.cookies_from_browser, self.cookies_file,
                )
            elif engine == "direct":
                res = await _run_direct(url, out_dir)
            else:
                continue

            bundle.results.append(res)

            if res.success and res.count > 0:
                bundle.chosen = res
                print(f"✅ Success with {engine} ({res.count} files)")
                break
            else:
                print(f"❌ {engine} failed: {res.error_ar or res.error}")

        print(f"{'='*60}")
        print(f"📊 Summary: {bundle.to_dict()}")
        print(f"{'='*60}\n")

        return bundle

    def _order_engines(self, source: str, share: bool) -> List[str]:
        if source == "facebook":
            order = ["facebook", "gallery-dl"]
            if not share:
                order.append("yt-dlp")
            order.append("direct")
            return order
        if source in ("instagram", "twitter", "pinterest"):
            return ["gallery-dl", "yt-dlp", "direct"]
        if source in ("youtube", "tiktok"):
            return ["yt-dlp", "gallery-dl", "direct"]
        return ["gallery-dl", "yt-dlp", "direct"]


# ─────────────────────────────────────────────────────────
# مساعد
# ─────────────────────────────────────────────────────────

async def download_image(
    url: str,
    out_dir: Optional[Path] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[Path] = None,
) -> Optional[Path]:
    dl = MediaDownloader(
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
    )
    bundle = await dl.download(url, out_dir=out_dir)
    files = bundle.all_files
    return files[0] if files else None


# ─────────────────────────────────────────────────────────
# نقطة دخول للاختبار
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    async def _main():
        if len(sys.argv) < 2:
            print("Usage: python media_downloader.py <url> [cookies_file]")
            sys.exit(1)

        url = sys.argv[1]
        cookies_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None

        dl = MediaDownloader(cookies_file=cookies_file)
        bundle = await dl.download(url)

        print("\n📣 رسالة المستخدم:")
        print(json.dumps(
            bundle.user_message_ar(),
            ensure_ascii=False, indent=2,
        ))

    asyncio.run(_main())
