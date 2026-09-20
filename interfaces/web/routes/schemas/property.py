"""Property video request schema."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PropertyVideoRequest(BaseModel):
    """نموذج طلب توليد فيديو عقاري."""
    project_id: str
    title: str = ""
    property_type: str = "apartment"
    price: Optional[float] = None
    currency: str = "SAR"
    city: str = ""
    district: str = ""
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    features: List[str] = []
    whatsapp: str = ""
    images: List[Dict[str, Any]] = []
    duration_per_image: float = 4.5
    style: str = "modern"

    voiceover_enabled: bool = True
    voiceover_voice: str = "ar-SA-HamedNeural"

    show_price: bool = True
    show_location: bool = True
    show_area: bool = True
    show_contact: bool = True
