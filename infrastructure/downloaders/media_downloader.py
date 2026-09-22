"""
مكتبة تحميل موحّدة للصور والفيديوهات.

تدعم عدة محركات (engines):
  - gallery-dl  → الصور من فيسبوك/إنستغرام/تويتر...
  - yt-dlp      → الفيديوهات
  - requests    → رابط مباشر (fallback)

تجرب كل محرك على حدة وتطبع النتائج على الكونسول.

نسخة محسّنة:
- تحقق حقيقي من الصور (magic bytes + Pillow + content-type + أبعاد)
- رفض صفحات HTML والملفات التالفة
- اكتشاف روابط المشاركة التي ترجع HTML
- رفض SVG نهائياً
- direct لا يعتبر النجاح إلا إذا كان المحتوى صورة فعلية
"""
from __future__ import annotations

import asyncio
import io
import logging
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Pillow (اختياري لكن مُوصى به بشدة)
# ─────────────────────────────────────────────────────────
try:
    from PIL import Image, UnidentifiedImageError
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    UnidentifiedImageError = Exception
    print("⚠️ Pillow غير متوفر — التحقق سيكون محدوداً. ثبّته: pip install Pillow")


# ─────────────────────────────────────────────────────────
# ثوابت التحقق
# ─────────────────────────────────────────────────────────
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

MIN_IMAGE_BYTES = 2_000          # 2 KB
MAX_IMAGE_BYTES = 30_000_000     # 30 MB
MIN_IMAGE_DIMENSION = 50         # بكسل

# روابط المشاركة التي غالباً ترجع HTML
SHARE_LINK_PATTERNS = (
    "/share/p/",
    "/share/r/",
    "/share/v/",
    "/share/",
    "fb.watch/",
    "pin.it/",
)


# ─────────────────────────────────────────────────────────
# نماذج البيانات
# ─────────────────────────────────────────────────────────

@dataclass
class DownloadResult:
    """نتيجة محاولة تحميل واحدة."""
    engine: str
    success: bool
    files: List[Path] = field(default_factory=list)
    error: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    rejected: List[Dict[str, Any]] = field(default_factory=list)

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
        if self.rejected:
            d["rejected"] = self.rejected[:10]
        return d


@dataclass
class DownloadBundle:
    """نتيجة كل المحاولات معاً."""
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "attempts": [r.to_dict() for r in self.results],
            "chosen_engine": self.chosen.engine if self.chosen else None,
            "total_files": len(self.all_files),
        }


# ─────────────────────────────────────────────────────────
# كشف المحركات المتاحة
# ─────────────────────────────────────────────────────────

def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def detect_engines() -> Dict[str, bool]:
    """يكشف المحركات المتاحة على النظام ويطبع النتائج."""
    engines = {
        "gallery-dl": _which("gallery-dl") is not None,
        "yt-dlp": _which("yt-dlp") is not None,
        "requests": True,  # دائماً متاح عبر httpx
        "pillow": PIL_AVAILABLE,
    }
    logger.info("🔍 Detected download engines: %s", engines)
    print(f"🔍 Detected download engines: {engines}")
    return engines


# ─────────────────────────────────────────────────────────
# التحقق من المحتوى
# ─────────────────────────────────────────────────────────

def _sniff_image_format(data: bytes) -> Optional[str]:
    """يكتشف صيغة الصورة من البايتات الأولى (magic bytes)."""
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


def is_share_link(url: str) -> bool:
    """يكتشف روابط المشاركة التي غالباً ترجع HTML."""
    u = url.lower()
    return any(p in u for p in SHARE_LINK_PATTERNS)


def is_valid_image_bytes(
    data: bytes,
    content_type: str = "",
) -> Tuple[bool, str, Optional[dict]]:
    """
    يتحقق أن البايتات تمثل صورة فعلية قابلة للمعاينة.
    يرجع (صالح؟, سبب, معلومات)
    """
    if not data:
        return False, "empty response", None

    size = len(data)
    if size < MIN_IMAGE_BYTES:
        return False, f"too small ({size} bytes)", None
    if size > MAX_IMAGE_BYTES:
        return False, f"too large ({size} bytes)", None

    # فحص content-type أولاً (سريع)
    ct = (content_type or "").lower()
    if ct:
        if "html" in ct or "text/" in ct or "xml" in ct or "json" in ct:
            return False, f"content-type is not an image: {ct}", None

    # فحص magic bytes
    sniffed = _sniff_image_format(data[:32])
    if not sniffed:
        return False, "not a recognized image format (magic bytes)", None

    # رفض SVG صراحة (احتياطي)
    if sniffed == "SVG":
        return False, "svg not allowed", None

    # فحص فعلي بـ Pillow إن توفر
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

    # بدون Pillow: نكتفي بـ magic bytes
    return True, "ok (no Pillow)", {"format": sniffed, "size": size}


def is_valid_image_file(path: Path) -> Tuple[bool, str, Optional[dict]]:
    """يتحقق أن الملف على القرص صورة فعلية."""
    if not path.is_file():
        return False, "not a file", None

    suffix = path.suffix.lower()

    # رفض SVG نهائياً
    if suffix == ".svg":
        return False, "svg not allowed", None

    # السماح فقط بامتدادات الصور المعروفة
    if suffix not in IMAGE_EXTENSIONS:
        # قد يكون ملفاً بلا امتداد لكن صورة فعلية
        try:
            head = path.read_bytes()[:32]
        except OSError as e:
            return False, f"unreadable: {e}", None
        sniffed = _sniff_image_format(head)
        if not sniffed:
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
    """
    يفحص قائمة ملفات، يرجع (صالح, مرفوض).
    expect: "image" أو "video" أو "any"
    """
    valid: List[Path] = []
    rejected: List[Dict[str, Any]] = []

    for f in files:
        if not f.is_file():
            continue

        suffix = f.suffix.lower()

        # فيديو
        if expect in ("video", "any") and suffix in VIDEO_EXTENSIONS:
            valid.append(f)
            continue

        # صورة
        if expect in ("image", "any"):
            ok, reason, info = is_valid_image_file(f)
            if ok:
                valid.append(f)
                continue
            else:
                # إذا كنا نتوقع "any" ولم تكن صورة، قد تكون فيديو
                if expect == "any" and suffix in VIDEO_EXTENSIONS:
                    valid.append(f)
                    continue
                rejected.append({
                    "file": f.name,
                    "error": reason,
                    "size": f.stat().st_size if f.exists() else 0,
                })
                continue

        # لم يطابق أي نوع متوقع
        rejected.append({
            "file": f.name,
            "error": f"unexpected type: {suffix}",
            "size": f.stat().st_size if f.exists() else 0,
        })

    return valid, rejected


# ─────────────────────────────────────────────────────────
# محرك 1: gallery-dl (الصور)
# ─────────────────────────────────────────────────────────

async def _run_gallery_dl(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
    timeout: int = 120,
) -> DownloadResult:
    """يحمّل الصور عبر gallery-dl."""
    import time
    start = time.perf_counter()

    if not _which("gallery-dl"):
        return DownloadResult(
            engine="gallery-dl",
            success=False,
            error="gallery-dl غير مثبّت (pip install gallery-dl)",
        )

    cmd = [
        "gallery-dl",
        "--dest", str(out_dir),
        "--no-part",
        "-q",  # quiet
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
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

        # فلترة: فقط الصور الصالحة
        valid, rejected = _filter_valid_files(all_files, expect="image")

        success = proc.returncode == 0 and len(valid) > 0

        result = DownloadResult(
            engine="gallery-dl",
            success=success,
            files=valid,
            error=None if success else (
                f"exit={proc.returncode}" if proc.returncode != 0
                else "no valid images after validation"
            ),
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
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return DownloadResult(
            engine="gallery-dl",
            success=False,
            error=str(e),
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────
# محرك 2: yt-dlp (الفيديو + thumbnails)
# ─────────────────────────────────────────────────────────

async def _run_yt_dlp(
    url: str,
    out_dir: Path,
    cookies_from_browser: Optional[str] = None,
    timeout: int = 300,
) -> DownloadResult:
    """يحمّل الفيديو + الصورة المصغّرة عبر yt-dlp."""
    import time
    start = time.perf_counter()

    if not _which("yt-dlp"):
        return DownloadResult(
            engine="yt-dlp",
            success=False,
            error="yt-dlp غير مثبّت (pip install yt-dlp)",
        )

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "-o", str(out_dir / "%(id)s.%(ext)s"),
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
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

        # yt-dlp قد يرجع فيديو + صورة مصغّرة. نقبل أي منهما.
        valid, rejected = _filter_valid_files(all_files, expect="any")

        success = proc.returncode == 0 and len(valid) > 0

        result = DownloadResult(
            engine="yt-dlp",
            success=success,
            files=valid,
            error=None if success else (
                f"exit={proc.returncode}" if proc.returncode != 0
                else "no valid media after validation"
            ),
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
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return DownloadResult(
            engine="yt-dlp",
            success=False,
            error=str(e),
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────
# محرك 3: requests مباشر (fallback للروابط المباشرة)
# ─────────────────────────────────────────────────────────

async def _run_direct(
    url: str,
    out_dir: Path,
    timeout: int = 60,
) -> DownloadResult:
    """
    يحمّل رابطاً مباشراً لصورة/فيديو عبر httpx.
    يتحقق أن المحتوى صورة أو فيديو فعلي، وليس صفحة HTML.
    """
    import time
    start = time.perf_counter()

    print(f"🎬 [direct] GET {url}")

    # تحذير مبكر لروابط المشاركة
    if is_share_link(url):
        print(f"🎬 [direct] ⚠️ share link detected — قد يرجع HTML")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            ct = resp.headers.get("content-type", "")
            data = resp.content
            duration = (time.perf_counter() - start) * 1000

            # فحص سريع: هل هو HTML؟
            if "html" in ct.lower() or "text/" in ct.lower():
                return DownloadResult(
                    engine="direct",
                    success=False,
                    error=f"content-type is not media: {ct}",
                    duration_ms=duration,
                    rejected=[{
                        "error": "HTML page, not an image",
                        "content_type": ct,
                        "size": len(data),
                    }],
                )

            # فحص magic bytes للصور
            sniffed = _sniff_image_format(data[:32])
            is_video = False
            if not sniffed:
                # فحص بسيط للفيديو
                if data[4:8] == b"ftyp" or data[:4] in (b"\x1a\x45\xdf\xa3",):
                    is_video = True

            if not sniffed and not is_video:
                return DownloadResult(
                    engine="direct",
                    success=False,
                    error="not a recognized image/video format",
                    duration_ms=duration,
                    rejected=[{
                        "error": "unknown format (magic bytes)",
                        "content_type": ct,
                        "size": len(data),
                    }],
                )

            # إذا كانت صورة، تحقق كامل
            if sniffed and not is_video:
                ok, reason, info = is_valid_image_bytes(data, ct)
                if not ok:
                    return DownloadResult(
                        engine="direct",
                        success=False,
                        error=f"invalid image: {reason}",
                        duration_ms=duration,
                        rejected=[{
                            "error": reason,
                            "content_type": ct,
                            "size": len(data),
                        }],
                    )

            # حدّد الامتداد الصحيح
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

            result = DownloadResult(
                engine="direct",
                success=True,
                files=[dest],
                duration_ms=duration,
            )
            print(
                f"🎬 [direct] OK, {len(data)} bytes, "
                f"{duration:.0f}ms, format={sniffed or ('video' if is_video else '?')}"
            )
            return result

    except httpx.HTTPStatusError as e:
        return DownloadResult(
            engine="direct",
            success=False,
            error=f"HTTP {e.response.status_code}",
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return DownloadResult(
            engine="direct",
            success=False,
            error=str(e),
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────
# الواجهة الموحّدة
# ─────────────────────────────────────────────────────────

class MediaDownloader:
    """
    يحاول تحميل URL عبر عدة محركات بالترتيب،
    ويطبع نتائج كل محاولة على الكونسول.
    """

    def __init__(
        self,
        cookies_from_browser: Optional[str] = None,
        prefer: Optional[List[str]] = None,
        allow_direct_for_share_links: bool = False,
    ):
        self.cookies_from_browser = cookies_from_browser
        self.prefer = prefer or ["gallery-dl", "yt-dlp", "direct"]
        # إذا False، لا نجرب direct على روابط المشاركة (لأنه سيرجع HTML)
        self.allow_direct_for_share_links = allow_direct_for_share_links

    async def download(
        self,
        url: str,
        out_dir: Optional[Path] = None,
        engines: Optional[List[str]] = None,
    ) -> DownloadBundle:
        out_dir = out_dir or Path(tempfile.mkdtemp(prefix="dl_"))
        out_dir.mkdir(parents=True, exist_ok=True)

        engines = engines or self.prefer
        available = detect_engines()

        bundle = DownloadBundle(url=url)

        share = is_share_link(url)
        if share:
            print(f"⚠️  Share link detected: {url}")

        print(f"\n{'='*60}")
        print(f"📥 Downloading: {url}")
        print(f"📁 Output dir: {out_dir}")
        print(f"🧩 Engines to try: {engines}")
        print(f"{'='*60}")

        for engine in engines:
            # تخطي direct على روابط المشاركة إذا مُنع
            if engine == "direct" and share and not self.allow_direct_for_share_links:
                print(f"⏭️  Skipping direct (share link, likely HTML)")
                bundle.results.append(DownloadResult(
                    engine="direct",
                    success=False,
                    error="skipped: share link likely returns HTML",
                ))
                continue

            if engine != "direct" and not available.get(engine, False):
                print(f"⏭️  Skipping {engine} (not installed)")
                bundle.results.append(DownloadResult(
                    engine=engine,
                    success=False,
                    error="not installed",
                ))
                continue

            if engine == "gallery-dl":
                res = await _run_gallery_dl(
                    url, out_dir, self.cookies_from_browser
                )
            elif engine == "yt-dlp":
                res = await _run_yt_dlp(
                    url, out_dir, self.cookies_from_browser
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
                print(f"❌ {engine} failed: {res.error}")

        print(f"{'='*60}")
        print(f"📊 Summary: {bundle.to_dict()}")
        print(f"{'='*60}\n")

        return bundle


# ─────────────────────────────────────────────────────────
# مساعد: تحميل صورة واحدة بسيطة
# ─────────────────────────────────────────────────────────

async def download_image(
    url: str,
    out_dir: Optional[Path] = None,
    cookies_from_browser: Optional[str] = None,
) -> Optional[Path]:
    """يرجع أول ملف تم تحميله أو None."""
    dl = MediaDownloader(cookies_from_browser=cookies_from_browser)
    bundle = await dl.download(url, out_dir=out_dir)
    files = bundle.all_files
    return files[0] if files else None
