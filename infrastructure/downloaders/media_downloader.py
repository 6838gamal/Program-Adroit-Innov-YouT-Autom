"""
مكتبة تحميل موحّدة للصور والفيديوهات.

تدعم عدة محركات (engines):
  - gallery-dl  → الصور من فيسبوك/إنستغرام/تويتر...
  - yt-dlp      → الفيديوهات
  - requests    → رابط مباشر (fallback)

تجرب كل محرك على حدة وتطبع النتائج على الكونسول.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


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

    @property
    def count(self) -> int:
        return len(self.files)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "success": self.success,
            "count": self.count,
            "files": [str(f) for f in self.files],
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


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
    }
    logger.info("🔍 Detected download engines: %s", engines)
    print(f"🔍 Detected download engines: {engines}")
    return engines


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
        url,
    ]
    if cookies_from_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_from_browser]

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

        files = [p for p in out_dir.rglob("*") if p.is_file()]

        result = DownloadResult(
            engine="gallery-dl",
            success=proc.returncode == 0 and len(files) > 0,
            files=files,
            error=None if proc.returncode == 0 else f"exit={proc.returncode}",
            stdout=stdout,
            stderr=stderr,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

        print(
            f"🎬 [gallery-dl] rc={proc.returncode}, "
            f"files={len(files)}, {result.duration_ms:.0f}ms"
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
        url,
    ]
    if cookies_from_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_from_browser]

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

        files = [p for p in out_dir.rglob("*") if p.is_file()]

        result = DownloadResult(
            engine="yt-dlp",
            success=proc.returncode == 0 and len(files) > 0,
            files=files,
            error=None if proc.returncode == 0 else f"exit={proc.returncode}",
            stdout=stdout,
            stderr=stderr,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

        print(
            f"🎬 [yt-dlp] rc={proc.returncode}, "
            f"files={len(files)}, {result.duration_ms:.0f}ms"
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
    """يحمّل رابطاً مباشراً لصورة/فيديو عبر httpx."""
    import time
    start = time.perf_counter()

    print(f"🎬 [direct] GET {url}")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            suffix = Path(urlparse(url).path).suffix or ".bin"
            if suffix.lower() not in {
                ".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"
            }:
                ct = resp.headers.get("content-type", "")
                if "jpeg" in ct: suffix = ".jpg"
                elif "png" in ct: suffix = ".png"
                elif "webp" in ct: suffix = ".webp"
                elif "mp4" in ct: suffix = ".mp4"
                else: suffix = ".jpg"

            dest = out_dir / f"direct_{uuid.uuid4().hex[:8]}{suffix}"
            dest.write_bytes(resp.content)

            result = DownloadResult(
                engine="direct",
                success=True,
                files=[dest],
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            print(
                f"🎬 [direct] OK, {len(resp.content)} bytes, "
                f"{result.duration_ms:.0f}ms"
            )
            return result

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
    ):
        self.cookies_from_browser = cookies_from_browser
        self.prefer = prefer or ["gallery-dl", "yt-dlp", "direct"]

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

        print(f"\n{'='*60}")
        print(f"📥 Downloading: {url}")
        print(f"📁 Output dir: {out_dir}")
        print(f"🧩 Engines to try: {engines}")
        print(f"{'='*60}")

        for engine in engines:
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
