import uuid
from datetime import datetime
from typing import Any


class BaseEntity:
    """Base class for all domain entities."""

    def __init__(self, id: uuid.UUID | None = None):
        self.id: uuid.UUID = id or uuid.uuid4()
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()

    def _touch(self) -> None:
        self.updated_at = datetime.utcnow()

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BaseEntity):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"
