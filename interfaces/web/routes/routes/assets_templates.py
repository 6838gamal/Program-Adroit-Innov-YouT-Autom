"""Assets, templates, and voices pages."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from infrastructure.database.session import get_db
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter

from ..core.config_helpers import get_supabase_config
from ..core.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/assets", response_class=HTMLResponse)
async def assets_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from infrastructure.repositories.sql_asset_repository import (
        SQLAssetRepository,
    )
    repo = SQLAssetRepository(session)
    assets = await repo.list_all(limit=50)
    total = await repo.count()

    supabase_files = []
    try:
        if settings.supabase_configured:
            storage = SupabaseStorageAdapter()
            supabase_files = await storage.list_files()
    except Exception as e:
        logger.warning(f"Failed to list Supabase files: {e}")

    return templates.TemplateResponse(request, "assets/library.html", {
        "assets": assets,
        "total": total,
        "supabase_files": supabase_files,
        "active_page": "assets",
        "supabase": get_supabase_config(),
    })


@router.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    builtin_templates = [
        {
            "id": "short_video",
            "name": "فيديو قصير",
            "description": "قالب مناسب لفيديوهات قصيرة",
            "gradient": "from-blue-900 to-blue-700",
            "ratio": "16:9",
            "tags": ["تعليم", "عروض", "تسويق"],
            "quality": 4,
        },
        {
            "id": "reel",
            "name": "ريلز / شورتس",
            "description": "قالب عمودي للمنصات القصيرة",
            "gradient": "from-pink-900 to-purple-800",
            "ratio": "9:16",
            "tags": ["ريلز", "شورتس", "سوشيال"],
            "quality": 4,
        },
        {
            "id": "educational",
            "name": "تعليمي",
            "description": "قالب طويل للمحتوى التعليمي",
            "gradient": "from-emerald-900 to-teal-800",
            "ratio": "16:9",
            "tags": ["تعليم", "شرح", "درس"],
            "quality": 5,
        },
        {
            "id": "product",
            "name": "مراجعة منتج",
            "description": "قالب للمراجعات والعروض",
            "gradient": "from-amber-900 to-orange-800",
            "ratio": "16:9",
            "tags": ["مراجعة", "تقنية", "منتج"],
            "quality": 4,
        },
        {
            "id": "square",
            "name": "مربع",
            "description": "قالب مربع لـ Instagram/LinkedIn",
            "gradient": "from-slate-700 to-slate-600",
            "ratio": "1:1",
            "tags": ["إنستقرام", "لينكدإن"],
            "quality": 3,
        },
    ]
    return templates.TemplateResponse(request, "templates_page.html", {
        "builtin_templates": builtin_templates,
        "custom_templates": [],
        "active_page": "templates",
        "supabase": get_supabase_config(),
    })


@router.get("/voices", response_class=HTMLResponse)
async def voices_page(request: Request):
    voice_engines = [
        {
            "id": "edge_tts",
            "name": "Edge TTS (مجاني)",
            "provider": "Microsoft",
            "description": "أصوات احترافية جاهزة — بدون استنساخ",
            "languages": ["ar", "en", "fr", "de", "es", "+36"],
            "quality": 4,
            "available": settings.EDGE_TTS_ENABLED,
            "active": True,
        },
        {
            "id": "huggingface",
            "name": "HuggingFace XTTS",
            "provider": "HuggingFace Spaces",
            "description": "استنساخ صوتك — مجاني تماماً",
            "languages": ["ar", "en", "fr", "de", "es"],
            "quality": 4,
            "available": True,
            "active": False,
        },
        {
            "id": "elevenlabs",
            "name": "ElevenLabs",
            "provider": "ElevenLabs API",
            "description": "الأفضل جودة — مدفوع ($5/شهر)",
            "languages": ["ar", "en", "fr", "de", "es", "+10"],
            "quality": 5,
            "available": settings.elevenlabs_configured,
            "active": False,
        },
        {
            "id": "did_talking_head",
            "name": "D-ID Talking Head",
            "provider": "D-ID API",
            "description": "تحريك صورة الشخص",
            "languages": ["كل اللغات"],
            "quality": 5,
            "available": settings.did_configured,
            "active": settings.did_configured,
        },
    ]
    return templates.TemplateResponse(request, "voices.html", {
        "voice_engines": voice_engines,
        "active_voice": "Edge TTS (مجاني)",
        "active_page": "voices",
        "supabase": get_supabase_config(),
    })
