"""Модели SQLAlchemy. Импортируются пакетом, чтобы Alembic видел все таблицы."""

from app.models.artifact import RecognitionArtifact
from app.models.audit import AuditEvent
from app.models.control_plane import FeatureFlagOverride, SettingOverride
from app.models.document import Document, DocumentRevision
from app.models.identity import AuthSession, UserIdentity, Workspace, WorkspaceMembership
from app.models.job import Job
from app.models.page_geometry import PageGeometry
from app.models.project import Project
from app.models.scale import ScaleCalibration
from app.models.sheet import Region, Sheet
from app.models.worker import Worker

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Document",
    "DocumentRevision",
    "FeatureFlagOverride",
    "Job",
    "PageGeometry",
    "Project",
    "RecognitionArtifact",
    "Region",
    "ScaleCalibration",
    "SettingOverride",
    "Sheet",
    "UserIdentity",
    "Worker",
    "Workspace",
    "WorkspaceMembership",
]
