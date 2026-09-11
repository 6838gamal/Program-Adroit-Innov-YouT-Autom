import uuid
from datetime import datetime
from typing import Optional, Any
from shared.base_entity import BaseEntity
from shared.value_objects import ProjectStatus, BrandColors
from shared.exceptions import ProjectAlreadyInProductionError, InvalidProjectStatusError


class Project(BaseEntity):
    """Project aggregate root — the central concept of the platform."""

    def __init__(
        self,
        title: str,
        description: str = "",
        script: str = "",
        tags: Optional[list[str]] = None,
        template_id: Optional[uuid.UUID] = None,
        logo_asset_id: Optional[uuid.UUID] = None,
        brand_colors: Optional[BrandColors] = None,
        settings: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ):
        super().__init__(id=id)
        self.title = title
        self.description = description
        self.script = script
        self.tags: list[str] = tags or []
        self.status = ProjectStatus.DRAFT
        self.template_id = template_id
        self.logo_asset_id = logo_asset_id
        self.brand_colors = brand_colors or BrandColors()
        self.settings: dict = settings or {}

        # Free-form blob persisted with the project.
        # Holds: clips, layers, total_duration, media_files,
        # thumbnail (URL), thumbnail_path, video_path, rendered_at, ...
        self.data: dict = {}

    # ── Business rules ────────────────────────────────────────────────────────

    def start_production(self) -> None:
        if self.status == ProjectStatus.IN_PRODUCTION:
            raise ProjectAlreadyInProductionError(self.id)
        if self.status == ProjectStatus.PUBLISHED:
            raise InvalidProjectStatusError(
                f"Cannot re-render a published project: {self.id}"
            )
        self.status = ProjectStatus.IN_PRODUCTION
        self._touch()

    def mark_rendered(self) -> None:
        self.status = ProjectStatus.RENDERED
        self._touch()

    def mark_failed(self) -> None:
        self.status = ProjectStatus.FAILED
        self._touch()

    def mark_published(self) -> None:
        self.status = ProjectStatus.PUBLISHED
        self._touch()

    def reset_to_draft(self) -> None:
        self.status = ProjectStatus.DRAFT
        self._touch()

    def update(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        script: Optional[str] = None,
        tags: Optional[list[str]] = None,
        template_id: Optional[uuid.UUID] = None,
        logo_asset_id: Optional[uuid.UUID] = None,
        brand_colors: Optional[BrandColors] = None,
        settings: Optional[dict] = None,
    ) -> None:
        if title is not None:
            self.title = title
        if description is not None:
            self.description = description
        if script is not None:
            self.script = script
        if tags is not None:
            self.tags = tags
        if template_id is not None:
            self.template_id = template_id
        if logo_asset_id is not None:
            self.logo_asset_id = logo_asset_id
        if brand_colors is not None:
            self.brand_colors = brand_colors
        if settings is not None:
            self.settings = {**self.settings, **settings}
        self._touch()

    # ── Data blob helpers ─────────────────────────────────────────────────────

    def update_data(self, data: dict) -> None:
        """
        Merge the given dict into `self.data`.

        Used by ProductionService to persist render outputs
        (thumbnail URL, video path, clips, layers, ...).
        """
        if not isinstance(data, dict):
            return
        existing = self.data if isinstance(self.data, dict) else {}
        existing.update(data)
        self.data = existing
        self._touch()

    def replace_data(self, data: dict) -> None:
        """Replace the entire data blob."""
        self.data = dict(data or {})
        self._touch()

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def can_render(self) -> bool:
        return self.status in (
            ProjectStatus.DRAFT,
            ProjectStatus.RENDERED,
            ProjectStatus.FAILED,
        )

    @property
    def can_publish(self) -> bool:
        return self.status == ProjectStatus.RENDERED

    @property
    def thumbnail(self) -> Optional[str]:
        """Public URL of the rendered video thumbnail, if any."""
        if isinstance(self.data, dict):
            return self.data.get("thumbnail")
        return None

    @property
    def video_url(self) -> Optional[str]:
        """Public URL of the rendered video, if any."""
        if isinstance(self.data, dict):
            return self.data.get("video_url")
        return None

    @property
    def video_path(self) -> Optional[str]:
        """Local filesystem path of the rendered video, if any."""
        if isinstance(self.data, dict):
            return self.data.get("video_path")
        return None

    @property
    def duration(self) -> Optional[float]:
        """Total duration in seconds, if known."""
        if isinstance(self.data, dict):
            value = self.data.get("total_duration")
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None
        return None

    @property
    def progress(self) -> int:
        """Render progress (0-100), if any."""
        if isinstance(self.data, dict):
            value = self.data.get("progress")
            try:
                return int(value) if value is not None else 0
            except (TypeError, ValueError):
                return 0
        return 0

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "script": self.script,
            "tags": self.tags,
            "status": self.status.value,
            "template_id": str(self.template_id) if self.template_id else None,
            "logo_asset_id": str(self.logo_asset_id) if self.logo_asset_id else None,
            "brand_colors": self.brand_colors.to_dict(),
            "settings": self.settings,
            "data": self.data,
            "thumbnail": self.thumbnail,
            "video_url": self.video_url,
            "video_path": self.video_path,
            "duration": self.duration,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        """
        Reconstruct a Project from a dict (e.g. from SQLAlchemy row).

        Tolerant of missing keys so it can be used with legacy rows.
        """
        # Resolve status value safely
        status_value = data.get("status")
        if isinstance(status_value, ProjectStatus):
            status = status_value
        else:
            try:
                status = ProjectStatus(str(status_value))
            except Exception:
                status = ProjectStatus.DRAFT

        # Resolve brand colors
        brand_colors_raw = data.get("brand_colors") or {}
        if isinstance(brand_colors_raw, BrandColors):
            brand_colors = brand_colors_raw
        elif isinstance(brand_colors_raw, dict):
            try:
                brand_colors = BrandColors(**brand_colors_raw)
            except Exception:
                brand_colors = BrandColors()
        else:
            brand_colors = BrandColors()

        # Resolve ids
        def _uuid(value):
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return value
            try:
                return uuid.UUID(str(value))
            except Exception:
                return None

        project = cls(
            title=data.get("title", ""),
            description=data.get("description", "") or "",
            script=data.get("script", "") or "",
            tags=list(data.get("tags") or []),
            template_id=_uuid(data.get("template_id")),
            logo_asset_id=_uuid(data.get("logo_asset_id")),
            brand_colors=brand_colors,
            settings=dict(data.get("settings") or {}),
            id=_uuid(data.get("id")),
        )

        project.status = status
        project.data = dict(data.get("data") or {})

        # Restore timestamps when available (BaseEntity manages them)
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")
        try:
            if created_at:
                if isinstance(created_at, str):
                    project.created_at = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                elif isinstance(created_at, datetime):
                    project.created_at = created_at
        except Exception:
            pass
        try:
            if updated_at:
                if isinstance(updated_at, str):
                    project.updated_at = datetime.fromisoformat(
                        updated_at.replace("Z", "+00:00")
                    )
                elif isinstance(updated_at, datetime):
                    project.updated_at = updated_at
        except Exception:
            pass

        return project
