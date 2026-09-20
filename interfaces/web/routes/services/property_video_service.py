"""Property video generation service — full pipeline."""
import asyncio
import logging
import random
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config.settings import settings
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.diagnostics import _diag, _diag_err
from ..core.directories import PROPERTY_VIDEOS_DIR
from ..jobs.persistence import update_job_async
from ..media.ffmpeg_helpers import _get_video_duration
from .edge_tts_service import edge_tts_generate

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Text / Price helpers
# ─────────────────────────────────────────────────────────

def _format_price_ar(price, currency: str = "SAR") -> str:
    """يُنسّق السعر بالعربي."""
    if not price:
        return ""
    symbol = {
        "SAR": "ريال",
        "AED": "درهم",
        "EGP": "جنيه",
        "USD": "$",
        "EUR": "€",
    }.get(currency, currency)
    try:
        price = float(price)
    except (TypeError, ValueError):
        return str(price)
    if price >= 1_000_000:
        v = f"{price / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{v} مليون {symbol}"
    if price >= 1_000:
        return f"{price / 1_000:.0f} ألف {symbol}"
    return f"{price:,.0f} {symbol}"


def _build_property_script(payload: Dict[str, Any]) -> str:
    """يبني نص التعليق الصوتي بالعربي."""
    type_map = {
        "land": "أرض", "villa": "فيلا", "apartment": "شقة",
        "building": "مبنى", "facade": "واجهة", "room": "غرفة",
        "hall": "صالة", "street": "موقع",
    }
    t = type_map.get(payload.get("property_type", ""), "عقار")

    parts: List[str] = []

    city = payload.get("city", "")
    district = payload.get("district", "")

    if district and city:
        parts.append(f"نقدم لكم {t} مميزة في حي {district} بمدينة {city}.")
    elif city:
        parts.append(f"نقدم لكم {t} مميزة في مدينة {city}.")
    else:
        parts.append(f"نقدم لكم {t} مميزة للبيع.")

    specs: List[str] = []
    if payload.get("area_sqm"):
        specs.append(f"مساحة {payload['area_sqm']:g} متر مربع")
    if payload.get("bedrooms"):
        specs.append(f"{payload['bedrooms']} غرف نوم")
    if payload.get("bathrooms"):
        specs.append(f"{payload['bathrooms']} دورات مياه")

    if specs:
        parts.append("تتميز بـ " + "، ".join(specs) + ".")

    features = payload.get("features", [])
    if features:
        parts.append("وتشمل " + "، ".join(features[:5]) + ".")

    price = payload.get("price")
    if price:
        parts.append(
            f"السعر {_format_price_ar(price, payload.get('currency', 'SAR'))}."
        )

    wa = payload.get("whatsapp", "")
    if wa:
        digits = " ".join(c for c in wa if c.isdigit())
        parts.append(f"للتواصل والاستفسار، اتصل على {digits}.")
    else:
        parts.append("للتواصل والاستفسار، راسلنا في التعليقات.")

    return " ".join(parts)


def _find_arabic_font() -> Optional[str]:
    """يبحث عن خط عربي متاح."""
    candidates = [
        "fonts/Cairo-Bold.ttf",
        "static/fonts/Cairo-Bold.ttf",
        "fonts/NotoNaskhArabic-Bold.ttf",
        "static/fonts/NotoNaskhArabic-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


# ─────────────────────────────────────────────────────────
# FFmpeg helpers
# ─────────────────────────────────────────────────────────

async def _render_motion_clip(
    image_path: Path,
    output_path: Path,
    duration: float,
    motion: str = "auto",
    width: int = 720,
    height: int = 1280,
    fps: int = 24,
) -> None:
    """يولّد مقطع فيديو من صورة بحركة Pan/Zoom — سريع."""
    if motion == "auto":
        motion = random.choice([
            "zoom_in", "zoom_out", "pan_left",
            "pan_right", "pan_up", "pan_down",
            "diagonal", "cinematic",
        ])

    frames = max(1, int(duration * fps))
    lw, lh = width * 2, height * 2

    base = (
        f"scale={lw}:{lh}:force_original_aspect_ratio=increase,"
        f"crop={lw}:{lh},"
    )

    motion_map = {
        "zoom_in": (
            f"zoompan=z='min(1.20,1+0.20*on/{frames})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "zoom_out": (
            f"zoompan=z='max(1.0,1.20-0.20*on/{frames})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_left": (
            f"zoompan=z='1.10':x='(iw-iw/zoom)*on/{frames}':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_right": (
            f"zoompan=z='1.10':x='(iw-iw/zoom)*(1-on/{frames})':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_up": (
            f"zoompan=z='1.10':x='iw/2-(iw/zoom/2)':"
            f"y='(ih-ih/zoom)*on/{frames}':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "pan_down": (
            f"zoompan=z='1.10':x='iw/2-(iw/zoom/2)':"
            f"y='(ih-ih/zoom)*(1-on/{frames})':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "diagonal": (
            f"zoompan=z='1.05+0.10*on/{frames}':"
            f"x='(iw-iw/zoom)*on/{frames}':"
            f"y='(ih-ih/zoom)*(1-on/{frames})':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
        "cinematic": (
            f"zoompan=z='1.02+0.08*sin(on/{frames}*PI/2)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},setsar=1"
        ),
    }

    vf = base + motion_map.get(motion, motion_map["zoom_in"])

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        "-t", str(duration),
        "-r", str(fps),
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"motion render failed: {stderr.decode(errors='ignore')[-500:]}"
        )


async def _concat_video_clips(
    clips: List[Path],
    output: Path,
    tmp_dir: Path,
) -> None:
    """يدمج مقاطع الفيديو."""
    concat_file = tmp_dir / "concat.txt"

    with concat_file.open("w", encoding="utf-8") as f:
        for clip in clips:
            safe = str(clip.absolute()).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"concat failed: {stderr.decode(errors='ignore')[-500:]}"
        )


async def _add_property_text_overlays(
    input_video: Path,
    payload: Dict[str, Any],
    output: Path,
    tmp_dir: Path,
) -> None:
    """يضيف النصوص العربية على الفيديو — سريع."""

    if not any([
        payload.get("show_price", True),
        payload.get("show_location", True),
        payload.get("show_area", True),
        payload.get("show_contact", True),
    ]):
        _diag("📝 All text overlays disabled — skipping")
        shutil.copy(input_video, output)
        return

    font = _find_arabic_font()
    if not font:
        _diag("⚠️ No Arabic font found — skipping text overlays")
        shutil.copy(input_video, output)
        return

    type_map = {
        "land": "أرض", "villa": "فيلا", "apartment": "شقة",
        "building": "مبنى", "facade": "واجهة", "room": "غرفة",
        "hall": "صالة", "street": "موقع",
    }
    t = type_map.get(payload.get("property_type", ""), "عقار")

    title = payload.get("title") or f"{t} للبيع"
    location = " - ".join(filter(None, [
        payload.get("district", ""),
        payload.get("city", ""),
    ]))
    price = _format_price_ar(
        payload.get("price"),
        payload.get("currency", "SAR"),
    ) if payload.get("show_price", True) else ""

    details_parts: List[str] = []
    if payload.get("show_area", True):
        if payload.get("area_sqm"):
            details_parts.append(f"{payload['area_sqm']:g} م²")
        if payload.get("bedrooms"):
            details_parts.append(f"{payload['bedrooms']} غرف")

    details = "   ".join(details_parts)
    contact = payload.get("whatsapp", "") if payload.get("show_contact", True) else ""

    def _write_text(name: str, text: str) -> str:
        p = tmp_dir / f"txt_{name}.txt"
        p.write_text(text, encoding="utf-8")
        return str(p)

    filters: List[str] = []

    if title:
        f = _write_text("title", title)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=48:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw=16:"
            f"x=(w-text_w)/2:y=h*0.08"
        )

    if location and payload.get("show_location", True):
        f = _write_text("loc", location)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=32:fontcolor=white:"
            f"box=1:boxcolor=black@0.4:boxborderw=12:"
            f"x=(w-text_w)/2:y=h*0.17"
        )

    if price:
        f = _write_text("price", price)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=54:fontcolor=black:"
            f"box=1:boxcolor=white@0.9:boxborderw=18:"
            f"x=(w-text_w)/2:y=h*0.72"
        )

    if details:
        f = _write_text("details", details)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=28:fontcolor=white:"
            f"box=1:boxcolor=black@0.5:boxborderw=12:"
            f"x=(w-text_w)/2:y=h*0.85"
        )

    if contact:
        f = _write_text("contact", contact)
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{f}':"
            f"fontsize=30:fontcolor=white:"
            f"box=1:boxcolor=black@0.7:boxborderw=14:"
            f"x=(w-text_w)/2:y=h*0.92"
        )

    if not filters:
        shutil.copy(input_video, output)
        return

    vf = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"text overlay failed: {stderr.decode(errors='ignore')[-500:]}"
        )


async def _attach_voiceover(
    video_path: Path,
    voiceover_path: Path,
    output: Path,
) -> None:
    """يدمج التعليق الصوتي مع الفيديو."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(voiceover_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"voiceover attach failed: {stderr.decode(errors='ignore')[-500:]}"
        )


# ─────────────────────────────────────────────────────────
# Main job runner
# ─────────────────────────────────────────────────────────

async def run_property_video_job(job_id: str, payload: Dict[str, Any]) -> None:
    """ينفّذ توليد الفيديو العقاري كاملاً في الخلفية."""
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"prop_{job_id}_"))

        try:
            images = payload.get("images", [])
            duration_per_image = float(payload.get("duration_per_image", 4.5))
            voice = payload.get("voiceover_voice", "ar-SA-HamedNeural")

            voiceover_enabled = payload.get("voiceover_enabled", True)

            overlay_enabled = any([
                payload.get("show_price", True),
                payload.get("show_location", True),
                payload.get("show_area", True),
                payload.get("show_contact", True),
            ])

            _diag(f"🏠 Property job {job_id}:")
            _diag(f"   voiceover_enabled = {voiceover_enabled}")
            _diag(f"   overlay_enabled   = {overlay_enabled}")
            _diag(f"   images            = {len(images)}")

            # ═══ 1. motion clips ═══
            await update_job_async(
                job_id, status="running", stage="motion", progress=0.05
            )

            motion_clips: List[Path] = []

            for idx, img in enumerate(images):
                img_path_str = img.get("path") or img.get("local_path")
                motion = img.get("motion", "auto")

                img_path: Optional[Path] = None

                if img_path_str and not str(img_path_str).startswith("http"):
                    p = Path(str(img_path_str))
                    if p.exists():
                        img_path = p

                if img_path is None:
                    img_url = img.get("url", "")
                    if img_url.startswith("http"):
                        try:
                            async with httpx.AsyncClient(
                                timeout=60.0, follow_redirects=True
                            ) as c:
                                r = await c.get(img_url)
                                if r.status_code == 200:
                                    suffix = (
                                        Path(img_url.split("?")[0]).suffix or ".jpg"
                                    )
                                    dl_path = tmp_dir / f"img_{idx}{suffix}"
                                    dl_path.write_bytes(r.content)
                                    img_path = dl_path
                        except Exception as e:
                            _diag_err(
                                f"⚠️ Failed to download image {idx}: {e}", e
                            )

                if img_path is None or not img_path.exists():
                    _diag(f"⚠️ Skipping missing image {idx}")
                    continue

                clip_path = tmp_dir / f"motion_{idx:03d}.mp4"

                await _render_motion_clip(
                    image_path=img_path,
                    output_path=clip_path,
                    duration=duration_per_image,
                    motion=motion,
                )

                motion_clips.append(clip_path)

                if len(images) > 0:
                    await update_job_async(
                        job_id,
                        progress=0.05 + (idx + 1) / len(images) * 0.4,
                    )

            if not motion_clips:
                raise RuntimeError("لم يتم توليد أي مقطع — تحقق من الصور")

            # ═══ 2. concat ═══
            await update_job_async(job_id, stage="concat", progress=0.5)

            stitched = tmp_dir / "stitched.mp4"
            await _concat_video_clips(motion_clips, stitched, tmp_dir)

            # ═══ 3. voiceover (اختياري) ═══
            voiceover_path: Optional[Path] = None

            if voiceover_enabled:
                await update_job_async(
                    job_id, stage="voiceover", progress=0.6
                )

                voiceover_text = _build_property_script(payload)

                try:
                    audio_bytes = await edge_tts_generate(
                        text=voiceover_text,
                        voice=voice,
                    )
                    voiceover_path = tmp_dir / "voiceover.mp3"
                    voiceover_path.write_bytes(audio_bytes)
                    _diag(
                        f"🎙️ Voiceover generated ({len(audio_bytes)} bytes)"
                    )
                except Exception as e:
                    _diag_err(
                        f"⚠️ Voiceover failed, continuing without it: {e}", e
                    )
                    voiceover_path = None
            else:
                _diag("🔇 Voiceover disabled — skipping TTS")
                await update_job_async(
                    job_id, stage="voiceover", progress=0.6
                )

            # ═══ 4. text overlays (اختياري) ═══
            with_text = tmp_dir / "with_text.mp4"

            if overlay_enabled:
                await update_job_async(job_id, stage="text", progress=0.75)

                await _add_property_text_overlays(
                    input_video=stitched,
                    payload=payload,
                    output=with_text,
                    tmp_dir=tmp_dir,
                )
            else:
                _diag("📝 Text overlays disabled — skipping")
                shutil.copy(stitched, with_text)
                await update_job_async(job_id, stage="text", progress=0.75)

            # ═══ 5. audio mix ═══
            await update_job_async(job_id, stage="audio", progress=0.85)

            final_video = tmp_dir / "final.mp4"

            if voiceover_path and voiceover_path.exists():
                await _attach_voiceover(
                    video_path=with_text,
                    voiceover_path=voiceover_path,
                    output=final_video,
                )
            else:
                shutil.copy(with_text, final_video)

            # ═══ 6. upload ═══
            await update_job_async(job_id, stage="upload", progress=0.92)

            project_id = payload.get("project_id", "unknown")
            unique = uuid.uuid4().hex[:12]
            remote_path = f"property_videos/{project_id}/{unique}.mp4"

            final_url: Optional[str] = None

            if settings.supabase_configured:
                try:
                    from application.services.production_service import (
                        _upload_to_supabase, _build_public_url,
                    )
                    storage = SupabaseStorageAdapter()

                    await _upload_to_supabase(
                        storage=storage,
                        local_path=final_video,
                        remote_path=remote_path,
                        content_type="video/mp4",
                    )
                    final_url = await _build_public_url(storage, remote_path)
                except Exception as e:
                    _diag_err(f"⚠️ Supabase upload failed: {e}", e)

            if not final_url:
                local_dest = PROPERTY_VIDEOS_DIR / f"{project_id}_{unique}.mp4"
                shutil.copy(final_video, local_dest)
                final_url = f"/static/media/property_videos/{local_dest.name}"
                remote_path = str(local_dest)

            real_duration = await _get_video_duration(final_video)

            await update_job_async(
                job_id,
                status="done",
                stage="done",
                progress=1.0,
                video_url=final_url,
                path=remote_path,
                duration=real_duration,
                property_meta={
                    "title": payload.get("title"),
                    "price": payload.get("price"),
                    "currency": payload.get("currency"),
                    "city": payload.get("city"),
                    "district": payload.get("district"),
                    "property_type": payload.get("property_type"),
                },
            )

            _diag(
                f"✅ Property video done: {final_url} ({real_duration:.2f}s)"
            )

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        _diag_err(f"❌ Property video job failed: {e}", e)
        await update_job_async(job_id, status="failed", error=str(e))
