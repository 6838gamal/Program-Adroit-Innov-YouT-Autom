from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class BrandColorsSchema(BaseModel):
    primary: str = "#3B82F6"
    secondary: str = "#1E40AF"
    accent: str = "#F59E0B"
    text: str = "#FFFFFF"
    background: str = "#000000"


class CreateProjectRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    script: str = ""
    tags: list[str] = []
    template_id: Optional[UUID] = None
    brand_colors: Optional[BrandColorsSchema] = None


class UpdateProjectRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    script: Optional[str] = None
    tags: Optional[list[str]] = None
    template_id: Optional[UUID] = None
    brand_colors: Optional[BrandColorsSchema] = None
    settings: Optional[dict] = None


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    description: str
    script: str
    tags: list[str]
    status: str
    template_id: Optional[UUID]
    logo_asset_id: Optional[UUID]
    brand_colors: dict
    settings: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    limit: int
    offset: int
