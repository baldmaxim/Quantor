"""Модели SQLAlchemy. Импортируются пакетом, чтобы Alembic видел все таблицы."""

from app.models.artifact import RecognitionArtifact
from app.models.document import Document, DocumentRevision
from app.models.job import Job
from app.models.project import Project
from app.models.sheet import Region, Sheet

__all__ = [
    "Document",
    "DocumentRevision",
    "Job",
    "Project",
    "RecognitionArtifact",
    "Region",
    "Sheet",
]
