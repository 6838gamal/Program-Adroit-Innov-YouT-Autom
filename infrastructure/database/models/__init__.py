# Import all models here so SQLAlchemy's metadata knows about them
from infrastructure.database.models.project_model import ProjectModel
from infrastructure.database.models.timeline_model import TimelineModel, TrackModel, SceneModel, LayerModel
from infrastructure.database.models.asset_model import AssetModel, AssetCategoryModel
from infrastructure.database.models.template_model import TemplateModel
from infrastructure.database.models.render_job_model import RenderJobModel, ExportJobModel
from infrastructure.database.models.publishing_model import (
    PublisherAccountModel,
    PublishingPlatformModel,
    PublishingJobModel,
    ScheduleModel,
)
from infrastructure.database.models.log_model import LogModel
from infrastructure.database.models.notification_model import NotificationModel

__all__ = [
    "ProjectModel",
    "TimelineModel", "TrackModel", "SceneModel", "LayerModel",
    "AssetModel", "AssetCategoryModel",
    "TemplateModel",
    "RenderJobModel", "ExportJobModel",
    "PublisherAccountModel", "PublishingPlatformModel",
    "PublishingJobModel", "ScheduleModel",
    "LogModel", "NotificationModel",
]
