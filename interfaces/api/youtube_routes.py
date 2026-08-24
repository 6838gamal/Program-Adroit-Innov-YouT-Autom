from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel

from application.services.youtube_service import YouTubeService


router = APIRouter(prefix="/youtube", tags=["youtube"])


# ============================================
# نماذج Pydantic
# ============================================

class YouTubeVideoRequest(BaseModel):
    url: str
    use_auth: bool = False


class YouTubeSearchRequest(BaseModel):
    query: str
    max_results: int = 10


class YouTubeAuthRequest(BaseModel):
    code: str
    user_id: str = "default"


# ============================================
# نقاط النهاية
# ============================================

def get_youtube_service() -> YouTubeService:
    return YouTubeService()


@router.get("/video")
async def get_youtube_video(
    url: str = Query(..., description="رابط فيديو يوتيوب"),
    use_auth: bool = Query(False, description="استخدام OAuth"),
    service: YouTubeService = Depends(get_youtube_service)
):
    """الحصول على معلومات فيديو يوتيوب"""
    try:
        video_id = service.extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=400, detail="رابط يوتيوب غير صحيح")
        
        info = service.get_video_info(video_id, use_auth)
        if not info:
            raise HTTPException(status_code=404, detail="لم يتم العثور على الفيديو")
        
        # إضافة معلومات التحميل من pytube
        from utils.video_utils import get_download_info
        download_info = get_download_info(video_id)
        
        return {
            **info,
            "download": download_info,
            "url": url,
            "video_id": video_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video/batch")
async def get_youtube_videos_batch(
    urls: List[str],
    service: YouTubeService = Depends(get_youtube_service)
):
    """الحصول على معلومات مجموعة فيديوهات"""
    results = []
    for url in urls:
        try:
            video_id = service.extract_video_id(url)
            if video_id:
                info = service.get_video_info(video_id)
                if info:
                    results.append(info)
        except Exception as e:
            print(f"⚠️ خطأ في معالجة {url}: {e}")
    
    return {
        "total": len(results),
        "videos": results
    }


@router.post("/search")
async def search_youtube(
    request: YouTubeSearchRequest,
    service: YouTubeService = Depends(get_youtube_service)
):
    """البحث عن فيديوهات في يوتيوب"""
    try:
        videos = service.search_videos(request.query, request.max_results)
        return {
            "query": request.query,
            "total": len(videos),
            "videos": videos
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/channel/{channel_id}")
async def get_channel_info(
    channel_id: str,
    service: YouTubeService = Depends(get_youtube_service)
):
    """الحصول على معلومات القناة"""
    try:
        info = service.get_channel_info(channel_id)
        if not info:
            raise HTTPException(status_code=404, detail="لم يتم العثور على القناة")
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# نقاط نهاية OAuth
# ============================================

@router.get("/auth/url")
async def get_auth_url(
    service: YouTubeService = Depends(get_youtube_service)
):
    """الحصول على رابط مصادقة OAuth"""
    try:
        auth_url = service.get_auth_url()
        return {
            "auth_url": auth_url,
            "message": "افتح الرابط للمصادقة"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/callback")
async def auth_callback(
    request: YouTubeAuthRequest,
    service: YouTubeService = Depends(get_youtube_service)
):
    """استقبال كود المصادقة"""
    try:
        success = service.authenticate(request.code, request.user_id)
        if success:
            return {
                "status": "success",
                "message": "تمت المصادقة بنجاح",
                "user_id": request.user_id
            }
        else:
            raise HTTPException(status_code=400, detail="فشلت المصادقة")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/status")
async def auth_status(
    user_id: str = Query("default"),
    service: YouTubeService = Depends(get_youtube_service)
):
    """التحقق من حالة المصادقة"""
    is_auth = service.is_authenticated(user_id)
    return {
        "user_id": user_id,
        "authenticated": is_auth
    }


# ============================================
# نقاط نهاية محمية
# ============================================

@router.get("/my/videos")
async def get_my_videos(
    max_results: int = Query(10, ge=1, le=50),
    service: YouTubeService = Depends(get_youtube_service)
):
    """الحصول على فيديوهات المستخدم"""
    try:
        videos = service.get_my_uploads(max_results)
        return {
            "total": len(videos),
            "videos": videos
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my/subscriptions")
async def get_my_subscriptions(
    max_results: int = Query(10, ge=1, le=50),
    service: YouTubeService = Depends(get_youtube_service)
):
    """الحصول على قنوات المشترك فيها"""
    try:
        subscriptions = service.get_subscriptions(max_results)
        return {
            "total": len(subscriptions),
            "subscriptions": subscriptions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# نقطة نهاية الفيديو المتكاملة (تحل محل القديمة)
# ============================================

@router.post("/process")
async def process_youtube_video(
    request: YouTubeVideoRequest,
    service: YouTubeService = Depends(get_youtube_service)
):
    """معالجة فيديو يوتيوب (بديل لنقطة /video/process)"""
    try:
        video_id = service.extract_video_id(request.url)
        if not video_id:
            raise HTTPException(status_code=400, detail="رابط يوتيوب غير صحيح")
        
        # الحصول على المعلومات
        info = service.get_video_info(video_id, request.use_auth)
        if not info:
            raise HTTPException(status_code=404, detail="لم يتم العثور على الفيديو")
        
        # الحصول على معلومات التحميل
        from utils.video_utils import get_download_info
        download_info = get_download_info(video_id)
        
        return {
            "session_id": str(uuid4()),
            "status": "completed",
            "progress": 100,
            "detail": "تم استخراج المعلومات بنجاح",
            "step": "اكتمل",
            "completed": True,
            "video_url": request.url,
            **info,
            "download": download_info,
            "is_external": True,
            "platform": "youtube"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
