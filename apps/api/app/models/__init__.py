"""Модели SQLAlchemy. Импортируются пакетом, чтобы Alembic видел все таблицы."""

from app.models.artifact import RecognitionArtifact
from app.models.audit import AuditEvent
from app.models.cad_construction import CadConstructionProps, CadSheetLevels
from app.models.cad_decision import CadDecision
from app.models.cad_finish_template import CadFinishTemplate
from app.models.cad_project_levels import CadProjectLevels, CadSlabHoleDecision
from app.models.cad_remark import CadRemark
from app.models.cad_riser import CadSheetRisers
from app.models.cad_section_level import CadSectionLevel
from app.models.cad_vor import CadVorDocument, CadVorItem, CadVorLink
from app.models.cad_zone import CadZone
from app.models.calc import (
    CalcFact,
    CalcFactConflict,
    CalcFactEvidence,
    CalcManualOverride,
    CalcSource,
    CalcSourceInspection,
)
from app.models.calc_passports import CalcExpectedQuantity, CalcPassport
from app.models.calc_rules import CalcRuleDefinition, CalcRuleReview, CalcRuleVersion
from app.models.calc_runs import CalcRun, CalcRunResult, CalcRunStep
from app.models.calc_synthesis import CalcSynthesisDecision, CalcSynthesisRun
from app.models.control_plane import FeatureFlagOverride, SettingOverride
from app.models.doc_question import DocQuestionAnswer, DocQuestionCandidate
from app.models.document import Document, DocumentRevision
from app.models.frame_node import FrameNode
from app.models.identity import (
    AuthSession,
    LocalCredential,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from app.models.job import Job
from app.models.page_geometry import PageGeometry
from app.models.project import Project
from app.models.revision_page_text import RevisionPageText
from app.models.scale import ScaleCalibration
from app.models.sheet import Region, Sheet
from app.models.sheet_passport import SheetPassport
from app.models.sheet_register import SheetRegister
from app.models.takeoff import Measurement, TakeoffItem
from app.models.tender_version import TenderVersion, TenderVersionDocument
from app.models.worker import Worker

__all__ = [
    "AuditEvent",
    "AuthSession",
    "CadConstructionProps",
    "CadDecision",
    "CadFinishTemplate",
    "CadProjectLevels",
    "CadRemark",
    "CadSectionLevel",
    "CadSheetLevels",
    "CadSheetRisers",
    "CadSlabHoleDecision",
    "CadVorDocument",
    "CadVorItem",
    "CadVorLink",
    "CadZone",
    "CalcExpectedQuantity",
    "CalcFact",
    "CalcFactConflict",
    "CalcFactEvidence",
    "CalcManualOverride",
    "CalcPassport",
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
    "DocQuestionAnswer",
    "DocQuestionCandidate",
    "Document",
    "DocumentRevision",
    "FeatureFlagOverride",
    "FrameNode",
    "Job",
    "LocalCredential",
    "Measurement",
    "PageGeometry",
    "Project",
    "RecognitionArtifact",
    "Region",
    "RevisionPageText",
    "ScaleCalibration",
    "SettingOverride",
    "Sheet",
    "SheetPassport",
    "SheetRegister",
    "TakeoffItem",
    "TenderVersion",
    "TenderVersionDocument",
    "UserIdentity",
    "Worker",
    "Workspace",
    "WorkspaceMembership",
]
