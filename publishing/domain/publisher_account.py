import uuid
from datetime import datetime
from typing import Optional

from shared.base_entity import BaseEntity


class PublisherAccount(BaseEntity):
    """An authenticated account on a publishing platform."""

    def __init__(
        self,
        name: str,
        platform_name: str,
        credentials_encrypted: str,
        metadata: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
        # ── Channel metadata (new) ──────────────────────────────────────────
        channel_id: str = "",
        channel_title: str = "",
        channel_handle: str = "",
        channel_thumbnail: str = "",
    ):
        super().__init__(id=id)
        self.name = name
        self.platform_name = platform_name
        self.credentials_encrypted = credentials_encrypted
        self.metadata: dict = metadata or {}

        # ── Channel metadata ────────────────────────────────────────────────
        self.channel_id: str = channel_id or ""
        self.channel_title: str = channel_title or ""
        self.channel_handle: str = channel_handle or ""
        self.channel_thumbnail: str = channel_thumbnail or ""

        # ── Lifecycle ───────────────────────────────────────────────────────
        self.is_active: bool = True
        self.last_verified: Optional[datetime] = None

    # ── Lifecycle methods ───────────────────────────────────────────────────

    def verify(self) -> None:
        self.last_verified = datetime.utcnow()
        self._touch()

    def deactivate(self) -> None:
        self.is_active = False
        self._touch()

    # ── Convenience properties ──────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """Best available name for UI display."""
        return self.channel_title or self.name or self.platform_name

    @property
    def identifier(self) -> str:
        """Best available unique identifier for UI."""
        return self.channel_handle or self.channel_id or str(self.id)

    # ── Serialization ───────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "platform_name": self.platform_name,

            # Channel metadata (new)
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "channel_handle": self.channel_handle,
            "channel_thumbnail": self.channel_thumbnail,

            # Lifecycle
            "is_active": self.is_active,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,

            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
