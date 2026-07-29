import uuid
from typing import Optional
from shared.base_entity import BaseEntity
from core.domain.timeline.layer import Layer


class Scene(BaseEntity):
    """A scene within a track — a time-bounded segment containing layers."""

    def __init__(
        self,
        track_id: uuid.UUID,
        timeline_id: uuid.UUID,
        start_time: float,
        end_time: float,
        name: str = "",
        position: int = 0,
        transition_in: Optional[dict] = None,
        transition_out: Optional[dict] = None,
        settings: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.track_id = track_id
        self.timeline_id = timeline_id
        self.start_time = start_time
        self.end_time = end_time
        self.name = name
        self.position = position
        self.transition_in = transition_in  # {type: "fade", duration: 0.5}
        self.transition_out = transition_out
        self.settings: dict = settings or {}
        self.layers: list[Layer] = []

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def add_layer(self, layer: Layer) -> None:
        layer.z_index = len(self.layers)
        self.layers.append(layer)
        self._touch()

    def get_layer(self, layer_id: uuid.UUID) -> Optional[Layer]:
        return next((l for l in self.layers if l.id == layer_id), None)

    def remove_layer(self, layer_id: uuid.UUID) -> bool:
        before = len(self.layers)
        self.layers = [l for l in self.layers if l.id != layer_id]
        return len(self.layers) < before

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "track_id": str(self.track_id),
            "timeline_id": str(self.timeline_id),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "name": self.name,
            "position": self.position,
            "transition_in": self.transition_in,
            "transition_out": self.transition_out,
            "settings": self.settings,
            "layers": [l.to_dict() for l in sorted(self.layers, key=lambda x: x.z_index)],
        }
