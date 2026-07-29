from fastapi import Request
from plugins.registry import PluginRegistry


def get_plugin_registry_from_app(request: Request) -> PluginRegistry:
    return request.app.state.plugin_registry
