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
    ):
        super().__init__(id=id)
        self.name = name
        self.platform_name = platform_name
        self.credentials_encrypted = credentials_encrypted
        self.metadata: dict = metadata or {}
        self.is_active: bool = True
        self.last_verified: Optional[datetime] = None

    def verify(self) -> None:
        self.last_verified = datetime.utcnow()
        self._touch()

    def deactivate(self) -> None:
        self.is_active = False
        self._touch()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "platform_name": self.platform_name,
            "is_active": self.is_active,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
