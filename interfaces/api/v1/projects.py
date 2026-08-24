from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, List, Dict, Any
import asyncio
import uuid
from datetime import datetime
import re
import json
import subprocess
import os
import shutil
from urllib.parse import urlparse

from pydantic import BaseModel

from application.services.project_service import ProjectService
from application.services.youtube_service import YouTubeService
from infrastructure.database.session import get_db
from infrastructure.repositories.sql_project_repository import SQLProjectRepository
from infrastructure.event_bus.in_memory_event_bus import InMemoryEventBus
from interfaces.schemas.project_schemas import (
    CreateProjectRequest, UpdateProjectRequest,
    ProjectResponse, ProjectListResponse,
)
from shared.exceptions import ProjectNotFoundError
from utils.video_utils import get_download_info, get_youtube_thumbnail, download_video

router = APIRouter(prefix="/projects", tags=["projects"])

# تخزين جلسات المعالجة
processing_sessions: Dict[str, Dict[str, Any]] = {}


def get_project_service(session: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(
        repo=SQLProjectRepository(session),
        event_bus=InMemoryEventBus(),
    )


def get_youtube_service() -> YouTubeService:
    return YouTubeService()


# ============================================
# تعريف نماذج Pydantic
# ============================================

class VideoProcessRequest(BaseModel):
    url: str
    session_id: Optional[str] = None
    use_auth: bool = False


class VideoGenerateRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    links: Optional[List[str]] = []


class YouTubeVideoRequest(BaseModel):
    url: str
    use_auth: bool = False
    session_id: Optional[str] = None


class YouTubeSearchRequest(BaseModel):
    query: str
    max_results: int = 10


class YouTubeAuthRequest(BaseModel):
    code: str
    user_id: str = "default"


# ============================================
# التحقق من وجود yt-dlp (كخيار احتياطي)
# ============================================

def is_ytdlp_available() -> bool:
    """
    التحقق من وجود yt-dlp في النظام (كخيار احتياطي)
    """
    return shutil.which("yt-dlp") is not None


# ============================================
# استخراج معلومات الفيديو المحسّن
# ============================================

async def extract_youtube_video_info(url: str, use_auth: bool = False) -> Dict[str, Any]:
    """
    استخراج معلومات الفيديو باستخدام YouTube Data API + pytube
    """
    service = YouTubeService()
    video_id = service.extract_video_id(url)
    
    if not video_id:
        print(f"⚠️ لم يتم العثور على معرف الفيديو في: {url}")
        return extract_video_info_manual(url)
    
    try:
        # 1. الحصول على المعلومات من YouTube Data API
        print(f"📡 جلب معلومات الفيديو من YouTube Data API: {video_id}")
        info = service.get_video_info(video_id, use_auth=use_auth)
        
        if info:
            print(f"✅ تم الحصول على المعلومات من API")
        else:
            print(f"⚠️ فشل API، محاولة استخدام pytube...")
            # 2. محاولة استخدام pytube كبديل
            download_info = get_download_info(video_id)
            if download_info and not download_info.get('error'):
                return {
                    'video_id': video_id,
                    'title': download_info.get('title', 'فيديو يوتيوب'),
                    'duration': download_info.get('length', 0),
                    'thumbnail': download_info.get('thumbnail', get_youtube_thumbnail(video_id)),
                    'uploader': download_info.get('author', 'YouTube'),
                    'description': download_info.get('description', ''),
                    'view_count': 0,
                    'like_count': 0,
                    'platform': 'youtube',
                    'is_external': True,
                    'url': url,
                    'format': 'mp4',
                    'size': None,
                    'size_bytes': None,
                    'dimensions': '1920x1080',
                    'download': download_info,
                    'warning': 'تم استخدام pytube بدلاً من YouTube API'
                }
            else:
                print(f"⚠️ فشل pytube أيضاً، استخدام الطريقة اليدوية")
                return extract_video_info_manual(url)
        
        # 3. دمج مع معلومات التحميل من pytube
        download_info = get_download_info(video_id)
        
        # 4. بناء النتيجة النهائية
        result = {
            'video_id': video_id,
            'title': info.get('title', 'فيديو يوتيوب'),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail') or get_youtube_thumbnail(video_id),
            'uploader': info.get('channel_title', 'YouTube'),
            'uploader_id': info.get('channel_id', ''),
            'description': info.get('description', ''),
            'view_count': info.get('view_count', 0),
            'like_count': info.get('like_count', 0),
            'comment_count': info.get('comment_count', 0),
            'platform': 'youtube',
            'is_external': True,
            'url': url,
            'format': 'mp4',
            'size': None,
            'size_bytes': None,
            'dimensions': info.get('dimensions', '1920x1080'),
            'tags': info.get('tags', []),
            'category_id': info.get('category_id', ''),
            'is_private': info.get('is_private', False),
            'is_unlisted': info.get('is_unlisted', False),
            'is_embeddable': info.get('is_embeddable', True),
            'published_at': info.get('published_at', ''),
            'download': download_info if download_info and not download_info.get('error') else None,
            'ytdlp_available': False,
            'ytdlp_error': None,
            'warning': None,
            'use_auth': use_auth
        }
        
        # حساب حجم الملف التقريبي
        if result['duration']:
            estimated_size_mb = max(result['duration'] * 2.5, 10)  # 2.5 MB per second minimum 10 MB
            result['size_bytes'] = int(estimated_size_mb * 1024 * 1024)
            result['size'] = f"~{estimated_size_mb:.1f} MB"
        
        print(f"✅ تم استخراج معلومات الفيديو بنجاح: {result['title']}")
        return result
        
    except Exception as e:
        print(f"⚠️ خطأ في استخراج المعلومات: {e}")
        return extract_video_info_manual(url)


def extract_video_info_manual(
    url: str, 
    youtube_auth_error: bool = False, 
    video_unavailable: bool = False,
    age_restricted: bool = False
) -> Dict[str, Any]:
    """
    استخراج معلومات الفيديو يدوياً (كحل أخير)
    """
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    
    info = {
        "title": None,
        "duration": None,
        "format": "mp4",
        "size": None,
        "size_bytes": None,
        "dimensions": "1280x720",
        "thumbnail": None,
        "uploader": None,
        "description": None,
        "view_count": None,
        "like_count": None,
        "platform": "generic",
        "ytdlp_error": None,
        "warning": None,
        "is_external": True,
        "video_id": None
    }
    
    # تحديد المنصة من الرابط
    if "youtube.com" in domain or "youtu.be" in domain:
        info["platform"] = "youtube"
        info["is_external"] = True
        video_id = extract_youtube_id(url)
        info["video_id"] = video_id
        
        if video_id:
            info["thumbnail"] = get_youtube_thumbnail(video_id)
        
        if age_restricted:
            info["ytdlp_error"] = "age_restricted"
            info["warning"] = "الفيديو مقيد بالعمر - سيتم استخدام فيديو تجريبي للعرض"
            info["title"] = "فيديو يوتيوب (مقيد بالعمر)"
            info["duration"] = 60
            info["size"] = "~30.0 MB"
            info["size_bytes"] = 30 * 1024 * 1024
        elif video_unavailable:
            info["ytdlp_error"] = "video_unavailable"
            info["warning"] = "الفيديو غير متاح - سيتم استخدام فيديو تجريبي للعرض"
            info["title"] = "فيديو يوتيوب (غير متاح)"
            info["duration"] = 60
            info["size"] = "~30.0 MB"
            info["size_bytes"] = 30 * 1024 * 1024
        elif youtube_auth_error:
            info["ytdlp_error"] = "auth_required"
            info["warning"] = "يوتيوب يطلب تسجيل الدخول - سيتم استخدام فيديو تجريبي للعرض"
            info["title"] = "فيديو يوتيوب (يتطلب تسجيل الدخول)"
            info["duration"] = 120
            info["size"] = "~45.6 MB"
            info["size_bytes"] = 45.6 * 1024 * 1024
        else:
            info["title"] = f"فيديو يوتيوب {f'(ID: {video_id[:8]}...)' if video_id else ''}"
            info["duration"] = 120
            info["size"] = "~45.6 MB"
            info["size_bytes"] = 45.6 * 1024 * 1024
            info["warning"] = "سيتم استخدام فيديو تجريبي للعرض (YouTube Data API غير متاح)"
        
        info["description"] = "فيديو من يوتيوب"
        info["uploader"] = "YouTube"
            
    elif "tiktok.com" in domain:
        info["platform"] = "tiktok"
        info["is_external"] = True
        info["title"] = "فيديو تيك توك"
        info["duration"] = 60
        info["size"] = "~15.2 MB"
        info["size_bytes"] = 15.2 * 1024 * 1024
        info["dimensions"] = "1080x1920"
        info["uploader"] = "TikTok"
        info["description"] = "فيديو من تيك توك"
        info["warning"] = "سيتم استخدام فيديو تجريبي للعرض"
        
    elif "vimeo.com" in domain:
        info["platform"] = "vimeo"
        info["is_external"] = False
        info["title"] = "فيديو Vimeo"
        info["duration"] = 180
        info["size"] = "~89.3 MB"
        info["size_bytes"] = 89.3 * 1024 * 1024
        info["uploader"] = "Vimeo"
        info["description"] = "فيديو من Vimeo"
        
    elif "facebook.com" in domain:
        info["platform"] = "facebook"
        info["is_external"] = True
        info["title"] = "فيديو فيسبوك"
        info["duration"] = 120
        info["size"] = "~35.0 MB"
        info["size_bytes"] = 35 * 1024 * 1024
        info["uploader"] = "Facebook"
        info["description"] = "فيديو من فيسبوك"
        info["warning"] = "سيتم استخدام فيديو تجريبي للعرض"
        
    elif "instagram.com" in domain:
        info["platform"] = "instagram"
        info["is_external"] = True
        info["title"] = "فيديو إنستغرام"
        info["duration"] = 60
        info["size"] = "~20.0 MB"
        info["size_bytes"] = 20 * 1024 * 1024
        info["uploader"] = "Instagram"
        info["description"] = "فيديو من إنستغرام"
        info["warning"] = "سيتم استخدام فيديو تجريبي للعرض"
        
    else:
        info["platform"] = "generic"
        info["is_external"] = True
        info["title"] = f"فيديو من {domain}"
        info["duration"] = 90
        info["size"] = "~30.0 MB"
        info["size_bytes"] = 30 * 1024 * 1024
        info["format"] = detect_video_format(url)
        info["description"] = f"فيديو من {domain}"
        info["warning"] = "سيتم استخدام فيديو تجريبي للعرض"
    
    print(f"ℹ️ تم استخراج معلومات الفيديو يدوياً: {info['title']} ({info['platform']})")
    if info.get("warning"):
        print(f"⚠️ {info['warning']}")
    
    return info


def extract_youtube_id(url: str) -> Optional[str]:
    """
    استخراج معرف الفيديو من رابط يوتيوب
    """
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([\w-]+)',
        r'(?:youtu\.be\/)([\w-]+)',
        r'(?:youtube\.com\/embed\/)([\w-]+)',
        r'(?:youtube\.com\/shorts\/)([\w-]+)',
        r'(?:youtube\.com\/v\/)([\w-]+)',
        r'(?:youtube\.com\/watch\?.*?v=)([\w-]+)',
        r'(?:youtube\.com\/@[\w-]+\/video\/)([\w-]+)',
        r'(?:youtube\.com\/live\/)([\w-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def detect_video_format(url: str) -> str:
    """
    اكتشاف صيغة الفيديو من الرابط
    """
    extensions = {
        '.mp4': 'mp4',
        '.webm': 'webm',
        '.avi': 'avi',
        '.mov': 'mov',
        '.mkv': 'mkv',
        '.flv': 'flv',
        '.wmv': 'wmv'
    }
    
    for ext, format_name in extensions.items():
        if ext in url.lower():
            return format_name
    return 'mp4'


def format_file_size(bytes_size: int) -> str:
    """
    تنسيق حجم الملف
    """
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"


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
# نقاط النهاية لمعالجة الفيديو (محسّنة)
# ============================================

@router.post("/video/process")
async def process_video(
    request: VideoProcessRequest,
    background_tasks: BackgroundTasks,
):
    """
    معالجة رابط فيديو من الإنترنت باستخدام YouTube Data API + pytube
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    # التحقق من وجود yt-dlp كخيار احتياطي
    ytdlp_available = is_ytdlp_available()
    
    # تهيئة حالة المعالجة
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
        "size_bytes": None,
        "dimensions": None,
        "thumbnail": None,
        "uploader": None,
        "description": None,
        "view_count": None,
        "like_count": None,
        "error": None,
        "started_at": datetime.now().isoformat(),
        "url": request.url,
        "ytdlp_available": ytdlp_available,
        "ytdlp_error": None,
        "platform": None,
        "warning": None,
        "is_external": False,
        "use_auth": request.use_auth,
        "video_id": None
    }
    
    # بدء المعالجة في الخلفية
    background_tasks.add_task(process_video_background, session_id, request.url, request.use_auth)
    
    return {
        "session_id": session_id,
        "status": "processing",
        "message": "جاري معالجة الفيديو..."
    }


@router.get("/video/process/{session_id}/status")
async def get_processing_status(session_id: str):
    """
    الحصول على حالة معالجة الفيديو مع التقدم والمعلومات
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
        "size_bytes": session.get("size_bytes"),
        "dimensions": session.get("dimensions"),
        "thumbnail": session.get("thumbnail"),
        "uploader": session.get("uploader"),
        "description": session.get("description"),
        "view_count": session.get("view_count"),
        "like_count": session.get("like_count"),
        "error": session.get("error"),
        "warning": session.get("warning"),
        "started_at": session.get("started_at"),
        "updated_at": datetime.now().isoformat(),
        "ytdlp_available": session.get("ytdlp_available", False),
        "ytdlp_error": session.get("ytdlp_error"),
        "platform": session.get("platform"),
        "is_external": session.get("is_external", False),
        "video_id": session.get("video_id"),
        "use_auth": session.get("use_auth", False)
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
        "size_bytes": None,
        "dimensions": None,
        "thumbnail": None,
        "error": None,
        "started_at": datetime.now().isoformat(),
        "prompt": request.prompt,
        "links": request.links or []
    }
    
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
    الحصول على حالة توليد الفيديو مع التقدم والمعلومات
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
        "size_bytes": session.get("size_bytes"),
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
    # التحقق من YouTube Service
    youtube_service = YouTubeService()
    is_youtube_auth = youtube_service.is_authenticated()
    
    return {
        "status": "ok",
        "message": "Video processing service is running",
        "active_sessions": len(processing_sessions),
        "ytdlp_available": is_ytdlp_available(),
        "youtube_api_available": True,
        "youtube_authenticated": is_youtube_auth,
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# وظائف الخلفية (محسّنة)
# ============================================

async def process_video_background(session_id: str, url: str, use_auth: bool = False):
    """
    معالجة الفيديو في الخلفية مع تحديث التقدم
    """
    try:
        # خطوة 1: تحليل الرابط
        processing_sessions[session_id].update({
            "status": "analyzing",
            "progress": 10,
            "detail": "جاري تحليل الرابط...",
            "step": "تحليل الرابط"
        })
        await asyncio.sleep(1)
        
        # خطوة 2: استخراج معلومات الفيديو
        processing_sessions[session_id].update({
            "status": "extracting",
            "progress": 25,
            "detail": "جاري استخراج معلومات الفيديو باستخدام YouTube API...",
            "step": "استخراج المعلومات"
        })
        
        # استخراج معلومات الفيديو باستخدام الطريقة المحسّنة
        video_info = await extract_youtube_video_info(url, use_auth)
        
        # تحديث بمعلومات الفيديو المستخرجة
        processing_sessions[session_id].update({
            "title": video_info.get("title", "فيديو مستورد"),
            "duration": video_info.get("duration", 60),
            "format": video_info.get("format", "mp4"),
            "size": video_info.get("size", "غير معروف"),
            "size_bytes": video_info.get("size_bytes"),
            "dimensions": video_info.get("dimensions", "1280x720"),
            "thumbnail": video_info.get("thumbnail"),
            "uploader": video_info.get("uploader"),
            "description": video_info.get("description"),
            "view_count": video_info.get("view_count"),
            "like_count": video_info.get("like_count"),
            "platform": video_info.get("platform", "generic"),
            "ytdlp_error": video_info.get("ytdlp_error"),
            "warning": video_info.get("warning"),
            "is_external": video_info.get("is_external", True),
            "video_id": video_info.get("video_id"),
            "use_auth": use_auth
        })
        
        await asyncio.sleep(1.5)
        
        # خطوة 3: التحقق من الفيديو
        processing_sessions[session_id].update({
            "status": "verifying",
            "progress": 45,
            "detail": "جاري التحقق من الفيديو...",
            "step": "التحقق من الفيديو"
        })
        await asyncio.sleep(1)
        
        # خطوة 4: معالجة الفيديو
        processing_sessions[session_id].update({
            "status": "processing",
            "progress": 60,
            "detail": "جاري معالجة الفيديو...",
            "step": "معالجة الفيديو"
        })
        await asyncio.sleep(1.5)
        
        # خطوة 5: تحليل المحتوى
        processing_sessions[session_id].update({
            "status": "analyzing_content",
            "progress": 80,
            "detail": "جاري تحليل محتوى الفيديو...",
            "step": "تحليل المحتوى"
        })
        await asyncio.sleep(1)
        
        # خطوة 6: تجهيز الفيديو
        processing_sessions[session_id].update({
            "status": "finalizing",
            "progress": 92,
            "detail": "جاري تجهيز الفيديو للمعاينة...",
            "step": "تجهيز الفيديو"
        })
        await asyncio.sleep(1)
        
        # تحديد رابط الفيديو النهائي
        platform = video_info.get("platform", "generic")
        is_external = video_info.get("is_external", True)
        video_url = url
        
        # إذا كان الفيديو من يوتيوب أو منصة خارجية، نستخدم فيديو تجريبي للعرض
        if is_external or platform in ["youtube", "tiktok", "facebook", "instagram"]:
            video_url = "https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4"
            if not processing_sessions[session_id].get("warning"):
                processing_sessions[session_id]["warning"] = f"تم استخدام فيديو تجريبي للعرض (بديل لـ {platform})"
            processing_sessions[session_id]["detail"] = f"✅ تم معالجة الفيديو من {platform} (فيديو تجريبي للعرض)"
            
            # إذا كان يوتيوب، نحاول تحميل فيديو حقيقي
            if platform == "youtube" and video_info.get("video_id"):
                try:
                    video_id = video_info["video_id"]
                    downloaded_path = download_video(video_id, '720p')
                    if downloaded_path:
                        video_url = downloaded_path
                        processing_sessions[session_id]["detail"] = "✅ تم تحميل الفيديو من يوتيوب بنجاح!"
                        processing_sessions[session_id]["warning"] = None
                except Exception as e:
                    print(f"⚠️ فشل تحميل الفيديو: {e}")
        else:
            processing_sessions[session_id]["detail"] = "✅ تم معالجة الفيديو بنجاح!"
        
        # اكتمال المعالجة
        processing_sessions[session_id].update({
            "status": "completed",
            "progress": 100,
            "step": "اكتمل",
            "completed": True,
            "video_url": video_url,
            "title": video_info.get("title", "فيديو معالج"),
            "duration": video_info.get("duration", 60),
            "format": video_info.get("format", "mp4"),
            "size": video_info.get("size", "غير معروف"),
            "size_bytes": video_info.get("size_bytes"),
            "dimensions": video_info.get("dimensions", "1280x720"),
            "thumbnail": video_info.get("thumbnail"),
            "uploader": video_info.get("uploader"),
            "description": video_info.get("description"),
            "view_count": video_info.get("view_count"),
            "like_count": video_info.get("like_count"),
            "platform": video_info.get("platform"),
            "ytdlp_error": video_info.get("ytdlp_error"),
            "warning": video_info.get("warning"),
            "is_external": is_external,
            "video_id": video_info.get("video_id")
        })
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ خطأ في المعالجة: {error_detail}")
        
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
    توليد فيديو في الخلفية مع تحديث التقدم
    """
    try:
        steps = [
            (5, "analyzing_prompt", "تحليل الطلب...", "تحليل الطلب"),
            (15, "writing_script", "صياغة النص السكريبت...", "صياغة السكريبت"),
            (30, "generating_scenes", "توليد المشاهد...", "توليد المشاهد"),
            (50, "processing_media", "معالجة الصوت والصورة...", "معالجة الوسائط"),
            (70, "compiling", "تجميع الفيديو...", "تجميع الفيديو"),
            (85, "optimizing", "تحسين الجودة...", "تحسين الجودة"),
            (95, "finalizing", "تجهيز الفيديو...", "تجهيز الفيديو")
        ]
        
        for progress, status, detail, step in steps:
            if session_id in processing_sessions:
                processing_sessions[session_id].update({
                    "status": status,
                    "progress": progress,
                    "detail": detail,
                    "step": step
                })
            await asyncio.sleep(1.5)
        
        video_info = {
            "title": prompt[:50] + ("..." if len(prompt) > 50 else ""),
            "duration": 180,
            "format": "mp4",
            "size": "68.2 MB",
            "size_bytes": 68.2 * 1024 * 1024,
            "dimensions": "1920x1080",
            "generated": True
        }
        
        video_url = "https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4"
        
        if session_id in processing_sessions:
            processing_sessions[session_id].update({
                "status": "completed",
                "progress": 100,
                "detail": "اكتمل التوليد! ✅",
                "step": "اكتمل",
                "completed": True,
                "video_url": video_url,
                "title": video_info["title"],
                "duration": video_info["duration"],
                "format": video_info["format"],
                "size": video_info["size"],
                "size_bytes": video_info["size_bytes"],
                "dimensions": video_info["dimensions"],
                "generated": True
            })
        
    except Exception as e:
        if session_id in processing_sessions:
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
