"""Комплект расчёта ВК стадии П (PROMPT 06): оркестратор над ядром и синтезом.

Для каждой системы комплекта:

1. назначение обозначения — только по документации (`system.function`); не подтверждено —
   паспорт BLOCKED с вопросом, расчёт не запускается;
2. три сценария — три запуска калькулятора `vk.<система>.stage_p@1` ядром PROMPT 04 и три
   запуска синтеза PROMPT 05 (ядро и синтез не обходятся);
3. позиции паспорта из графа и результатов (слой D);
4. паспорт — разделы, статус, отпечаток; вместе с позициями записывается один раз.

ВОР Заказчика здесь не читается ни в каком виде: снимок ядра его не допускает, а сверки нет.
Запуск синхронный, одной транзакцией запроса, как запуски ядра и синтеза.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.engine import CalcRunCreate, CalcRunRead
from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcRunStatus,
    CalcScenario,
    CalcSemanticsStatus,
)
from app.contracts.calc.passport import CalcExpectedQuantityBody, CalcPassportRun, CalcVkRunCreate
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcSynthesisRunCreate, CalcSynthesisRunRead
from app.errors import DomainError, ErrorCode
from app.models import CalcExpectedQuantity, CalcPassport, Project
from app.services.calc import readiness as input_readiness
from app.services.calc.engine import runs as engine_runs
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.catalog import CALCULATORS
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.reads import run_read as calculation_read
from app.services.calc.synthesis import reads as synthesis_reads
from app.services.calc.synthesis import runs as synthesis_runs
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.systems.vk.graph_parts import text_of
from app.services.calc.systems.vk.passport import PassportInputs, ScenarioOutcome, assemble
from app.services.calc.systems.vk.readiness import rule_matrix, semantics_of
from app.services.calc.systems.vk.requirements import (
    VK_REQUIREMENTS_VERSION,
    VK_SYSTEMS,
    requirements_for,
)
from app.services.calc.systems.vk.spec import VK_SPECS, VkSystemSpec
from app.services.calc.systems.vk.volume_base import VolumeInputs
from app.services.calc.systems.vk.volumes import generate

SCENARIOS: Final = (CalcScenario.MINIMUM, CalcScenario.EXPECTED, CalcScenario.TENDER_SAFE)


def _request_sha256(payload: CalcVkRunCreate) -> str:
    return canonical_sha256(
        {
            "building": payload.building,
            "section": payload.section,
            "systems": sorted(payload.systems),
        }
    )


async def _lock(session: AsyncSession, name: str) -> None:
    digest = hashlib.sha256(name.encode()).digest()
    await session.execute(
        select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True)))
    )


def _rule_refs(run: CalcRunRead) -> dict[str, str]:
    bindings = {item.step_key: f"{item.rule_key}@{item.version}" for item in run.rule_bindings}
    return {
        item.result_key: bindings[item.step_key]
        for item in run.results
        if item.step_key in bindings
    }


def blocked_steps(definition: CalculatorDef, run: CalcRunRead) -> dict[str, tuple[str, ...]]:
    """Шаг без результата → корневые шаги с собственной причиной блокировки."""
    executed = {item.step_key for item in run.steps}
    own = {item.step_key for item in run.blocking_reasons if item.step_key}
    steps = {step.step_key: step for step in definition.steps}
    cache: dict[str, tuple[str, ...]] = {}

    def roots(key: str) -> tuple[str, ...]:
        if key in cache:
            return cache[key]
        if key in own or key not in steps:
            found: tuple[str, ...] = (key,)
        else:
            found = tuple(
                dict.fromkeys(
                    root
                    for dependency in steps[key].depends_on
                    if dependency not in executed
                    for root in roots(dependency)
                )
            ) or (key,)
        cache[key] = found
        return found

    return {key: roots(key) for key in steps if key not in executed}


def _material(synthesis: CalcSynthesisRunRead | None) -> str | None:
    if synthesis is None:
        return None
    item = next(
        (row for row in synthesis.snapshot.items if row.fact_type == "system.pipe_material"), None
    )
    return None if item is None else text_of(item)


async def _scenario(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    spec: VkSystemSpec,
    scope: CalcFactSubject,
    scenario: CalcScenario,
    author: uuid.UUID | None,
) -> ScenarioOutcome:
    run, _ = await engine_runs.start_run(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=CalcRunCreate(
            calculator_id=spec.calculator_id,
            calculator_version=spec.version,
            scenario=scenario,
            scope=scope,
        ),
        author=author,
    )
    calculation = calculation_read(run)
    synthesis_read: CalcSynthesisRunRead | None = None
    graph = None
    synthesis_id: uuid.UUID | None = None
    if run.status in (CalcRunStatus.SUCCEEDED, CalcRunStatus.PARTIAL):
        synthesis, _ = await synthesis_runs.start(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=CalcSynthesisRunCreate(
                calculation_run_id=run.id,
                synthesizer_id=spec.synthesizer_id,
                synthesizer_version=spec.version,
            ),
            author=author,
        )
        synthesis_id = synthesis.id
        synthesis_read = synthesis_reads.run_read(synthesis, [])
        graph = synthesis_reads.graph_read(synthesis)
    definition = CALCULATORS[(spec.calculator_id, spec.version)]
    rows = generate(
        VolumeInputs(
            spec=spec,
            scenario=scenario,
            scope=scope,
            graph=graph,
            results={item.result_key: item for item in calculation.results},
            assumptions=tuple(calculation.assumptions),
            calculation_run_id=run.id,
            synthesis_run_id=synthesis_id,
            material=_material(synthesis_read),
            rule_refs=_rule_refs(calculation),
            blocked_steps=blocked_steps(definition, calculation),
        )
    )
    return ScenarioOutcome(scenario, calculation, synthesis_read, graph, tuple(rows))


def passport_sha256(body: dict[str, object], rows: Sequence[CalcExpectedQuantityBody]) -> str:
    """Отпечаток содержания: без идентификаторов запусков — одинаковые входы, один отпечаток."""
    return canonical_sha256(
        {
            "body": body,
            "rows": [
                row.model_dump(mode="json", exclude={"calculation_run_id", "synthesis_run_id"})
                for row in rows
            ],
        }
    )


async def _existing(session: AsyncSession, project_id: uuid.UUID, key: str) -> list[CalcPassport]:
    return list(
        await session.scalars(
            select(CalcPassport)
            .where(CalcPassport.project_id == project_id, CalcPassport.idempotency_key == key)
            .order_by(CalcPassport.created_at, CalcPassport.id)
        )
    )


async def start(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project: Project,
    payload: CalcVkRunCreate,
    author: uuid.UUID | None,
) -> tuple[uuid.UUID, list[CalcPassport], bool]:
    """Новый комплект паспортов или уже созданный по тому же ключу (третье — False)."""
    request_sha256 = _request_sha256(payload)
    if payload.idempotency_key is not None:
        await _lock(session, f"calc-vk|{project.id}|{payload.idempotency_key}")
        existing = await _existing(session, project.id, payload.idempotency_key)
        if existing:
            if any(item.request_sha256 != request_sha256 for item in existing):
                raise DomainError(ErrorCode.CALC_RUN_IDEMPOTENCY_CONFLICT)
            return existing[0].batch_id, existing, False
    specs = [spec for spec in VK_SPECS if spec.code in payload.systems]
    readiness = await input_readiness.load_readiness(
        session,
        project=project,
        version=VK_REQUIREMENTS_VERSION,
        systems=[item for item in VK_SYSTEMS if item.code in payload.systems],
        requirements_for=requirements_for,
    )
    by_code = {item.system_code: item for item in readiness.systems}
    today = datetime.now(UTC).date()
    batch_id = uuid.uuid4()
    passports: list[CalcPassport] = []
    for spec in specs:
        scope = CalcFactSubject(
            building=payload.building,
            section=payload.section,
            discipline=CalcDiscipline.VK,
            system_code=spec.code,
        )
        semantics, note, _ = await semantics_of(
            session, project_id=project.id, spec=spec, building=payload.building
        )
        outcomes: dict[CalcScenario, ScenarioOutcome] = {}
        if semantics is CalcSemanticsStatus.CONFIRMED:
            for scenario in SCENARIOS:
                outcomes[scenario] = await _scenario(
                    session,
                    workspace_id=workspace_id,
                    project_id=project.id,
                    spec=spec,
                    scope=scope,
                    scenario=scenario,
                    author=author,
                )
        rules = await rule_matrix(
            session, workspace_id=workspace_id, system_code=spec.code, on=today
        )
        status, body = assemble(
            PassportInputs(
                spec=spec,
                scope=scope,
                semantics=semantics,
                semantics_note=note,
                readiness=by_code.get(spec.code),
                rules=tuple(rules),
                outcomes=outcomes,
                definition=CALCULATORS[(spec.calculator_id, spec.version)],
            )
        )
        rows = [row for outcome in outcomes.values() for row in outcome.rows]
        body_json = body.model_dump(mode="json")
        synthesizer = SYNTHESIZERS[(spec.synthesizer_id, spec.version)]
        passport = CalcPassport(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            project_id=project.id,
            batch_id=batch_id,
            system_code=spec.code,
            system_title=spec.title,
            discipline=CalcDiscipline.VK,
            scope=scope.model_dump(mode="json"),
            scope_key=scope.key(),
            status=status,
            calculator_id=spec.calculator_id,
            calculator_version=spec.version,
            calculator_sha256=CALCULATORS[(spec.calculator_id, spec.version)].sha256,
            synthesizer_id=spec.synthesizer_id,
            synthesizer_version=spec.version,
            implementation_sha256=synthesizer.implementation_sha256,
            runs=[
                CalcPassportRun(
                    scenario=outcome.scenario,
                    calculation_run_id=None
                    if outcome.calculation is None
                    else outcome.calculation.id,
                    calculation_status=None
                    if outcome.calculation is None
                    else outcome.calculation.status,
                    synthesis_run_id=None if outcome.synthesis is None else outcome.synthesis.id,
                    synthesis_status=None
                    if outcome.synthesis is None
                    else outcome.synthesis.status,
                ).model_dump(mode="json")
                for outcome in outcomes.values()
            ],
            body=body_json,
            passport_sha256=passport_sha256(body_json, rows),
            quantities_count=len(rows),
            idempotency_key=payload.idempotency_key,
            request_sha256=request_sha256,
            created_by=author,
            quantities=[],
        )
        passport.quantities = [
            _quantity_row(passport.id, position, row) for position, row in enumerate(rows)
        ]
        session.add(passport)
        passports.append(passport)
    await session.flush()
    return batch_id, passports, True


def _quantity_row(
    passport_id: uuid.UUID, position: int, row: CalcExpectedQuantityBody
) -> CalcExpectedQuantity:
    return CalcExpectedQuantity(
        passport_id=passport_id,
        position=position,
        quantity_key=row.quantity_key,
        scenario=row.scenario,
        system_code=row.system_code,
        category=row.category,
        item_type=row.item_type,
        completeness=row.completeness,
        derivation=row.derivation,
        unit=row.unit,
        value=row.amount.value,
        low=row.amount.low,
        high=row.amount.high,
        size=row.size,
        material=row.material,
        calculation_run_id=row.calculation_run_id,
        synthesis_run_id=row.synthesis_run_id,
        body=row.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------------- чтение


async def get(
    session: AsyncSession, *, workspace_id: uuid.UUID, passport_id: uuid.UUID
) -> CalcPassport | None:
    result = await session.scalars(
        select(CalcPassport)
        .where(CalcPassport.id == passport_id, CalcPassport.workspace_id == workspace_id)
        .options(selectinload(CalcPassport.quantities))
    )
    return result.one_or_none()


async def list_for_project(session: AsyncSession, *, project_id: uuid.UUID) -> list[CalcPassport]:
    return list(
        await session.scalars(
            select(CalcPassport)
            .where(CalcPassport.project_id == project_id)
            .order_by(CalcPassport.created_at.desc(), CalcPassport.system_code)
        )
    )


async def quantity(
    session: AsyncSession, *, workspace_id: uuid.UUID, quantity_id: uuid.UUID
) -> tuple[CalcExpectedQuantity, CalcPassport] | None:
    row = await session.get(CalcExpectedQuantity, quantity_id)
    if row is None:
        return None
    passport = await session.get(CalcPassport, row.passport_id)
    if passport is None or passport.workspace_id != workspace_id:
        return None
    return row, passport
