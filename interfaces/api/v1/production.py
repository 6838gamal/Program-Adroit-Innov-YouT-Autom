from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Annotated, Optional, List, Dict, Any
import logging
from datetime import datetime

from application.services.production_service import ProductionService
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.repositories.sql_render_job_repository import SQLRenderJobRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from interfaces.schemas.production_schemas import (
    StartRenderRequest, 
    RenderJobResponse,
    RenderStatusResponse,
    CancelRenderResponse
)
from shared.exceptions import ProjectNotFoundError, RenderJobNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/production", tags=["production"])

# Shared event bus instance (module-level singleton for MVP)
_event_bus = InMemoryEventBus()


def get_production_service(
    session: AsyncSession = Depends(get_db),
) -> ProductionService:
    from interfaces.web.dependencies import get_plugin_registry_from_app
    from fastapi import Request
    # Import registry lazily to avoid circular imports
    from plugins.registry import PluginRegistry, PluginLoader
    from config.settings import settings

    registry = PluginRegistry()
    loader = PluginLoader()
    loader.load_all(settings.PLUGIN_CONFIG_PATH, registry)

    return ProductionService(
        project_repo=SQLProjectRepository(session),
        job_repo=SQLRenderJobRepository(session),
        event_bus=_event_bus,
        plugin_registry=registry,
    )


@router.post("/render", response_model=RenderJobResponse, status_code=202)
async def start_render(
    body: StartRenderRequest,
    service: ProductionService = Depends(get_production_service),
):
    """
    بدء عملية الرندر لمشروع معين
    
    يمكن للعميل إرسال:
    1. فقط project_id (لرندر مشروع موجود)
    2. project_id + بيانات المشروع الكاملة (لحفظ المشروع ثم رندره)
    
    Returns:
        RenderJobResponse: معلومات عن مهمة الرندر
    """
    try:
        # ====== 1. التحقق الأساسي ======
        if not body.project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        
        logger.info(f"📥 طلب رندر للمشروع: {body.project_id}")
        
        # ====== 2. حفظ بيانات المشروع إذا أرسلها العميل ======
        if body.clips is not None:
            try:
                logger.info(f"💾 حفظ بيانات المشروع {body.project_id} قبل الرندر")
                
                # تحويل البيانات إلى تنسيق مناسب للتخزين
                clips_data = []
                if body.clips:
                    for clip in body.clips:
                        clip_dict = clip.dict() if hasattr(clip, 'dict') else clip
                        clips_data.append(clip_dict)
                
                layers_data = []
                if body.layers:
                    for layer in body.layers:
                        layer_dict = layer.dict() if hasattr(layer, 'dict') else layer
                        layers_data.append(layer_dict)
                
                media_data = []
                if body.mediaFiles:
                    for media in body.mediaFiles:
                        media_dict = media.dict() if hasattr(media, 'dict') else media
                        media_data.append(media_dict)
                
                # حفظ البيانات في قاعدة البيانات
                await service.save_project_data(
                    project_id=body.project_id,
                    clips=clips_data,
                    layers=layers_data,
                    total_duration=body.duration or 10.0,
                    media_files=media_data
                )
                logger.info(f"✅ تم حفظ بيانات المشروع {body.project_id} بنجاح")
                
            except Exception as e:
                logger.warning(f"⚠️ فشل حفظ بيانات المشروع: {str(e)}")
        
        # ====== 3. تحويل data إلى dict للمشروع ======
        project_data = None
        if body.clips is not None or body.layers is not None:
            project_data = {
                "clips": [c.dict() if hasattr(c, 'dict') else c for c in (body.clips or [])],
                "layers": [l.dict() if hasattr(l, 'dict') else l for l in (body.layers or [])],
                "total_duration": body.duration or 10.0,
                "media_files": [m.dict() if hasattr(m, 'dict') else m for m in (body.mediaFiles or [])]
            }
        
        # ====== 4. بدء الرندر ======
        render_settings = {
            "fps": body.fps or 30,
            "width": body.width or 1920,
            "height": body.height or 1080,
            "quality": body.quality or "medium",
        }
        
        logger.info(f"🎬 بدء الرندر للمشروع {body.project_id} بالإعدادات: {render_settings}")
        
        job = await service.start_render(
            project_id=body.project_id,
            render_settings=render_settings,
            project_data=project_data,
        )
        
        logger.info(f"✅ تم إنشاء مهمة الرندر: {job.id} للمشروع {body.project_id}")
        
        # ====== 5. إرجاع النتيجة (متوافقة مع الواجهة الأمامية) ======
        return RenderJobResponse(
            job_id=job.id,  # ← استخدم job_id بدلاً من id
            project_id=job.project_id,
            renderer=getattr(job, 'renderer', 'default'),
            status=job.status.value if hasattr(job.status, 'value') else str(job.status),
            progress=job.progress or 0,
            current_stage=getattr(job, 'current_stage', ''),
            output_path=getattr(job, 'output_path', None),
            error_message=getattr(job, 'error_message', None),
            started_at=getattr(job, 'started_at', None),
            completed_at=getattr(job, 'completed_at', None),
            created_at=job.created_at,
            render_settings=getattr(job, 'settings', render_settings),
        )
        
    except ProjectNotFoundError as e:
        logger.error(f"❌ مشروع غير موجود: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Project not found: {str(e)}")
    
    except ValueError as e:
        logger.error(f"❌ خطأ في البيانات: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid data: {str(e)}")
    
    except Exception as e:
        logger.error(f"❌ فشل الرندر: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Render failed: {str(e)}")


@router.get("/jobs", response_model=list[RenderJobResponse])
async def list_render_jobs(
    service: ProductionService = Depends(get_production_service),
):
    """
    الحصول على قائمة بجميع مهام الرندر
    """
    try:
        jobs = await service.list_jobs()
        logger.info(f"📋 تم جلب {len(jobs)} مهمة رندر")
        
        return [
            RenderJobResponse(
                job_id=job.id,
                project_id=job.project_id,
                renderer=getattr(job, 'renderer', 'default'),
                status=job.status.value if hasattr(job.status, 'value') else str(job.status),
                progress=job.progress or 0,
                current_stage=getattr(job, 'current_stage', ''),
                output_path=getattr(job, 'output_path', None),
                error_message=getattr(job, 'error_message', None),
                started_at=getattr(job, 'started_at', None),
                completed_at=getattr(job, 'completed_at', None),
                created_at=job.created_at,
                render_settings=getattr(job, 'settings', {}),
            )
            for job in jobs
        ]
    except Exception as e:
        logger.error(f"❌ فشل جلب قائمة المهام: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


@router.get("/jobs/{job_id}", response_model=RenderJobResponse)
async def get_render_job(
    job_id: UUID,
    service: ProductionService = Depends(get_production_service),
):
    """
    الحصول على تفاصيل مهمة رندر محددة
    """
    try:
        job = await service.get_job(job_id)
        logger.info(f"📄 تم جلب تفاصيل المهمة: {job_id}")
        
        return RenderJobResponse(
            job_id=job.id,
            project_id=job.project_id,
            renderer=getattr(job, 'renderer', 'default'),
            status=job.status.value if hasattr(job.status, 'value') else str(job.status),
            progress=job.progress or 0,
            current_stage=getattr(job, 'current_stage', ''),
            output_path=getattr(job, 'output_path', None),
            error_message=getattr(job, 'error_message', None),
            started_at=getattr(job, 'started_at', None),
            completed_at=getattr(job, 'completed_at', None),
            created_at=job.created_at,
            render_settings=getattr(job, 'settings', {}),
        )
        
    except RenderJobNotFoundError as e:
        logger.warning(f"⚠️ مهمة غير موجودة: {job_id}")
        raise HTTPException(status_code=404, detail=f"Render job not found: {str(e)}")
    
    except Exception as e:
        logger.error(f"❌ فشل جلب المهمة {job_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get job: {str(e)}")


@router.get("/jobs/{job_id}/status", response_model=RenderStatusResponse)
async def get_render_status(
    job_id: UUID,
    service: ProductionService = Depends(get_production_service),
):
    """
    الحصول على حالة مهمة رندر محددة (نظام المراقبة)
    """
    try:
        job = await service.get_job(job_id)
        
        return RenderStatusResponse(
            job_id=str(job.id),
            project_id=str(job.project_id),
            status=job.status.value if hasattr(job.status, 'value') else str(job.status),
            progress=int(job.progress or 0),
            current_stage=getattr(job, 'current_stage', None),
            error=getattr(job, 'error_message', None),
            output_url=getattr(job, 'output_path', None),
            updated_at=datetime.utcnow().isoformat(),
        )
        
    except RenderJobNotFoundError:
        raise HTTPException(status_code=404, detail="Render job not found")
    
    except Exception as e:
        logger.error(f"❌ فشل جلب حالة المهمة {job_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.delete("/jobs/{job_id}", response_model=CancelRenderResponse, status_code=200)
async def cancel_render_job(
    job_id: UUID,
    service: ProductionService = Depends(get_production_service),
):
    """
    إلغاء مهمة رندر قيد التنفيذ
    """
    try:
        job = await service.get_job(job_id)
        
        current_status = job.status.value if hasattr(job.status, 'value') else str(job.status)
        if current_status not in ["pending", "processing"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot cancel job with status: {current_status}"
            )
        
        await service.cancel_job(job_id)
        logger.info(f"🛑 تم إلغاء المهمة: {job_id}")
        
        return CancelRenderResponse(
            job_id=str(job_id),
            status="cancelled",
            message="Render job cancelled successfully"
        )
        
    except RenderJobNotFoundError as e:
        logger.warning(f"⚠️ مهمة غير موجودة للإلغاء: {job_id}")
        raise HTTPException(status_code=404, detail=f"Render job not found: {str(e)}")
    
    except Exception as e:
        logger.error(f"❌ فشل إلغاء المهمة {job_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")
