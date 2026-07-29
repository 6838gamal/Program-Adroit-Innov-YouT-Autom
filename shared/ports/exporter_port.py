from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable


@dataclass
class ExportSettings:
    format: str = "mp4"             # mp4|mov|avi|gif|webm
    aspect_ratio: str = "16:9"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    video_bitrate: str = "5M"
    audio_bitrate: str = "192k"
    crf: int = 23                   # quality factor (lower = better)
    preset: str = "medium"          # ffmpeg preset
    extra_args: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    output_path: Path
    file_size: int
    duration: float
    format: str
    resolution: tuple[int, int]


class ExporterPort(ABC):
    """Abstract export engine contract."""

    @abstractmethod
    async def export(
        self,
        input_path: Path,
        settings: ExportSettings,
        output_path: Path,
        progress_callback: Callable[[float], Awaitable[None]],
    ) -> ExportResult:
        ...

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        ...
