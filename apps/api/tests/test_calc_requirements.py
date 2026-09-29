"""Каталог исходных данных ВК и матрица готовности (ADR-0030, PROMPT 02) — без базы.

Главное свойство матрицы: «не найдено» (MISSING) звучит только после проверки документов, а
документ, который ещё не смотрели, даёт NOT_INSPECTED. И ни одно состояние не превращает
отсутствие в ноль.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDocumentStage,
    CalcFactMethod,
    CalcFactStatus,
    CalcInspectionIssueCode,
    CalcReadinessStatus,
    CalcRequirementLevel,
    CalcRequirementScope,
    CalcReviewStatus,
    CalcSourceClass,
)
from app.contracts.calc.fact_types import REGISTRY, check_subject
from app.contracts.calc.inspections import CalcInspectionIssueRead
from app.contracts.calc.requirements import CalcInputRequirement
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcCountValue, CalcFactValue, CalcNumberValue
from app.services.calc.adapters.pipeline import DOCUMENT_FACT_TYPES
from app.services.calc.facts.policy import policy_for
from app.services.calc.facts.resolution import ClaimView, resolve
from app.services.calc.readiness import (
    DocumentState,
    KeyState,
    compute_readiness,
    derivable_types,
    evaluate,
)
from app.services.calc.systems.vk.requirements import (
    VK_REQUIREMENTS,
    VK_REQUIREMENTS_VERSION,
    VK_SYSTEMS,
    requirements_for,
)

T0 = datetime(2026, 9, 28, tzinfo=UTC)


def _requirement(requirement_id: str) -> CalcInputRequirement:
    return next(item for item in VK_REQUIREMENTS if item.id == requirement_id)


class TestCatalog:
    def test_ids_are_unique(self) -> None:
        ids = [item.id for item in VK_REQUIREMENTS]
        assert len(ids) == len(set(ids))

    def test_each_system_asks_each_fact_once(self) -> None:
        for system in VK_SYSTEMS:
            types = [item.fact_type for item in requirements_for(system.code)]
            assert len(types) == len(set(types)), system.code

    def test_requirements_reference_registered_facts_of_the_right_scope(self) -> None:
        subjects = {
            CalcRequirementScope.BUILDING: CalcFactSubject(building="1"),
            CalcRequirementScope.FLOOR: CalcFactSubject(building="1", floor="3"),
        }
        codes = {system.code for system in VK_SYSTEMS}
        for item in VK_REQUIREMENTS:
            definition = REGISTRY.get(item.fact_type)
            assert definition is not None, item.id
            assert set(item.systems) <= codes, item.id
            assert all(fact_type in REGISTRY for fact_type in item.derivable_from), item.id
            if item.scope is CalcRequirementScope.SYSTEM:
                assert "system_code" in definition.required_subject, item.id
                continue
            subject = subjects[item.scope]
            if definition.qualifier_options:
                subject = subject.model_copy(
                    update={"qualifier": definition.qualifier_options[0].value}
                )
            assert check_subject(definition, subject) is None, item.id

    def test_derivable_level_says_from_what(self) -> None:
        for item in VK_REQUIREMENTS:
            if item.level is CalcRequirementLevel.DERIVABLE:
                assert item.derivable_from, item.id

    def test_every_system_has_required_inputs(self) -> None:
        for system in VK_SYSTEMS:
            levels = {item.level for item in requirements_for(system.code)}
            assert CalcRequirementLevel.REQUIRED in levels, system.code

    def test_catalog_has_no_calculation(self) -> None:
        """Каталог — декларация: в нём нет чисел, коэффициентов и норм."""
        for item in VK_REQUIREMENTS:
            text = re.sub(r"[ВТК]\d|±0,000", "", item.description)
            assert not any(char.isdigit() for char in text), item.id


def _claim(
    value: CalcFactValue,
    *,
    source_class: CalcSourceClass = CalcSourceClass.APARTMENT_SCHEDULE,
    eligible: bool = True,
) -> ClaimView:
    return ClaimView(
        id=uuid.uuid4(),
        value=value,
        method=CalcFactMethod.TABLE_COUNTED,
        confidence=CalcConfidence.MEDIUM,
        source_class=source_class,
        document_stage=CalcDocumentStage.P,
        source_content_sha256=None,
        review_status=CalcReviewStatus.UNREVIEWED,
        status=CalcFactStatus.ACTIVE,
        calculation_eligible=eligible,
        created_at=T0,
        source_id=uuid.uuid4(),
    )


def _key(fact_type: str, subject: CalcFactSubject, *claims: ClaimView) -> KeyState:
    definition = REGISTRY[fact_type]
    return KeyState(
        fact_key=f"{fact_type}@{subject.key()}",
        fact_type=fact_type,
        subject=subject,
        resolution=resolve(definition, list(claims), None, policy_for(fact_type)),
        conflict_id=None,
        source_title="Квартирография",
        source_class=CalcSourceClass.APARTMENT_SCHEDULE,
    )


def _document(
    *,
    inspected: bool = True,
    recognized: bool = True,
    declared: CalcSourceClass | None = CalcSourceClass.ARCHITECTURE,
    issues: tuple[CalcInspectionIssueRead, ...] = (),
) -> DocumentState:
    return DocumentState(
        recognized=recognized,
        latest=True,
        inspected_fact_types=DOCUMENT_FACT_TYPES if inspected else None,
        declared_class=declared if inspected else None,
        issues=issues,
    )


def _status(
    requirement_id: str,
    keys: list[KeyState],
    documents: list[DocumentState],
    system: str = "В1",
    present: frozenset[CalcSourceClass] = frozenset({CalcSourceClass.ARCHITECTURE}),
) -> tuple[CalcReadinessStatus, str | None, int]:
    row = evaluate(
        _requirement(requirement_id), system, keys, documents, present, lambda item: item.value
    )
    return row.status, row.reason, len(row.values)


FLOOR = CalcFactSubject(building="1", floor="3")
APARTMENTS = "floor.apartments_count"


class TestReadiness:
    def test_found(self) -> None:
        keys = [_key(APARTMENTS, FLOOR, _claim(CalcCountValue(value=9)))]
        status, _, values = _status("vk.apartments.per_floor", keys, [_document()])
        assert (status, values) == (CalcReadinessStatus.FOUND, 1)

    def test_inspected_document_without_value_is_missing(self) -> None:
        status, reason, values = _status("vk.apartments.per_floor", [], [_document()])
        assert status is CalcReadinessStatus.MISSING
        assert reason == "Проверено документов: 1 — не найдено"
        # MISSING не ноль: значения нет вовсе.
        assert values == 0

    def test_uninspected_document_is_not_a_false_missing(self) -> None:
        documents = [_document(), _document(inspected=False)]
        status, reason, _ = _status("vk.apartments.per_floor", [], documents)
        assert status is CalcReadinessStatus.NOT_INSPECTED
        assert reason == "Не проверено документов: 1 из 2"

    def test_project_composition_does_not_make_facts_uninspected(self) -> None:
        composition = DocumentState(
            recognized=True,
            latest=True,
            inspected_fact_types=frozenset(),
            declared_class=CalcSourceClass.PROJECT_COMPOSITION,
            issues=(),
        )
        status, reason, _ = _status("vk.apartments.per_floor", [], [_document(), composition])
        assert status is CalcReadinessStatus.MISSING
        assert reason == "Проверено документов: 1 — не найдено"

    def test_no_recognized_documents_is_unknown(self) -> None:
        documents = [_document(recognized=False, inspected=False)]
        status, reason, _ = _status("vk.apartments.per_floor", [], documents)
        assert (status, reason) == (
            CalcReadinessStatus.UNKNOWN,
            "В проекте нет распознанных документов",
        )

    def test_found_but_unattributed_value_is_unknown(self) -> None:
        issue = CalcInspectionIssueRead(
            code=CalcInspectionIssueCode.UNSCOPED,
            fact_type=APARTMENTS,
            message="Экспликация без этажа: «Экспликация квартир типового этажа»",
            count=1,
        )
        status, reason, _ = _status("vk.apartments.per_floor", [], [_document(issues=(issue,))])
        assert status is CalcReadinessStatus.UNKNOWN
        assert reason is not None and "типового этажа" in reason

    def test_disagreeing_sources_are_conflicted(self) -> None:
        keys = [
            _key(
                APARTMENTS,
                FLOOR,
                _claim(CalcCountValue(value=9)),
                _claim(CalcCountValue(value=8)),
            )
        ]
        status, _, values = _status("vk.apartments.per_floor", keys, [_document()])
        assert (status, values) == (CalcReadinessStatus.CONFLICTED, 1)

    def test_derivable_from_found_facts(self) -> None:
        keys = [_key(APARTMENTS, FLOOR, _claim(CalcCountValue(value=9)))]
        status, reason, _ = _status("vk.apartments.total", keys, [_document()])
        assert status is CalcReadinessStatus.DERIVABLE
        assert reason is not None and "квартир на этаже" in reason

    def test_derivation_follows_chains(self) -> None:
        """Отметки этажей → высоты этажей → высота здания: выводимо по цепочке."""
        elevation = _key("floor.elevation", FLOOR, _claim(CalcNumberValue(value="6.600", unit="m")))
        catalog = [item for system in VK_SYSTEMS for item in requirements_for(system.code)]
        available = derivable_types([elevation], catalog)
        assert {"floor.height", "building.height"} <= available
        row = evaluate(
            _requirement("vk.building.height"),
            "В1",
            [elevation],
            [_document()],
            frozenset(),
            lambda item: item.value,
            available,
        )
        assert row.status is CalcReadinessStatus.DERIVABLE

    def test_head_without_technical_conditions_needs_manual_input(self) -> None:
        status, reason, _ = _status("vk.b1.inlet_pressure", [], [_document()], present=frozenset())
        assert status is CalcReadinessStatus.MANUAL_REQUIRED
        assert reason == "TECHNICAL_CONDITIONS в проекте не найдены — нужен ручной ввод"

    def test_head_with_technical_conditions_is_looked_for(self) -> None:
        conditions = frozenset({CalcSourceClass.TECHNICAL_CONDITIONS})
        status, _, _ = _status("vk.b1.inlet_pressure", [], [_document()], present=conditions)
        assert status is CalcReadinessStatus.MISSING

    def test_not_extractable_fact_asks_for_manual_input(self) -> None:
        status, reason, _ = _status("vk.t3.source", [], [_document()], system="Т3")
        assert status is CalcReadinessStatus.MANUAL_REQUIRED
        assert reason is not None and reason.startswith("Автоматически не извлекается")

    def test_system_facts_belong_to_their_system(self) -> None:
        subject = CalcFactSubject(building="1", discipline="VK", system_code="К1")
        keys = [_key("system.pipe_material", subject, _claim(CalcNumberValue(value="1", unit="m")))]
        assert _status("vk.water.material", keys, [_document()])[0] is not (
            CalcReadinessStatus.FOUND
        )

    def test_customer_vor_is_counted_apart_and_never_found(self) -> None:
        subject = CalcFactSubject(building="1", discipline="VK", system_code="В1")
        vor = _claim(
            CalcNumberValue(value="1", unit="m"),
            source_class=CalcSourceClass.CUSTOMER_VOR,
            eligible=False,
        )
        keys = [_key("system.main_diameter", subject, vor)]
        row = evaluate(
            _requirement("vk.water.main_diameter"),
            "В1",
            keys,
            [_document()],
            frozenset(),
            lambda item: item.value,
        )
        assert row.status is not CalcReadinessStatus.FOUND
        assert row.values == []
        assert row.excluded_count == 1

    @pytest.mark.parametrize("system", ["В1", "Т3", "Т4", "К1"])
    def test_counts_split_by_level(self, system: str) -> None:
        keys = [_key(APARTMENTS, FLOOR, _claim(CalcCountValue(value=9)))]
        readiness = compute_readiness(
            version=VK_REQUIREMENTS_VERSION,
            systems=[item for item in VK_SYSTEMS if item.code == system],
            requirements_for=requirements_for,
            keys=keys,
            documents=[_document()],
            present_classes=frozenset(),
            class_titles=lambda item: item.value,
        )
        [matrix] = readiness.systems
        required = next(
            count for count in matrix.counts if count.level is CalcRequirementLevel.REQUIRED
        )
        # Квартиры на этажах найдены — одно закрытое обязательное. Всего квартир в каталоге v2
        # (PROMPT 06) желательное: оно выводимо и нужно только для сверки с итогом документа.
        assert required.satisfied == 1
        assert required.total == sum(
            1 for item in requirements_for(system) if item.level is CalcRequirementLevel.REQUIRED
        )
        desirable = next(
            count for count in matrix.counts if count.level is CalcRequirementLevel.DESIRABLE
        )
        assert desirable.satisfied >= 1
