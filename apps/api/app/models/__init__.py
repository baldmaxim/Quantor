"""Модели SQLAlchemy. Импортируются пакетом, чтобы Alembic видел все таблицы."""

from app.models.artifact import RecognitionArtifact
from app.models.audit import AuditEvent
from app.models.calc import (
    CalcFact,
    CalcFactConflict,
    CalcFactEvidence,
    CalcManualOverride,
    CalcSource,
    CalcSourceInspection,
)
from app.models.calc_rules import CalcRuleDefinition, CalcRuleReview, CalcRuleVersion
from app.models.calc_runs import CalcRun, CalcRunResult, CalcRunStep
from app.models.calc_synthesis import CalcSynthesisDecision, CalcSynthesisRun
from app.models.control_plane import FeatureFlagOverride, SettingOverride
from app.models.document import Document, DocumentRevision
from app.models.identity import AuthSession, UserIdentity, Workspace, WorkspaceMembership
from app.models.job import Job
from app.models.page_geometry import PageGeometry
from app.models.project import Project
from app.models.scale import ScaleCalibration
from app.models.sheet import Region, Sheet
from app.models.takeoff import Measurement, TakeoffItem
from app.models.worker import Worker

__all__ = [
    "AuditEvent",
    "AuthSession",
    "CalcFact",
    "CalcFactConflict",
    "CalcFactEvidence",
    "CalcManualOverride",
    "CalcRuleDefinition",
    "CalcRuleReview",
    "CalcRuleVersion",
    "CalcRun",
    "CalcRunResult",
    "CalcRunStep",
    "CalcSource",
    "CalcSourceInspection",
    "CalcSynthesisDecision",
    "CalcSynthesisRun",
    "Document",
    "DocumentRevision",
    "FeatureFlagOverride",
    "Job",
    "Measurement",
    "PageGeometry",
    "Project",
    "RecognitionArtifact",
    "Region",
    "ScaleCalibration",
    "SettingOverride",
    "Sheet",
    "TakeoffItem",
    "UserIdentity",
    "Worker",
    "Workspace",
    "WorkspaceMembership",
]
