"""Jinja2 templates + custom filters."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

# المسار: interfaces/web/routes/core/templates.py
# templates/ في جذر المشروع → نصعد 4 مستويات
_TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _format_duration(seconds) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_number(value) -> str:
    if value is None:
        return "0"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


templates.env.filters["format_duration"] = _format_duration
templates.env.filters["format_number"] = _format_number
