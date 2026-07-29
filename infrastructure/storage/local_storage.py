import shutil
from pathlib import Path

from shared.ports.storage_port import StoragePort
from config.settings import settings


class LocalStorageAdapter(StoragePort):
    """Stores files on the local filesystem under MEDIA_DIR."""

    def __init__(self, base_dir: Path | None = None):
        self._base = base_dir or settings.MEDIA_DIR
        self._base.mkdir(parents=True, exist_ok=True)

    async def save(self, source: Path, destination: str) -> str:
        dest_path = self._base / destination
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest_path)
        return destination

    async def get_path(self, key: str) -> Path:
        return self._base / key

    async def delete(self, key: str) -> None:
        p = self._base / key
        if p.exists():
            p.unlink()

    async def exists(self, key: str) -> bool:
        return (self._base / key).exists()

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        return f"/media/{key}"
