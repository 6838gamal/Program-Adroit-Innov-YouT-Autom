import uuid
from typing import Optional
from shared.base_entity import BaseEntity


class Template(BaseEntity):
    """A reusable design template for projects."""

    def __init__(
        self,
        name: str,
        description: str = "",
        thumbnail: Optional[str] = None,
        settings: Optional[dict] = None,
        is_builtin: bool = False,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.name = name
        self.description = description
        self.thumbnail = thumbnail
        self.is_builtin = is_builtin
        # settings holds: colors, fonts, text_positions, logo_position,
        # resolution, transitions, effects, subtitle_style, animation_presets
        self.settings: dict = settings or {
            "colors": {
                "primary": "#3B82F6",
                "secondary": "#1E40AF",
                "accent": "#F59E0B",
                "text": "#FFFFFF",
                "background": "#000000",
            },
            "fonts": {
                "heading": "Arial",
                "body": "Arial",
                "subtitle": "Arial",
            },
            "resolution": {"width": 1920, "height": 1080},
            "fps": 30,
            "default_transition": {"type": "fade", "duration": 0.5},
            "subtitle_style": {
                "font_family": "Arial",
                "font_size": 36,
                "color": "#FFFFFF",
                "background": "rgba(0,0,0,0.7)",
                "alignment": "bottom-center",
            },
            "logo": {
                "corner": "top-right",
                "margin": 20,
                "opacity": 0.9,
            },
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "thumbnail": self.thumbnail,
            "is_builtin": self.is_builtin,
            "settings": self.settings,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
