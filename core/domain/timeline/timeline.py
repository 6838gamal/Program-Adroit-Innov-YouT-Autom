import uuid
from typing import Optional
from shared.base_entity import BaseEntity
from shared.value_objects import Resolution, TrackType
from core.domain.timeline.track import Track


class Timeline(BaseEntity):
    """Timeline aggregate — holds the complete temporal structure of a project."""

    def __init__(
        self,
        project_id: uuid.UUID,
        fps: int = 30,
        width: int = 1920,
        height: int = 1080,
        duration: float = 0.0,
        settings: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.project_id = project_id
        self.fps = fps
        self.width = width
        self.height = height
        self.duration = duration
        self.settings: dict = settings or {}
        self.tracks: list[Track] = []
        self.markers: list[dict] = []

    @property
    def resolution(self) -> Resolution:
        return Resolution(self.width, self.height)

    def add_track(self, type: TrackType, name: str = "") -> Track:
        position = len(self.tracks)
        track = Track(
            timeline_id=self.id,
            type=type,
            name=name or type.value,
            position=position,
        )
        self.tracks.append(track)
        self._touch()
        return track

    def get_track(self, track_id: uuid.UUID) -> Optional[Track]:
        return next((t for t in self.tracks if t.id == track_id), None)

    def remove_track(self, track_id: uuid.UUID) -> bool:
        before = len(self.tracks)
        self.tracks = [t for t in self.tracks if t.id != track_id]
        if len(self.tracks) < before:
            self._touch()
            return True
        return False

    def add_marker(self, time: float, label: str, color: str = "#F59E0B") -> None:
        self.markers.append({"time": time, "label": label, "color": color})
        self._touch()

    def recalculate_duration(self) -> None:
        max_end = 0.0
        for track in self.tracks:
            for scene in track.scenes:
                if scene.end_time > max_end:
                    max_end = scene.end_time
        self.duration = max_end
        self._touch()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "settings": self.settings,
            "tracks": [t.to_dict() for t in self.tracks],
            "markers": self.markers,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
