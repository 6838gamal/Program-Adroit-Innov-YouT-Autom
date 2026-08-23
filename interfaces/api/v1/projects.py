from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, List, Dict, Any
import asyncio
import uuid
from datetime import datetime
import json

# إضافة استيراد BaseModel من pydantic
from pydantic import BaseModel

from application.services.project_service import ProjectService
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from interfaces.schemas.project_schemas import (
    CreateProjectRequest, UpdateProjectRequest,
    ProjectResponse, ProjectListResponse,
)
from shared.exceptions import ProjectNotFoundError

router = APIRouter(prefix="/projects", tags=["projects"])

# تخزين جلسات المعالجة
processing_sessions: Dict[str, Dict[str, Any]] = {}


def get_project_service(session: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(
        repo=SQLProjectRepository(session),
        event_bus=InMemoryEventBus(),
    )


# ============================================
# تعريف نماذج Pydantic للفيديو
# ============================================

class VideoProcessRequest(BaseModel):
    url: str
    session_id: Optional[str] = None


class VideoGenerateRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    links: Optional[List[str]] = []


# ============================================
# نقاط النهاية الأساسية
# ============================================

@router.get("", response_model=ProjectListResponse)
async def list_projects(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
):
    projects, total = await service.list_all(limit=limit, offset=offset, status=status, search=search)
    return ProjectListResponse(
        items=[ProjectResponse(**p.to_dict()) for p in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    service: ProjectService = Depends(get_project_service),
):
    project = await service.create(
        title=body.title,
        description=body.description,
        script=body.script,
        tags=body.tags,
        template_id=body.template_id,
        brand_colors=body.brand_colors.model_dump() if body.brand_colors else None,
    )
    return ProjectResponse(**project.to_dict())


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    try:
        project = await service.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**project.to_dict())


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: UpdateProjectRequest,
    service: ProjectService = Depends(get_project_service),
):
    try:
        project = await service.update(
            project_id=project_id,
            title=body.title,
            description=body.description,
            script=body.script,
            tags=body.tags,
            template_id=body.template_id,
            brand_colors=body.brand_colors.model_dump() if body.brand_colors else None,
            settings=body.settings,
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**project.to_dict())


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    try:
        await service.delete(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


# ============================================
# نقاط النهاية لمعالجة الفيديو مع دعم التقدم
# ============================================

@router.post("/video/process")
async def process_video(
    request: VideoProcessRequest,
    background_tasks: BackgroundTasks,
):
    """
    معالجة رابط فيديو من الإنترنت مع تحديث التقدم
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    # تهيئة حالة المعالجة مع معلومات مفصلة
    processing_sessions[session_id] = {
        "session_id": session_id,
        "status": "initializing",
        "progress": 0,
        "detail": "جاري تهيئة المعالجة...",
        "step": "تهيئة",
        "completed": False,
        "video_url": None,
        "title": None,
        "duration": None,
        "format": None,
        "size": None,
        "dimensions": None,
        "thumbnail": None,
        "error": None,
        "started_at": datetime.now().isoformat()
    }
    
    # بدء المعالجة في الخلفية
    background_tasks.add_task(process_video_background, session_id, request.url)
    
    return {
        "session_id": session_id,
        "status": "processing",
        "message": "جاري معالجة الفيديو..."
    }


@router.get("/video/process/{session_id}/status")
async def get_processing_status(session_id: str):
    """
    الحصول على حالة معالجة الفيديو مع التقدم
    """
    if session_id not in processing_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = processing_sessions[session_id]
    
    # بناء استجابة مفصلة
    return {
        "session_id": session_id,
        "status": session.get("status", "unknown"),
        "progress": session.get("progress", 0),
        "detail": session.get("detail", ""),
        "step": session.get("step", ""),
        "completed": session.get("completed", False),
        "video_url": session.get("video_url"),
        "title": session.get("title"),
        "duration": session.get("duration"),
        "format": session.get("format"),
        "size": session.get("size"),
        "dimensions": session.get("dimensions"),
        "thumbnail": session.get("thumbnail"),
        "error": session.get("error"),
        "started_at": session.get("started_at"),
        "updated_at": datetime.now().isoformat()
    }


@router.post("/video/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """
    توليد فيديو من برومبت مع تحديث التقدم
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    # تهيئة حالة التوليد
    processing_sessions[session_id] = {
        "session_id": session_id,
        "status": "initializing",
        "progress": 0,
        "detail": "جاري تهيئة التوليد...",
        "step": "تهيئة",
        "completed": False,
        "video_url": None,
        "title": None,
        "duration": None,
        "format": None,
        "size": None,
        "dimensions": None,
        "thumbnail": None,
        "error": None,
        "started_at": datetime.now().isoformat(),
        "prompt": request.prompt,
        "links": request.links or []
    }
    
    # بدء التوليد في الخلفية
    background_tasks.add_task(
        generate_video_background, 
        session_id, 
        request.prompt, 
        request.links or []
    )
    
    return {
        "session_id": session_id,
        "status": "generating",
        "message": "جاري توليد الفيديو..."
    }


@router.get("/video/generate/{session_id}/status")
async def get_generation_status(session_id: str):
    """
    الحصول على حالة توليد الفيديو مع التقدم
    """
    if session_id not in processing_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = processing_sessions[session_id]
    
    return {
        "session_id": session_id,
        "status": session.get("status", "unknown"),
        "progress": session.get("progress", 0),
        "detail": session.get("detail", ""),
        "step": session.get("step", ""),
        "completed": session.get("completed", False),
        "video_url": session.get("video_url"),
        "title": session.get("title"),
        "duration": session.get("duration"),
        "format": session.get("format"),
        "size": session.get("size"),
        "dimensions": session.get("dimensions"),
        "thumbnail": session.get("thumbnail"),
        "error": session.get("error"),
        "started_at": session.get("started_at"),
        "updated_at": datetime.now().isoformat()
    }


@router.get("/video/health")
async def video_health_check():
    """
    التحقق من صحة خدمة الفيديو
    """
    return {
        "status": "ok",
        "message": "Video processing service is running",
        "active_sessions": len(processing_sessions),
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# وظائف الخلفية مع تحديث التقدم
# ============================================

async def process_video_background(session_id: str, url: str):
    """
    معالجة الفيديو في الخلفية مع تحديث التقدم خطوة بخطوة
    """
    try:
        # خطوة 1: تحليل الرابط
        processing_sessions[session_id].update({
            "status": "analyzing",
            "progress": 10,
            "detail": "جاري تحليل الرابط...",
            "step": "تحليل الرابط"
        })
        await asyncio.sleep(1.5)
        
        # خطوة 2: استخراج معلومات الفيديو
        processing_sessions[session_id].update({
            "status": "extracting",
            "progress": 25,
            "detail": "جاري استخراج معلومات الفيديو...",
            "step": "استخراج المعلومات"
        })
        await asyncio.sleep(2)
        
        # محاكاة استخراج معلومات الفيديو
        video_info = {
            "title": f"فيديو مستورد - {datetime.now().strftime('%H:%M')}",
            "duration": 120,
            "format": "mp4",
            "size": "45.6 MB",
            "dimensions": "1920x1080"
        }
        
        # تحديث بمعلومات الفيديو
        processing_sessions[session_id].update({
            "title": video_info["title"],
            "duration": video_info["duration"],
            "format": video_info["format"],
            "size": video_info["size"],
            "dimensions": video_info["dimensions"]
        })
        
        # خطوة 3: تحميل الفيديو
        processing_sessions[session_id].update({
            "status": "downloading",
            "progress": 45,
            "detail": "جاري تحميل الفيديو...",
            "step": "تحميل الفيديو"
        })
        await asyncio.sleep(2)
        
        # خطوة 4: معالجة المحتوى
        processing_sessions[session_id].update({
            "status": "processing",
            "progress": 65,
            "detail": "جاري معالجة المحتوى...",
            "step": "معالجة المحتوى"
        })
        await asyncio.sleep(2)
        
        # خطوة 5: تحليل المشاهد
        processing_sessions[session_id].update({
            "status": "analyzing_content",
            "progress": 80,
            "detail": "جاري تحليل المشاهد...",
            "step": "تحليل المشاهد"
        })
        await asyncio.sleep(1.5)
        
        # خطوة 6: تجهيز الفيديو
        processing_sessions[session_id].update({
            "status": "finalizing",
            "progress": 95,
            "detail": "جاري تجهيز الفيديو...",
            "step": "تجهيز الفيديو"
        })
        await asyncio.sleep(1)
        
        # اكتمال المعالجة
        # استخدام فيديو تجريبي (في الواقع سيكون الفيديو المعالج)
        video_url = "https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4"
        
        processing_sessions[session_id].update({
            "status": "completed",
            "progress": 100,
            "detail": "اكتملت المعالجة!",
            "step": "اكتمل",
            "completed": True,
            "video_url": video_url,
            "title": video_info["title"],
            "duration": video_info["duration"],
            "format": video_info["format"],
            "size": video_info["size"],
            "dimensions": video_info["dimensions"]
        })
        
    except Exception as e:
        processing_sessions[session_id].update({
            "status": "failed",
            "progress": 0,
            "detail": f"فشل المعالجة: {str(e)}",
            "step": "فشل",
            "completed": True,
            "error": str(e)
        })


async def generate_video_background(session_id: str, prompt: str, links: List[str]):
    """
    توليد فيديو في الخلفية مع تحديث التقدم خطوة بخطوة
    """
    try:
        # خطوة 1: تحليل الطلب
        processing_sessions[session_id].update({
            "status": "analyzing_prompt",
            "progress": 5,
            "detail": "تحليل الطلب...",
            "step": "تحليل الطلب"
        })
        await asyncio.sleep(1.5)
        
        # خطوة 2: صياغة السكريبت
        processing_sessions[session_id].update({
            "status": "writing_script",
            "progress": 15,
            "detail": "صياغة النص السكريبت...",
            "step": "صياغة السكريبت"
        })
        await asyncio.sleep(2)
        
        # خطوة 3: توليد المشاهد
        processing_sessions[session_id].update({
            "status": "generating_scenes",
            "progress": 30,
            "detail": "توليد المشاهد...",
            "step": "توليد المشاهد"
        })
        await asyncio.sleep(2)
        
        # خطوة 4: معالجة الوسائط
        processing_sessions[session_id].update({
            "status": "processing_media",
            "progress": 50,
            "detail": "معالجة الصوت والصورة...",
            "step": "معالجة الوسائط"
        })
        await asyncio.sleep(2)
        
        # خطوة 5: تجميع الفيديو
        processing_sessions[session_id].update({
            "status": "compiling",
            "progress": 70,
            "detail": "تجميع الفيديو...",
            "step": "تجميع الفيديو"
        })
        await asyncio.sleep(2)
        
        # خطوة 6: تحسين الجودة
        processing_sessions[session_id].update({
            "status": "optimizing",
            "progress": 85,
            "detail": "تحسين الجودة...",
            "step": "تحسين الجودة"
        })
        await asyncio.sleep(1.5)
        
        # خطوة 7: تجهيز الفيديو
        processing_sessions[session_id].update({
            "status": "finalizing",
            "progress": 95,
            "detail": "تجهيز الفيديو...",
            "step": "تجهيز الفيديو"
        })
        await asyncio.sleep(1)
        
        # اكتمال التوليد
        # استخدام فيديو تجريبي (في الواقع سيكون فيديو مولد)
        video_url = "https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4"
        
        processing_sessions[session_id].update({
            "status": "completed",
            "progress": 100,
            "detail": "اكتمل التوليد!",
            "step": "اكتمل",
            "completed": True,
            "video_url": video_url,
            "title": prompt[:50] + ("..." if len(prompt) > 50 else ""),
            "duration": 180,
            "format": "mp4",
            "size": "68.2 MB",
            "dimensions": "1920x1080",
            "generated": True
        })
        
    except Exception as e:
        processing_sessions[session_id].update({
            "status": "failed",
            "progress": 0,
            "detail": f"فشل التوليد: {str(e)}",
            "step": "فشل",
            "completed": True,
            "error": str(e)
        })


# ============================================
# نقاط النهاية الإضافية للمشاريع
# ============================================

@router.post("/{project_id}/publish")
async def publish_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    نشر المشروع
    """
    try:
        project = await service.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        updated_project = await service.update(
            project_id=project_id,
            status="published"
        )
        
        return {
            "message": "Project published successfully",
            "project": ProjectResponse(**updated_project.to_dict())
        }
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/export")
async def export_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    تصدير المشروع كملف JSON
    """
    try:
        project = await service.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return {
            "project": project.to_dict(),
            "exported_at": datetime.now().isoformat()
        }
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/duplicate")
async def duplicate_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    نسخ مشروع موجود
    """
    try:
        original = await service.get(project_id)
        if not original:
            raise HTTPException(status_code=404, detail="Project not found")
        
        new_project = await service.create(
            title=f"{original.title} (نسخة)",
            description=original.description,
            script=original.script,
            tags=original.tags,
            template_id=original.template_id,
            brand_colors=original.brand_colors
        )
        
        return ProjectResponse(**new_project.to_dict())
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_id}/render")
async def render_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """
    بدء عملية الرندر
    """
    try:
        project = await service.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        updated_project = await service.update(
            project_id=project_id,
            status="in_production"
        )
        
        return {
            "message": "Render started successfully",
            "project": ProjectResponse(**updated_project.to_dict())
        }
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
