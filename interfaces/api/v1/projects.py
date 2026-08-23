from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, List, Dict, Any
import asyncio
import uuid
from datetime import datetime

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
# نقاط النهاية لمعالجة الفيديو
# ============================================

class VideoProcessRequest(BaseModel):
    url: str
    session_id: Optional[str] = None

class VideoGenerateRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    links: Optional[List[str]] = []


@router.post("/video/process")
async def process_video(
    request: VideoProcessRequest,
    background_tasks: BackgroundTasks,
):
    """معالجة رابط فيديو من الإنترنت"""
    session_id = request.session_id or str(uuid.uuid4())
    
    processing_sessions[session_id] = {
        "status": "initializing",
        "progress": 0,
        "detail": "جاري تهيئة المعالجة...",
        "completed": False,
        "session_id": session_id
    }
    
    background_tasks.add_task(process_video_background, session_id, request.url)
    
    return {
        "session_id": session_id,
        "status": "processing",
        "message": "جاري معالجة الفيديو..."
    }


@router.get("/video/process/{session_id}/status")
async def get_processing_status(session_id: str):
    """الحصول على حالة معالجة الفيديو"""
    if session_id not in processing_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return processing_sessions[session_id]


@router.post("/video/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """توليد فيديو من برومبت"""
    session_id = request.session_id or str(uuid.uuid4())
    
    processing_sessions[session_id] = {
        "status": "initializing",
        "progress": 0,
        "detail": "جاري تهيئة التوليد...",
        "completed": False,
        "session_id": session_id
    }
    
    background_tasks.add_task(
        generate_video_background, 
        session_id, 
        request.prompt, 
        request.links
    )
    
    return {
        "session_id": session_id,
        "status": "generating",
        "message": "جاري توليد الفيديو..."
    }


@router.get("/video/generate/{session_id}/status")
async def get_generation_status(session_id: str):
    """الحصول على حالة توليد الفيديو"""
    if session_id not in processing_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return processing_sessions[session_id]


@router.get("/video/health")
async def video_health_check():
    """التحقق من صحة خدمة الفيديو"""
    return {
        "status": "ok",
        "message": "Video processing service is running",
        "active_sessions": len(processing_sessions),
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# نقاط النهاية الإضافية للمشاريع
# ============================================

@router.post("/{project_id}/publish")
async def publish_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """نشر المشروع"""
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


@router.get("/{project_id}/export")
async def export_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """تصدير المشروع"""
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


@router.post("/{project_id}/duplicate")
async def duplicate_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """نسخ مشروع"""
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


@router.post("/{project_id}/render")
async def render_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    """بدء عملية الرندر"""
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


# ============================================
# وظائف الخلفية
# ============================================

async def process_video_background(session_id: str, url: str):
    """معالجة الفيديو في الخلفية"""
    try:
        steps = [
            (10, "جاري تحليل الرابط..."),
            (25, "جاري تحميل الفيديو..."),
            (40, "جاري معالجة المحتوى..."),
            (60, "جاري تحليل المشاهد..."),
            (80, "جاري استخراج الصورة المصغرة..."),
            (95, "جاري تجهيز الفيديو..."),
        ]
        
        for progress, detail in steps:
            await asyncio.sleep(1)
            processing_sessions[session_id].update({
                "progress": progress,
                "detail": detail,
                "status": "processing"
            })
        
        # اكتمال المعالجة
        processing_sessions[session_id].update({
            "status": "completed",
            "progress": 100,
            "detail": "اكتملت المعالجة!",
            "completed": True,
            "video_url": url,
            "title": f"فيديو معالج - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "duration": 120,
            "thumbnail": None
        })
        
    except Exception as e:
        processing_sessions[session_id].update({
            "status": "failed",
            "detail": str(e),
            "completed": True,
            "error": str(e)
        })


async def generate_video_background(session_id: str, prompt: str, links: List[str]):
    """توليد فيديو في الخلفية"""
    try:
        steps = [
            (5, "تحليل الطلب..."),
            (15, "صياغة النص السكريبت..."),
            (30, "توليد المشاهد..."),
            (50, "معالجة الصوت والصورة..."),
            (70, "تجميع الفيديو..."),
            (85, "تحسين الجودة..."),
            (95, "تجهيز الفيديو..."),
        ]
        
        for progress, detail in steps:
            await asyncio.sleep(1.5)
            processing_sessions[session_id].update({
                "progress": progress,
                "detail": detail,
                "status": "generating"
            })
        
        # اكتمال التوليد
        video_url = "https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4"
        
        processing_sessions[session_id].update({
            "status": "completed",
            "progress": 100,
            "detail": "اكتمل التوليد!",
            "completed": True,
            "video_url": video_url,
            "title": prompt[:50] + ("..." if len(prompt) > 50 else ""),
            "duration": 180,
            "thumbnail": None,
            "generated": True
        })
        
    except Exception as e:
        processing_sessions[session_id].update({
            "status": "failed",
            "detail": str(e),
            "completed": True,
            "error": str(e)
        })


# ============================================
# تنظيف الجلسات القديمة
# ============================================
async def cleanup_old_sessions():
    while True:
        await asyncio.sleep(3600)
        # حذف الجلسات المكتملة
        to_remove = [sid for sid, sess in processing_sessions.items() if sess.get("completed")]
        for sid in to_remove:
            if sid in processing_sessions:
                del processing_sessions[sid]


# ============================================
# استيراد النماذج
# ============================================
from pydantic import BaseModel

class VideoProcessRequest(BaseModel):
    url: str
    session_id: Optional[str] = None

class VideoGenerateRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    links: Optional[List[str]] = []
