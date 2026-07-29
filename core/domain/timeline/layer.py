import uuid
from typing import Optional
from shared.base_entity import BaseEntity
from shared.value_objects import LayerType


class Layer(BaseEntity):
    """Base layer entity — a single visual/audio element within a scene."""

    def __init__(
        self,
        scene_id: uuid.UUID,
        type: LayerType,
        name: str = "",
        position: int = 0,
        start_time: float = 0.0,
        end_time: Optional[float] = None,
        asset_id: Optional[uuid.UUID] = None,
        properties: Optional[dict] = None,
        effects: Optional[list[dict]] = None,
        animations: Optional[list[dict]] = None,
        is_visible: bool = True,
        z_index: int = 0,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.scene_id = scene_id
        self.type = type
        self.name = name or type.value
        self.position = position
        self.start_time = start_time
        self.end_time = end_time
        self.asset_id = asset_id
        self.properties: dict = properties or {}
        self.effects: list[dict] = effects or []
        self.animations: list[dict] = animations or []
        self.is_visible = is_visible
        self.z_index = z_index

    def add_effect(self, effect_type: str, params: Optional[dict] = None) -> None:
        self.effects.append({"type": effect_type, "params": params or {}})
        self._touch()

    def add_animation(self, keyframes: list[dict]) -> None:
        self.animations.append({"keyframes": keyframes})
        self._touch()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "scene_id": str(self.scene_id),
            "type": self.type.value,
            "name": self.name,
            "position": self.position,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "asset_id": str(self.asset_id) if self.asset_id else None,
            "properties": self.properties,
            "effects": self.effects,
            "animations": self.animations,
            "is_visible": self.is_visible,
            "z_index": self.z_index,
        }


# ── Specialised layer types ───────────────────────────────────────────────────

class VideoLayer(Layer):
    def __init__(self, scene_id: uuid.UUID, asset_id: uuid.UUID, **kwargs):
        super().__init__(scene_id=scene_id, type=LayerType.VIDEO,
                         asset_id=asset_id, **kwargs)
        self.properties.setdefault("volume", 1.0)
        self.properties.setdefault("playback_rate", 1.0)
        self.properties.setdefault("fit_mode", "cover")


class ImageLayer(Layer):
    def __init__(self, scene_id: uuid.UUID, asset_id: uuid.UUID, **kwargs):
        super().__init__(scene_id=scene_id, type=LayerType.IMAGE,
                         asset_id=asset_id, **kwargs)
        self.properties.setdefault("x", 0)
        self.properties.setdefault("y", 0)
        self.properties.setdefault("width", 1920)
        self.properties.setdefault("height", 1080)
        self.properties.setdefault("opacity", 1.0)
        self.properties.setdefault("fit_mode", "cover")


class TextLayer(Layer):
    def __init__(self, scene_id: uuid.UUID, content: str, **kwargs):
        super().__init__(scene_id=scene_id, type=LayerType.TEXT, **kwargs)
        self.properties.setdefault("content", content)
        self.properties.setdefault("font_family", "Arial")
        self.properties.setdefault("font_size", 48)
        self.properties.setdefault("color", "#FFFFFF")
        self.properties.setdefault("alignment", "center")
        self.properties.setdefault("x", 0)
        self.properties.setdefault("y", 0)


class AudioLayer(Layer):
    def __init__(self, scene_id: uuid.UUID, asset_id: uuid.UUID, **kwargs):
        super().__init__(scene_id=scene_id, type=LayerType.AUDIO,
                         asset_id=asset_id, **kwargs)
        self.properties.setdefault("volume", 1.0)
        self.properties.setdefault("fade_in", 0.0)
        self.properties.setdefault("fade_out", 0.0)


class SubtitleLayer(Layer):
    def __init__(self, scene_id: uuid.UUID, **kwargs):
        super().__init__(scene_id=scene_id, type=LayerType.SUBTITLE, **kwargs)
        self.properties.setdefault("format", "srt")
        self.properties.setdefault("font_family", "Arial")
        self.properties.setdefault("font_size", 36)
        self.properties.setdefault("color", "#FFFFFF")
        self.properties.setdefault("alignment", "bottom-center")


class LogoLayer(Layer):
    def __init__(self, scene_id: uuid.UUID, asset_id: uuid.UUID, **kwargs):
        super().__init__(scene_id=scene_id, type=LayerType.LOGO,
                         asset_id=asset_id, **kwargs)
        self.properties.setdefault("corner", "top-right")
        self.properties.setdefault("margin", 20)
        self.properties.setdefault("opacity", 0.9)
        self.properties.setdefault("width", 150)
