from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class StartRenderRequest(BaseModel):
    project_id: UUID
    fps: int = 30
    width: int = 1920
    height: int = 1080
    quality: str = "high"


class RenderJobResponse(BaseModel):
    id: UUID
    project_id: UUID
    renderer: str
    status: str
    progress: float
    current_stage: str
    output_path: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class ExportRequest(BaseModel):
    render_job_id: UUID
    format: str = "mp4"
    aspect_ratio: str = "16:9"
    width: int = 1920
    height: int = 1080
