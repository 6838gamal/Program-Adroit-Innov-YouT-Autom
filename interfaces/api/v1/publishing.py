import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from publishing.domain.publisher_account import PublisherAccount
from publishing.domain.publishing_job import PublishingJob
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_publishing_repository import (
    SQLPublishingJobRepository, SQLAccountRepository,
)
from interfaces.schemas.publishing_schemas import (
    PublishRequest, ConnectAccountRequest,
    PublishingJobResponse, AccountResponse,
)

router = APIRouter(prefix="/publishing", tags=["publishing"])


def get_repos(session: AsyncSession = Depends(get_db)):
    return SQLPublishingJobRepository(session), SQLAccountRepository(session)


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(session: AsyncSession = Depends(get_db)):
    repo = SQLAccountRepository(session)
    accounts = await repo.list_all()
    return [AccountResponse(**a.to_dict()) for a in accounts]


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def connect_account(
    body: ConnectAccountRequest,
    session: AsyncSession = Depends(get_db),
):
    from plugins.registry import PluginRegistry, PluginLoader
    from config.settings import settings as app_settings
    registry = PluginRegistry()
    PluginLoader().load_all(app_settings.PLUGIN_CONFIG_PATH, registry)

    try:
        plugin = registry.get_publisher(body.platform_name)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {body.platform_name}")

    auth = await plugin.authenticate(body.credentials)
    if not auth.success:
        raise HTTPException(status_code=401, detail=auth.error or "Authentication failed")

    account = PublisherAccount(
        name=body.name,
        platform_name=body.platform_name,
        credentials_encrypted=json.dumps(body.credentials),  # TODO: encrypt in Phase 2
    )
    account.verify()

    repo = SQLAccountRepository(session)
    await repo.save(account)
    return AccountResponse(**account.to_dict())


@router.post("/publish", response_model=PublishingJobResponse, status_code=202)
async def publish_content(
    body: PublishRequest,
    session: AsyncSession = Depends(get_db),
):
    job = PublishingJob(
        project_id=body.project_id,
        account_id=body.account_id,
        export_job_id=body.export_job_id,
        metadata={
            "title": body.title,
            "description": body.description,
            "tags": body.tags,
            "privacy": body.privacy,
        },
        scheduled_at=body.scheduled_at,
    )
    repo = SQLPublishingJobRepository(session)
    await repo.save(job)
    return PublishingJobResponse(**job.to_dict())


@router.get("/jobs", response_model=list[PublishingJobResponse])
async def list_publishing_jobs(session: AsyncSession = Depends(get_db)):
    repo = SQLPublishingJobRepository(session)
    jobs = await repo.list_recent(limit=20)
    return [PublishingJobResponse(**j.to_dict()) for j in jobs]


@router.get("/jobs/{job_id}", response_model=PublishingJobResponse)
async def get_publishing_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    repo = SQLPublishingJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")
    return PublishingJobResponse(**job.to_dict())


@router.get("/platforms")
async def list_platforms():
    from plugins.registry import PluginRegistry, PluginLoader
    from config.settings import settings as app_settings
    registry = PluginRegistry()
    PluginLoader().load_all(app_settings.PLUGIN_CONFIG_PATH, registry)
    publishers = registry.list_publishers()
    return [
        {
            "name": p.platform_name,
            "display_name": p.get_platform_profile().display_name,
            "profile": {
                "max_duration": p.get_platform_profile().max_duration,
                "supported_formats": p.get_platform_profile().supported_formats,
                "supports_scheduling": p.get_platform_profile().supports_scheduling,
            }
        }
        for p in publishers
    ]
