from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class AssetResponse(BaseModel):
    id: UUID
    name: str
    type: str
    file_path: str
    file_size: int
    mime_type: str
    duration: Optional[float]
    width: Optional[int]
    height: Optional[int]
    tags: list[str]
    is_global: bool
    created_at: datetime


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    total: int
