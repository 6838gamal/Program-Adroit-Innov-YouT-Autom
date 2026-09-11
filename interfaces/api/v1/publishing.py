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
            }
        d.setdefault("platform_name", getattr(a, "platform_name", "—"))
        d.setdefault("is_verified", getattr(a, "is_active", True))
        d.setdefault("verified", getattr(a, "is_active", True))
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
    await session.commit()
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
    """فصل حساب (تعطيل)."""
    repo = SQLAccountRepository(session)
    account = await repo.get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        # deactivate بدلاً من الحذف الصلب
        account.deactivate()
        await repo.save(account)
        await session.commit()
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
    await session.commit()
    return PublishingJobResponse(**job.to_dict())


# ============================================
# Jobs
# ============================================

@router.get("/jobs", response_model=list[PublishingJobResponse])
async def list_publishing_jobs(session: AsyncSession = Depends(get_db)):
    repo = SQLPublishingJobRepository(session)
    jobs = await repo.list_recent(limit=50)
    return [PublishingJobResponse(**j.to_dict()) for j in jobs]


@router.get("/jobs/{job_id}", response_model=PublishingJobResponse)
async def get_publishing_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    repo = SQLPublishingJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")
    return PublishingJobResponse(**job.to_dict())


# ============================================
# ✅ Execute — تنفيذ مهمة نشر فوراً
# ============================================

@router.post("/jobs/{job_id}/execute")
async def execute_publishing_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """
    تنفيذ مهمة نشر فوراً عبر plugin المنصة.

    Flow:
    1. جلب المهمة والحساب من DB.
    2. جلب plugin المنصة من registry.
    3. تنزيل الفيديو من Supabase إلى ملف محلي.
    4. استدعاء plugin.upload() → YouTube API.
    5. تحديث حالة المهمة (published/failed).
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

    # بيانات الاعتماد
    try:
        credentials = json.loads(account.credentials_encrypted or "{}")
    except Exception:
        credentials = {}

    # تفاصيل النشر من metadata
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
        import tempfile
        import httpx

        # تنزيل الفيديو
        if video_url.startswith("http"):
            logger.info(f"[job {job_id}] Downloading video: {video_url}")
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            with httpx.Client(timeout=300.0, follow_redirects=True) as client:
                with client.stream("GET", video_url) as r:
                    r.raise_for_status()
                    for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                        tmp.write(chunk)
            tmp.close()
            video_path = Path(tmp.name)
            logger.info(f"[job {job_id}] Downloaded to {video_path}")
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
        # سجّل الفشل
        try:
            job.mark_failed(f"فشل تحضير المحتوى: {e}")
            await pub_repo.save(job)
            await session.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))

    # progress callback
    async def _progress(pct: float, stage: str):
        logger.info(f"[job {job_id}] {pct:.1f}% — {stage}")

    # شغّل الـ upload
    try:
        # علّم المهمة كـ uploading
        job.start()
        await pub_repo.save(job)
        await session.commit()

        logger.info(f"[job {job_id}] Starting upload to {account.platform_name}")
        result = await plugin.upload(content, credentials, _progress)

        if not result.success:
            job.mark_failed(result.error or "Upload failed")
            await pub_repo.save(job)
            await session.commit()
            raise HTTPException(status_code=500, detail=result.error or "Upload failed")

        job.mark_published(
            platform_post_id=result.platform_post_id or "",
            platform_url=result.platform_url or "",
        )
        await pub_repo.save(job)
        await session.commit()

        logger.info(f"[job {job_id}] ✅ Published: {result.platform_url}")

        return {
            "status": "success",
            "platform_post_id": result.platform_post_id,
            "platform_url": result.platform_url,
            "message": "تم النشر بنجاح",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[job {job_id}] Upload failed")
        try:
            job.mark_failed(str(e))
            await pub_repo.save(job)
            await session.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


# ============================================
# ✅ Cancel — إلغاء مهمة في الانتظار
# ============================================

@router.post("/jobs/{job_id}/cancel")
async def cancel_publishing_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """
    إلغاء مهمة نشر في الانتظار.

    مسموح فقط للمهام بحالة: pending, scheduled.
    """
    pub_repo = SQLPublishingJobRepository(session)
    job = await pub_repo.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    status_value = job.status.value if hasattr(job.status, "value") else str(job.status)

    if status_value not in ("pending", "scheduled"):
        raise HTTPException(
            status_code=400,
            detail=f"لا يمكن إلغاء مهمة بحالة '{status_value}' — فقط pending أو scheduled",
        )

    try:
        job.cancel()
        await pub_repo.save(job)
        await session.commit()

        logger.info(f"[job {job_id}] 🚫 Cancelled")
        return {
            "status": "success",
            "message": "تم إلغاء المهمة",
            "job_id": str(job_id),
        }
    except Exception as e:
        logger.exception(f"Cancel failed for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# ✅ Retry — إعادة محاولة مهمة فاشلة
# ============================================

@router.post("/jobs/{job_id}/retry")
async def retry_publishing_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """
    إعادة محاولة مهمة فاشلة.

    Flow: يُحدّث الحالة إلى pending ويُعيد التنفيذ.
    """
    pub_repo = SQLPublishingJobRepository(session)
    job = await pub_repo.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.can_retry:
        raise HTTPException(
            status_code=400,
            detail=f"لا يمكن إعادة المحاولة — status={job.status.value}, retry_count={job.retry_count}/{job.MAX_RETRIES}",
        )

    try:
        # جدول إعادة المحاولة (تلقائي)
        job.schedule_retry(delay_seconds=1)  # 1 ثانية للتنفيذ الفوري
        await pub_repo.save(job)
        await session.commit()

        logger.info(f"[job {job_id}] 🔄 Scheduled for retry ({job.retry_count})")
        return {
            "status": "success",
            "message": f"تم جدولة إعادة المحاولة ({job.retry_count}/{job.MAX_RETRIES})",
            "job_id": str(job_id),
        }
    except Exception as e:
        logger.exception(f"Retry failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
