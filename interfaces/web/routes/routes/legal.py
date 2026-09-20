"""Legal pages: privacy policy + terms of service + test code."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from config.settings import settings

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

router = APIRouter()


@router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy_page(request: Request):
    """صفحة سياسة الخصوصية."""
    return templates.TemplateResponse(request, "privacy_policy.html", {
        "active_page": "privacy_policy",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })


@router.get("/terms-of-service", response_class=HTMLResponse)
async def terms_of_service_page(request: Request):
    """صفحة شروط الخدمة."""
    return templates.TemplateResponse(request, "terms_of_service.html", {
        "active_page": "terms_of_service",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })


@router.get("/test-code", response_class=HTMLResponse)
async def test_code_page(request: Request):
    """صفحة تجريبية لتنزيل الفيديو من الرابط مع معاينة."""
    return templates.TemplateResponse(request, "test_code.html", {
        "active_page": "test_code",
        "supabase": get_supabase_config(),
        "last_updated": "2026-09-14",
        "settings": {
            "APP_NAME": settings.APP_NAME,
            "APP_VERSION": settings.APP_VERSION,
        },
    })
