from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable
import uuid


@dataclass
class RenderSettings:
    fps: int = 30
    resolution_width: int = 1920
    resolution_height: int = 1080
    quality: str = "high"   # low|medium|high
    threads: int = 0         # 0 = auto


@dataclass
class RenderResult:
    output_path: Path
    duration: float
    file_size: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ThumbnailConfig:
    width: int = 1280
    height: int = 720
    title: str = ""
    logo_path: Path | None = None
    primary_color: str = "#3B82F6"
    text_color: str = "#FFFFFF"
    font_path: Path | None = None


@dataclass
class RendererCapabilities:
    supported_formats: list[str] = field(default_factory=lambda: ["mp4"])
    supports_hardware_acceleration: bool = False
    max_resolution: tuple[int, int] = (3840, 2160)
    name: str = "unknown"


class RendererPort(ABC):
    """
    Abstract rendering engine contract.
    Core only depends on this — never on FFmpeg or any other tool directly.
    """

    @abstractmethod
    async def render(
        self,
        project_id: uuid.UUID,
        timeline_data: dict,
        assets: dict,
        settings: RenderSettings,
        temp_dir: Path,
        progress_callback: Callable[[float, str], Awaitable[None]],
    ) -> RenderResult:
        ...

    @abstractmethod
    async def generate_thumbnail(
        self,
        video_path: Path,
        config: ThumbnailConfig,
        output_path: Path,
    ) -> Path:
        ...

    @abstractmethod
    def get_capabilities(self) -> RendererCapabilities:
        ...
