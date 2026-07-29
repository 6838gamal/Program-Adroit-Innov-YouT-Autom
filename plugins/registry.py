import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

from shared.exceptions import PluginNotFoundError, PluginLoadError
from shared.ports.renderer_port import RendererPort
from shared.ports.publisher_port import PublisherPort
from shared.ports.voice_port import VoicePort
from shared.ports.exporter_port import ExporterPort

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Central plugin registry.
    Loaded at startup from plugin_config.yaml.
    All services receive implementations via Dependency Injection.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, plugin_type: str, name: str, plugin: Any) -> None:
        key = f"{plugin_type}:{name}"
        self._plugins[key] = plugin
        logger.info("Plugin registered: %s", key)

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_renderer(self) -> RendererPort:
        return self._get("renderer", "default")

    def get_exporter(self) -> ExporterPort:
        return self._get("exporter", "default")

    def get_voice_provider(self, name: str = "default") -> VoicePort:
        return self._get("voice", name)

    def get_publisher(self, platform: str) -> PublisherPort:
        return self._get("publisher", platform)

    def list_publishers(self) -> list[PublisherPort]:
        return [v for k, v in self._plugins.items() if k.startswith("publisher:")]

    def list_voices(self) -> list[VoicePort]:
        return [v for k, v in self._plugins.items() if k.startswith("voice:")]

    def list_all(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for key in self._plugins:
            plugin_type, name = key.split(":", 1)
            result.setdefault(plugin_type, []).append(name)
        return result

    def _get(self, plugin_type: str, name: str) -> Any:
        key = f"{plugin_type}:{name}"
        if key not in self._plugins:
            raise PluginNotFoundError(plugin_type, name)
        return self._plugins[key]


class PluginLoader:
    """Loads plugins from YAML config at startup."""

    def load_all(self, config_path: Path, registry: PluginRegistry) -> None:
        if not config_path.exists():
            logger.warning("Plugin config not found at %s — using defaults", config_path)
            self._load_defaults(registry)
            return

        with open(config_path) as f:
            config = yaml.safe_load(f)

        plugins_cfg = config.get("plugins", {})

        for plugin_type, type_config in plugins_cfg.items():
            enabled = type_config.get("enabled", [])
            default_name = type_config.get("default", "")

            for plugin_def in enabled:
                try:
                    instance = self._instantiate(plugin_def)
                    name = plugin_def["name"]
                    registry.register(plugin_type, name, instance)
                    if name == default_name or len(enabled) == 1:
                        registry.register(plugin_type, "default", instance)
                except Exception as exc:
                    logger.error(
                        "Failed to load plugin %s/%s: %s",
                        plugin_type,
                        plugin_def.get("name"),
                        exc,
                    )

    def _instantiate(self, plugin_def: dict) -> Any:
        module_path = plugin_def["module"]
        class_name = plugin_def["class"]
        cfg = plugin_def.get("config", {})

        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise PluginLoadError(f"Cannot import {module_path}: {e}") from e

        cls = getattr(module, class_name, None)
        if cls is None:
            raise PluginLoadError(f"Class {class_name} not found in {module_path}")

        return cls(config=cfg) if cfg else cls()

    def _load_defaults(self, registry: PluginRegistry) -> None:
        """Load built-in plugins when no config file exists."""
        from plugins.renderer.ffmpeg_renderer import FFmpegRendererPlugin
        from plugins.exporter.ffmpeg_exporter import FFmpegExporterPlugin
        from plugins.voice.silent_voice import SilentVoicePlugin

        renderer = FFmpegRendererPlugin()
        registry.register("renderer", "ffmpeg", renderer)
        registry.register("renderer", "default", renderer)

        exporter = FFmpegExporterPlugin()
        registry.register("exporter", "ffmpeg", exporter)
        registry.register("exporter", "default", exporter)

        voice = SilentVoicePlugin()
        registry.register("voice", "silent", voice)
        registry.register("voice", "default", voice)
