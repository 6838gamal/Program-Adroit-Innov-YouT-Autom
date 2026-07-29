import uuid
from typing import Optional
from shared.base_entity import BaseEntity
from shared.value_objects import TrackType
from core.domain.timeline.scene import Scene


class Track(BaseEntity):
    """A single track within a Timeline (video, audio, subtitle, etc.)."""

    def __init__(
        self,
        timeline_id: uuid.UUID,
        type: TrackType,
        name: str = "",
        position: int = 0,
        is_muted: bool = False,
        is_locked: bool = False,
        settings: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.timeline_id = timeline_id
        self.type = type
        self.name = name or type.value
        self.position = position
        self.is_muted = is_muted
        self.is_locked = is_locked
        self.settings: dict = settings or {}
        self.scenes: list[Scene] = []

    def add_scene(
        self,
        start_time: float,
        end_time: float,
        name: str = "",
        transition_in: Optional[dict] = None,
        transition_out: Optional[dict] = None,
    ) -> Scene:
        pos = len(self.scenes)
        scene = Scene(
            track_id=self.id,
            timeline_id=self.timeline_id,
            start_time=start_time,
            end_time=end_time,
            name=name or f"Scene {pos + 1}",
            position=pos,
            transition_in=transition_in,
            transition_out=transition_out,
        )
        self.scenes.append(scene)
        return scene

    def get_scene(self, scene_id: uuid.UUID) -> Optional[Scene]:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def remove_scene(self, scene_id: uuid.UUID) -> bool:
        before = len(self.scenes)
        self.scenes = [s for s in self.scenes if s.id != scene_id]
        return len(self.scenes) < before

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "timeline_id": str(self.timeline_id),
            "type": self.type.value,
            "name": self.name,
            "position": self.position,
            "is_muted": self.is_muted,
            "is_locked": self.is_locked,
            "settings": self.settings,
            "scenes": [s.to_dict() for s in self.scenes],
        }
