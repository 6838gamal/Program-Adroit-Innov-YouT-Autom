from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class PublishRequest(BaseModel):
    project_id: UUID
    account_id: UUID
    title: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    tags: list[str] = []
    privacy: str = "public"
    scheduled_at: Optional[datetime] = None
    export_job_id: Optional[UUID] = None


class ConnectAccountRequest(BaseModel):
    name: str
    platform_name: str
    credentials: dict


class PublishingJobResponse(BaseModel):
    id: UUID
    project_id: UUID
    account_id: UUID
    status: str
    platform_post_id: Optional[str]
    platform_url: Optional[str]
    error_message: Optional[str]
    retry_count: int
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class AccountResponse(BaseModel):
    id: UUID
    name: str
    platform_name: str
    is_active: bool
    last_verified: Optional[datetime]
    created_at: datetime
