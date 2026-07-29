import uuid
from typing import Optional
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
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
