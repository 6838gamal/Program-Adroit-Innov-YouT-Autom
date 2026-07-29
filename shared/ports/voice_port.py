from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VoiceConfig:
    voice_id: str = "default"
    language: str = "en"
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    extra: dict = field(default_factory=dict)


@dataclass
class VoiceInfo:
    id: str
    name: str
    language: str
    gender: str = "neutral"
    description: str = ""


@dataclass
class VoiceGenerationResult:
    audio_path: Path
    duration: float
    sample_rate: int = 22050


class VoicePort(ABC):
    """Abstract TTS engine contract."""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        ...

    @abstractmethod
    async def generate(
        self,
        text: str,
        config: VoiceConfig,
        output_path: Path,
    ) -> VoiceGenerationResult:
        ...

    @abstractmethod
    async def list_voices(self) -> list[VoiceInfo]:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...
