"""Модели SQLAlchemy. Импортируются пакетом, чтобы Alembic видел все таблицы."""

from app.models.artifact import RecognitionArtifact
from app.models.audit import AuditEvent
from app.models.control_plane import FeatureFlagOverride, SettingOverride
from app.models.document import Document, DocumentRevision
from app.models.identity import AuthSession, UserIdentity, Workspace, WorkspaceMembership
from app.models.job import Job
from app.models.project import Project
from app.models.sheet import Region, Sheet
from app.models.worker import Worker

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Document",
    "DocumentRevision",
    "FeatureFlagOverride",
    "Job",
    "Project",
    "RecognitionArtifact",
    "Region",
    "SettingOverride",
    "Sheet",
    "UserIdentity",
    "Worker",
    "Workspace",
    "WorkspaceMembership",
]
