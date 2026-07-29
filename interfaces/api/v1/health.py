from fastapi import APIRouter
from datetime import datetime
from config.settings import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/plugins")
async def plugins_health():
    from plugins.registry import PluginRegistry, PluginLoader
    registry = PluginRegistry()
    PluginLoader().load_all(settings.PLUGIN_CONFIG_PATH, registry)
    return {
        "plugins": registry.list_all(),
        "timestamp": datetime.utcnow().isoformat(),
    }
