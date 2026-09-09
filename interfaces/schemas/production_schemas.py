from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum


# ============================================================
#  Enums
# ============================================================

class RenderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================
#  Request Schemas (ما يرسله العميل)
# ============================================================

class ClipData(BaseModel):
    """بيانات المقطع الواحد من التايم لاين"""
    id: Optional[int] = None
    type: str = Field(..., description="نوع المقطع: image, video, audio, text")
    layer: int = Field(default=0, description="رقم الطبقة")
    start: float = Field(default=0.0, description="وقت البداية بالثواني")
    duration: float = Field(default=3.0, description="المدة بالثواني")
    title: Optional[str] = Field(default="مقطع", description="عنوان المقطع")
    content: Optional[str] = Field(None, description="المحتوى (نص، مسار الصورة، URL الفيديو، إلخ)")
    color: Optional[str] = Field(None, description="لون المقطع (اختياري)")
    icon: Optional[str] = Field(None, description="أيقونة المقطع (اختياري)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="بيانات إضافية")
    
    @validator('type')
    def validate_type(cls, v):
        allowed = ['image', 'video', 'audio', 'text']
        if v not in allowed:
            raise ValueError(f'type must be one of: {", ".join(allowed)}')
        return v
    
    @validator('duration')
    def validate_duration(cls, v):
        if v < 0.1:
            raise ValueError('duration must be at least 0.1 seconds')
        return v
    
    @validator('start')
    def validate_start(cls, v):
        if v < 0:
            raise ValueError('start cannot be negative')
        return v


class LayerData(BaseModel):
    """بيانات الطبقة الواحدة"""
    name: str = Field(default="طبقة", description="اسم الطبقة")
    visible: bool = Field(default=True, description="مرئية أم لا")
    locked: bool = Field(default=False, description="مقفلة أم لا")


class MediaFileData(BaseModel):
    """بيانات ملف وسائط مستورد"""
    name: str = Field(..., description="اسم الملف")
    size: int = Field(..., description="حجم الملف بالبايت")
    type: str = Field(..., description="نوع الملف (image/png, video/mp4, إلخ)")
    url: Optional[str] = Field(None, description="مسار الملف (اختياري)")


class StartRenderRequest(BaseModel):
    """
    طلب بدء الرندر
    
    يمكن للعميل إرسال:
    1. فقط project_id (لرندر مشروع موجود)
    2. project_id + بيانات المشروع الكاملة (لحفظ المشروع ثم رندره)
    """
    
    # ====== الحقول المطلوبة للرندر ======
    project_id: UUID = Field(..., description="معرف المشروع (مطلوب)")
    
    # ====== إعدادات الرندر (اختيارية مع قيم افتراضية) ======
    fps: Optional[int] = Field(default=30, ge=1, le=120, description="عدد الإطارات في الثانية")
    width: Optional[int] = Field(default=1920, ge=320, le=7680, description="عرض الفيديو بالبكسل")
    height: Optional[int] = Field(default=1080, ge=240, le=4320, description="ارتفاع الفيديو بالبكسل")
    quality: Optional[str] = Field(
        default="medium", 
        description="جودة الفيديو: low, medium, high"
    )
    
    # ====== بيانات المشروع الإضافية (اختيارية - يرسلها العميل من المحرر) ======
    clips: Optional[List[ClipData]] = Field(None, description="قائمة المقاطع في التايم لاين")
    layers: Optional[List[LayerData]] = Field(None, description="قائمة الطبقات")
    duration: Optional[float] = Field(default=10.0, ge=0.5, description="المدة الإجمالية للمشروع بالثواني")
    mediaFiles: Optional[List[MediaFileData]] = Field(None, description="قائمة ملفات الوسائط المستوردة")
    
    # ====== بيانات إضافية (اختيارية) ======
    script: Optional[str] = Field(None, description="نص المشروع (للمشاريع النصية)")
    title: Optional[str] = Field(None, description="عنوان المشروع")
    brand_colors: Optional[Dict[str, str]] = Field(None, description="ألوان العلامة التجارية")
    
    class Config:
        schema_extra = {
            "example": {
                "project_id": "778bf000-e348-4fad-8fc8-9f418ec9d190",
                "fps": 30,
                "width": 1920,
                "height": 1080,
                "quality": "medium",
                "clips": [
                    {
                        "id": 1,
                        "type": "image",
                        "layer": 0,
                        "start": 0,
                        "duration": 3,
                        "title": "صورة تمهيدية",
                        "content": "https://example.com/image.jpg"
                    }
                ],
                "layers": [
                    {"name": "طبقة 1", "visible": True, "locked": False}
                ],
                "duration": 10.0,
                "mediaFiles": [
                    {"name": "image.jpg", "size": 1024, "type": "image/jpeg"}
                ]
            }
        }


# ============================================================
#  Response Schemas (ما يرسله السيرفر)
# ============================================================

class RenderJobResponse(BaseModel):
    """استجابة مهمة الرندر"""
    id: UUID = Field(..., description="معرف مهمة الرندر")
    project_id: UUID = Field(..., description="معرف المشروع")
    renderer: str = Field(default="default", description="نوع الرندر المستخدم")
    status: str = Field(..., description="حالة المهمة: pending, processing, completed, failed, cancelled")
    progress: float = Field(default=0.0, ge=0, le=100, description="نسبة التقدم (0-100)")
    current_stage: str = Field(default="", description="المرحلة الحالية")
    output_path: Optional[str] = Field(None, description="مسار الفيديو الناتج")
    error_message: Optional[str] = Field(None, description="رسالة الخطأ (في حالة الفشل)")
    started_at: Optional[datetime] = Field(None, description="وقت بدء الرندر")
    completed_at: Optional[datetime] = Field(None, description="وقت الانتهاء")
    created_at: datetime = Field(..., description="وقت الإنشاء")
    
    class Config:
        schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "project_id": "778bf000-e348-4fad-8fc8-9f418ec9d190",
                "renderer": "ffmpeg",
                "status": "processing",
                "progress": 45.5,
                "current_stage": "تركيب الفيديو النهائي",
                "output_path": None,
                "error_message": None,
                "started_at": "2026-09-09T13:20:11.652443Z",
                "completed_at": None,
                "created_at": "2026-09-09T13:20:11.652443Z"
            }
        }


class ExportRequest(BaseModel):
    """طلب تصدير الفيديو"""
    render_job_id: UUID = Field(..., description="معرف مهمة الرندر")
    format: str = Field(default="mp4", description="صيغة الفيديو: mp4, mov, avi")
    aspect_ratio: str = Field(default="16:9", description="نسبة العرض إلى الارتفاع")
    width: int = Field(default=1920, ge=320, le=7680, description="العرض بالبكسل")
    height: int = Field(default=1080, ge=240, le=4320, description="الارتفاع بالبكسل")
    
    @validator('format')
    def validate_format(cls, v):
        allowed = ['mp4', 'mov', 'avi', 'webm', 'mkv']
        if v not in allowed:
            raise ValueError(f'format must be one of: {", ".join(allowed)}')
        return v


class RenderStatusResponse(BaseModel):
    """استجابة حالة الرندر (لـ polling)"""
    job_id: str = Field(..., description="معرف مهمة الرندر")
    project_id: str = Field(..., description="معرف المشروع")
    status: str = Field(..., description="حالة المهمة")
    progress: int = Field(default=0, description="نسبة التقدم")
    current_stage: Optional[str] = Field(None, description="المرحلة الحالية")
    error: Optional[str] = Field(None, description="رسالة الخطأ")
    output_url: Optional[str] = Field(None, description="رابط الفيديو الناتج")
    updated_at: str = Field(..., description="وقت آخر تحديث")


class CancelRenderResponse(BaseModel):
    """استجابة إلغاء الرندر"""
    job_id: str = Field(..., description="معرف مهمة الرندر")
    status: str = Field(default="cancelled", description="الحالة الجديدة")
    message: str = Field(default="Render job cancelled successfully", description="رسالة التأكيد")


class RenderJobListResponse(BaseModel):
    """استجابة قائمة مهام الرندر"""
    jobs: List[RenderJobResponse] = Field(..., description="قائمة المهام")
    total: int = Field(..., description="إجمالي عدد المهام")
