"""
Pillow Scene Image Generator.
Creates a full-resolution scene image from text content.
Supports Arabic (RTL) text, gradient backgrounds, and branding.
"""
import asyncio
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Gradient palettes (background_top, background_bottom, text_color)
_PALETTES = [
    ((15, 23, 42),   (30, 58, 138),  "#FFFFFF"),   # Dark blue
    ((17, 24, 39),   (55, 65, 81),   "#F9FAFB"),   # Dark gray
    ((7,  15, 30),   (30, 41, 59),   "#E2E8F0"),   # Navy
    ((20, 10, 40),   (67, 20, 100),  "#F3E8FF"),   # Purple
    ((5,  46, 22),   (20, 83, 45),   "#DCFCE7"),   # Dark green
    ((69, 10, 10),   (127, 29, 29),  "#FEE2E2"),   # Dark red
]


class SceneImageGenerator:
    """
    Generates high-quality scene images using Pillow.
    Each scene becomes a 1920×1080 image with gradient background + text overlay.
    """

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        font_path: Optional[Path] = None,
    ):
        self.width = width
        self.height = height
        self.font_path = font_path

    async def generate_scene_image(
        self,
        text: str,
        output_path: Path,
        scene_index: int = 0,
        title: str = "",
        brand_color: Optional[str] = None,
        logo_path: Optional[Path] = None,
    ) -> Path:
        """Generate a scene image asynchronously in an executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._render(text, output_path, scene_index, title, brand_color, logo_path),
        )

    def _render(
        self,
        text: str,
        output_path: Path,
        scene_index: int,
        title: str,
        brand_color: Optional[str],
        logo_path: Optional[Path],
    ) -> Path:
        from PIL import Image, ImageDraw, ImageFont

        W, H = self.width, self.height
        palette_idx = scene_index % len(_PALETTES)
        top_color, bot_color, default_text_color = _PALETTES[palette_idx]

        # ── Gradient background ───────────────────────────────────────────────
        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)

        for y in range(H):
            t = y / H
            r = int(top_color[0] + (bot_color[0] - top_color[0]) * t)
            g = int(top_color[1] + (bot_color[1] - top_color[1]) * t)
            b = int(top_color[2] + (bot_color[2] - top_color[2]) * t)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # ── Subtle grid overlay ───────────────────────────────────────────────
        for x in range(0, W, 80):
            draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
        for y in range(0, H, 80):
            draw.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)

        # ── Brand accent bar ──────────────────────────────────────────────────
        accent = self._parse_color(brand_color) if brand_color else (59, 130, 246)
        draw.rectangle([(0, H - 8), (W, H)], fill=accent)
        draw.rectangle([(0, 0), (W, 8)], fill=accent)

        # ── Scene number badge ────────────────────────────────────────────────
        badge_text = str(scene_index + 1)
        try:
            badge_font = self._load_font(36)
        except Exception:
            badge_font = ImageFont.load_default()
        badge_x, badge_y = 60, 50
        draw.ellipse(
            [(badge_x - 30, badge_y - 30), (badge_x + 30, badge_y + 30)],
            fill=(*accent, 200),
        )
        draw.text((badge_x, badge_y), badge_text, font=badge_font,
                  fill="#FFFFFF", anchor="mm")

        # ── Title (small, top area) ───────────────────────────────────────────
        if title:
            try:
                title_font = self._load_font(32)
            except Exception:
                title_font = ImageFont.load_default()
            draw.text(
                (W // 2, 55), title, font=title_font,
                fill="#94A3B8", anchor="mm",
            )

        # ── Main scene text ───────────────────────────────────────────────────
        text_color = default_text_color
        margin_x = int(W * 0.12)
        max_text_width = W - 2 * margin_x
        center_y = H // 2

        wrapped = self._wrap_text(text, max_text_width, font_size=56)

        try:
            body_font = self._load_font(56)
        except Exception:
            body_font = ImageFont.load_default()

        line_height = 80
        total_height = len(wrapped) * line_height
        start_y = center_y - total_height // 2

        for i, line in enumerate(wrapped):
            y_pos = start_y + i * line_height
            # Shadow
            draw.text(
                (W // 2 + 3, y_pos + 3), line, font=body_font,
                fill=(0, 0, 0), anchor="mm",
            )
            # Text
            draw.text(
                (W // 2, y_pos), line, font=body_font,
                fill=text_color, anchor="mm",
            )

        # ── Logo overlay ──────────────────────────────────────────────────────
        if logo_path and logo_path.exists():
            try:
                logo = Image.open(logo_path).convert("RGBA")
                logo_w = 120
                ratio = logo_w / logo.width
                logo_h = int(logo.height * ratio)
                logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
                img.paste(logo, (W - logo_w - 30, 30), logo)
            except Exception as e:
                logger.warning("Could not overlay logo: %s", e)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "JPEG", quality=95)
        return output_path

    def _wrap_text(self, text: str, max_width_px: int, font_size: int = 56) -> list[str]:
        """Wrap text so each line fits within max_width_px (approx by char count)."""
        # Approximate: at font_size=56, each Arabic char ≈ 35px, Latin ≈ 28px
        chars_per_line = max(10, max_width_px // (font_size // 2))
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            if len(test) <= chars_per_line:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        # Hard-cap at 5 lines
        if len(lines) > 5:
            lines = lines[:4] + ["…"]
        return lines

    def _load_font(self, size: int):
        from PIL import ImageFont
        # Try system fonts that support Arabic
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/run/current-system/sw/share/X11/fonts/DejaVuSans.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        if self.font_path and self.font_path.exists():
            return ImageFont.truetype(str(self.font_path), size)
        return ImageFont.load_default()

    @staticmethod
    def _parse_color(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            return (59, 130, 246)
