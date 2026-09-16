"""Контракты MEP-эксперимента П → РД → ВОР, версия 0.3 (ADR-0027, ADR-0028).

Три слоя не смешиваются:

```text
MepEvidenceGraph   что показано на листе П или подтверждено человеком
InferenceStep      почему генератор принял решение: входы, метод, уверенность
MepNetworkGraph    сгенерированная система уровня РД со ссылками на шаги и evidence
```

Ядро не знает дисциплины: классы, атрибуты, типы связей и систем приходят из
`MepSystemProfile`. Здесь только типы и проверки — ни модели, ни эндпоинта, ни таблицы.
"""

from app.contracts.mep.common import (
    CONTRACT_VERSION,
    ContractIssue,
    IssueSeverity,
    SubjectKind,
    SubjectRef,
    calibration_fingerprint,
    canonical_sha256,
)
from app.contracts.mep.evidence import EvidenceInputMode, MepEvidenceGraph
from app.contracts.mep.network import GenerationProvenance, MepNetworkGraph
from app.contracts.mep.network_validation import validate_network_graph
from app.contracts.mep.profile import MepSystemProfile
from app.contracts.mep.validation import validate_evidence_graph, validate_profile

__all__ = [
    "CONTRACT_VERSION",
    "ContractIssue",
    "EvidenceInputMode",
    "GenerationProvenance",
    "IssueSeverity",
    "MepEvidenceGraph",
    "MepNetworkGraph",
    "MepSystemProfile",
    "SubjectKind",
    "SubjectRef",
    "calibration_fingerprint",
    "canonical_sha256",
    "validate_evidence_graph",
    "validate_network_graph",
    "validate_profile",
]
