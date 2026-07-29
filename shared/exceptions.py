"""Domain exceptions — all business rule violations live here."""


class DomainError(Exception):
    """Base class for all domain errors."""
    pass


# ── Project ──────────────────────────────────────────────────────────────────

class ProjectNotFoundError(DomainError):
    def __init__(self, project_id):
        super().__init__(f"Project not found: {project_id}")


class ProjectAlreadyInProductionError(DomainError):
    def __init__(self, project_id):
        super().__init__(f"Project is already in production: {project_id}")


class InvalidProjectStatusError(DomainError):
    pass


# ── Pipeline ─────────────────────────────────────────────────────────────────

class PipelineError(DomainError):
    pass


class PipelineStageError(PipelineError):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"Pipeline stage '{stage}' failed: {message}")


class RenderJobNotFoundError(DomainError):
    def __init__(self, job_id):
        super().__init__(f"Render job not found: {job_id}")


# ── Asset ────────────────────────────────────────────────────────────────────

class AssetNotFoundError(DomainError):
    def __init__(self, asset_id):
        super().__init__(f"Asset not found: {asset_id}")


class AssetUploadError(DomainError):
    pass


class UnsupportedAssetTypeError(DomainError):
    pass


# ── Publishing ───────────────────────────────────────────────────────────────

class PublisherNotFoundError(DomainError):
    def __init__(self, platform: str):
        super().__init__(f"No publisher plugin registered for platform: {platform}")


class ContentValidationError(DomainError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Content validation failed: {'; '.join(errors)}")


class PublishError(DomainError):
    pass


class AuthenticationError(DomainError):
    pass


class AccountNotFoundError(DomainError):
    def __init__(self, account_id):
        super().__init__(f"Publisher account not found: {account_id}")


# ── Plugin ───────────────────────────────────────────────────────────────────

class PluginNotFoundError(DomainError):
    def __init__(self, plugin_type: str, name: str):
        super().__init__(f"Plugin not found: type={plugin_type}, name={name}")


class PluginLoadError(DomainError):
    pass


# ── Timeline ─────────────────────────────────────────────────────────────────

class TimelineNotFoundError(DomainError):
    def __init__(self, project_id):
        super().__init__(f"Timeline not found for project: {project_id}")


class InvalidTimelineOperationError(DomainError):
    pass


# ── Template ─────────────────────────────────────────────────────────────────

class TemplateNotFoundError(DomainError):
    def __init__(self, template_id):
        super().__init__(f"Template not found: {template_id}")
