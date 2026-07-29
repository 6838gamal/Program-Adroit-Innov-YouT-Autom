from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, AsyncIterator


class StoragePort(ABC):
    """Abstract file storage contract (local, S3, GCS, etc.)."""

    @abstractmethod
    async def save(self, source: Path, destination: str) -> str:
        """Save a file and return its storage key."""
        ...

    @abstractmethod
    async def get_path(self, key: str) -> Path:
        """Resolve a storage key to a local-accessible path."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a URL for client-side access."""
        ...
