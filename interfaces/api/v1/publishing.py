import json
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publishing", tags=["publishing"])


def get_repos(session: AsyncSession = Depends(get_db)):
    return SQLPublishingJobRepository(session), SQLAccountRepository(session)


# ============================================
# Accounts
# ============================================

@router.get("/accounts")
async def list_accounts(session: AsyncSession = Depends(get_db)):
    """
    قائمة الحسابات المتصلة.

    يُرجع: {"status": "success", "count": N, "items": [...]}
    """
    repo = SQLAccountRepository(session)
    accounts = await repo.list_all()

    items = []
    for a in accounts:
        try:
            d = a.to_dict()
        except Exception:
            d = {
                "id": str(a.id),
                "name": getattr(a, "name", "—"),
                "platform_name": getattr(a, "platform_name", "—"),
                "is_verified": getattr(a, "is_verified", True),
                "verified": getattr(a, "verified", True),
            }

        # ضمان وجود حقول يستخدمها الـ frontend
        d.setdefault("platform_name", getattr(a, "platform_name", "—"))
        d.setdefault("is_verified", getattr(a, "is_verified", True))
        d.setdefault("verified", getattr(a, "verified", True))

        items.append(d)

    return {
        "status": "success",
        "count": len(items),
        "items": items,
    }


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
        credentials_encrypted=json.dumps(body.credentials),
    )
    account.verify()

    repo = SQLAccountRepository(session)
    await repo.save(account)
    return AccountResponse(**account.to_dict())


@router.get("/accounts/{account_id}")
async def get_account(account_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    """جلب حساب واحد بالتفصيل."""
    repo = SQLAccountRepository(session)
    account = await repo.get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        d = account.to_dict()
    except Exception:
        d = {
            "id": str(account.id),
            "name": getattr(account, "name", "—"),
            "platform_name": getattr(account, "platform_name", "—"),
        }

    return {"status": "success", "data": d}


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    """حذف (فصل) حساب."""
    repo = SQLAccountRepository(session)
    account = await repo.get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # محاولة الحذف الناعم أو الصلب
    try:
        if hasattr(repo, "soft_delete"):
            await repo.soft_delete(account_id)
        elif hasattr(repo, "delete"):
            await repo.delete(account_id)
    except Exception as e:
        logger.exception(f"Failed to delete account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Publish (single job)
# ============================================

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


# ============================================
# Jobs
# ============================================

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


@router.post("/jobs/{job_id}/execute")
async def execute_publishing_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """
    تنفيذ مهمة نشر (اختياري - إن لم يوجد worker تلقائي).

    هذه النقطة تُشغّل الـ upload فوراً عبر plugin المنصة.
    """
    pub_repo = SQLPublishingJobRepository(session)
    acc_repo = SQLAccountRepository(session)

    job = await pub_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    account = await acc_repo.get(job.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # جلب plugin المنصة
    from plugins.registry import PluginRegistry, PluginLoader
    from config.settings import settings as app_settings

    registry = PluginRegistry()
    PluginLoader().load_all(app_settings.PLUGIN_CONFIG_PATH, registry)

    try:
        plugin = registry.get_publisher(account.platform_name)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {account.platform_name}")

    # استخرج بيانات الاعتماد
    try:
        credentials = json.loads(account.credentials_encrypted or "{}")
    except Exception:
        credentials = {}

    # استخرج بيانات النشر من metadata
    metadata = getattr(job, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    video_url = metadata.get("video_url")
    if not video_url:
        raise HTTPException(status_code=400, detail="metadata.video_url missing")

    # جهّز PublishableContent
    try:
        from shared.ports.publisher_port import PublishableContent
        from pathlib import Path

        # تنزيل الفيديو إلى ملف محلي إن كان URL
        video_path = None
        if video_url.startswith("http"):
            import httpx
            import tempfile

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                r = client.get(video_url)
                r.raise_for_status()
                tmp.write(r.content)
            tmp.close()
            video_path = Path(tmp.name)
        else:
            video_path = Path(video_url)

        content = PublishableContent(
            video_path=video_path,
            title=metadata.get("title", "فيديو"),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            privacy=metadata.get("privacy", "public"),
        )
    except Exception as e:
        logger.exception("Failed to prepare PublishableContent")
        raise HTTPException(status_code=500, detail=str(e))

    # شغّل الـ upload
    async def _progress(pct: float, stage: str):
        logger.info(f"[job {job_id}] {pct:.1f}% — {stage}")

    try:
        result = await plugin.upload(content, credentials, _progress)
    except Exception as e:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Upload failed")

    return {
        "status": "success",
        "platform_post_id": result.platform_post_id,
        "platform_url": result.platform_url,
    }


# ============================================
# Platforms
# ============================================

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
            },
        }
        for p in publishers
    ]
