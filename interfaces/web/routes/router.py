"""المُجمِّع الرئيسي لكل web routes."""
from fastapi import APIRouter

from .routes import (
    dashboard,
    projects,
    voice,
    talking_head,
    property_video,
    media_voiceover,
    assets_templates,
    publishing,
    analytics_logs,
    health_settings,
    legal,
    debug,
)

router = APIRouter(tags=["web"])

# ترتيب التسجيل مهم: dashboard (/) أولاً
for module in (
    dashboard,
    projects,
    voice,
    talking_head,
    property_video,
    media_voiceover,
    assets_templates,
    publishing,
    analytics_logs,
    health_settings,
    legal,
    debug,
):
    router.include_router(module.router)
