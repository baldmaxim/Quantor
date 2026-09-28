"""Реестр правил без базы (ADR-0030, PROMPT 03).

Карантин 365 правил старого портала, его упаковка и воспроизводимость; контракты правил без
исполняемого кода; единицы и размерности; условия утверждения по типу правила; разбор
опасностей старых правил; независимость от реестра фактов и ВОР Заказчика.
"""

from __future__ import annotations

import ast
import asyncio
import fnmatch
import json
import os
import re
import sys
import tomllib
import zipfile
from collections import Counter
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.calc.enums import (
    CalcHazardOutcome,
    CalcLegacyAction,
    CalcLegacyCatalog,
    CalcLegacyClass,
    CalcLegacyHazard,
    CalcRuleStatus,
    CalcRuleType,
)
from app.contracts.calc.rules import (
    LEGACY_NOTICE,
    TENDER_NOTICE,
    CalcLegacyResolution,
    CalcRuleApprove,
    CalcRuleContent,
    CalcRuleFromLegacy,
)
from app.core.config import REPO_ROOT
from app.core.features import REGISTRY as FEATURES
from app.services.calc.rules import legacy as legacy_module
from app.services.calc.rules import legacy_build, validation
from app.services.calc.rules.legacy import (
    LegacyCatalogError,
    catalog_read,
    load_catalog,
    read_packaged_text,
)
from app.services.calc.rules.registry import draft_from_legacy
from tests.calc_rule_fixtures import (
    content,
    decision_source,
    engineering_source,
    geometry_content,
    manufacturer_source,
    normative_source,
)

API_ROOT = Path(__file__).resolve().parents[1]
RULES_PACKAGE = API_ROOT / "app" / "services" / "calc" / "rules"
RULES_MODULES = [*sorted(RULES_PACKAGE.glob("*.py")), API_ROOT / "app/api/v1/calc_rules.py"]

# Разбор PROMPT 00 (docs/calc/00-legacy-portal-analysis.md, раздел 5): итоговая строка таблицы.
P00_BY_CATALOG = {"K": 124, "OV": 79, "VK": 60, "VRF": 54, "FIRE": 48}
P00_BY_CLASS = {
    "HEURISTIC": 181,
    "UNKNOWN_ORIGIN": 54,
    "ERROR": 52,
    "GEOMETRY": 37,
    "TENDER": 26,
    "PHYSICS": 14,
    "NONE": 1,
}


def _approve(*reviews: CalcLegacyResolution) -> CalcRuleApprove:
    return CalcRuleApprove(comment="Проверено по тестовому документу.", legacy_review=list(reviews))


def _problems(rule: CalcRuleContent, *reviews: CalcLegacyResolution) -> list[str]:
    return validation.approval_problems(rule, _approve(*reviews), load_catalog())


# ------------------------------------------------------------------------ карантин (T02, T13)


class TestLegacyQuarantine:
    def test_t02_every_legacy_rule_is_unverified_and_not_eligible(self) -> None:
        items = load_catalog().items
        assert items
        assert all(item.status is CalcRuleStatus.UNVERIFIED_LEGACY for item in items)
        assert not any(item.calculation_eligible for item in items)
        assert {item.notice for item in items} == {LEGACY_NOTICE}

    def test_t13_all_365_rules_match_the_prompt00_catalog(self) -> None:
        """Число и идентификаторы сверяются с разбором независимым способом — простым поиском."""
        catalog = load_catalog()
        ids = [item.legacy_id for item in catalog.items]
        assert len(ids) == 365 == len(set(ids))

        in_docs: list[str] = []
        for path in sorted((REPO_ROOT / "docs" / "calc" / "legacy").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            in_docs.extend(re.findall(r"^\| (LEG-[A-Z0-9]+-\d{3}) \|", text, re.MULTILINE))
        assert sorted(in_docs) == sorted(ids)

        assert Counter(item.catalog.value for item in catalog.items) == P00_BY_CATALOG
        assert Counter(item.class_primary.value for item in catalog.items) == P00_BY_CLASS

    def test_origin_classification_and_action_are_kept(self) -> None:
        for item in load_catalog().items:
            assert item.location and item.code_refs, item.legacy_id
            assert item.rule_text and item.class_raw and item.action_raw, item.legacy_id
            assert item.actions, item.legacy_id

    def test_t14_conflicting_implementations_stay_separate(self) -> None:
        """Одна логика с разными константами: оригиналы не схлопываются, группа их связывает."""
        catalog = load_catalog()
        groups = {group.group_id: group for group in catalog.groups}
        assert set(groups) == {
            "LG-VK-COMPENSATORS",
            "LG-VK-COLLECTORS",
            "LG-K1-PIPE",
            "LG-OV-ESTIMATE",
        }
        for group in groups.values():
            members = [catalog.get(member) for member in group.members]
            assert all(member is not None for member in members)
            texts = {member.rule_text for member in members if member is not None}
            assert len(texts) == len(group.members), group.group_id
            for member in members:
                assert member is not None
                assert group.group_id in member.group_ids
                assert CalcLegacyHazard.CONFLICTING_CONSTANTS in member.hazards
        assert "803,4" in groups["LG-K1-PIPE"].finding

    @pytest.mark.parametrize(
        ("legacy_id", "hazard"),
        [
            ("LEG-OV-037", CalcLegacyHazard.DOUBLE_MULTIPLICATION),
            ("LEG-VK-001", CalcLegacyHazard.HIDDEN_DEFAULT),
            ("LEG-VK-005", CalcLegacyHazard.SUBSTITUTED_VALUES),
            ("LEG-VK-033", CalcLegacyHazard.UNIT_ERROR),
            ("LEG-VK-027", CalcLegacyHazard.CONFLICTING_CONSTANTS),
        ],
    )
    def test_known_legacy_errors_are_flagged(
        self, legacy_id: str, hazard: CalcLegacyHazard
    ) -> None:
        entry = load_catalog().get(legacy_id)
        assert entry is not None and hazard in entry.hazards

    def test_error_class_always_carries_defect(self) -> None:
        for item in load_catalog().items:
            if CalcLegacyClass.ERROR in (item.class_primary, *item.class_secondary):
                assert CalcLegacyHazard.DEFECT in item.hazards, item.legacy_id

    def test_filters(self) -> None:
        assert len(catalog_read(catalog=CalcLegacyCatalog.K).items) == 124
        doubled = catalog_read(hazard=CalcLegacyHazard.DOUBLE_MULTIPLICATION).items
        assert doubled and all(
            CalcLegacyHazard.DOUBLE_MULTIPLICATION in item.hazards for item in doubled
        )
        outside = catalog_read(action=CalcLegacyAction.OUT_OF_SCOPE).items
        assert {item.legacy_id for item in outside} >= {"LEG-EST-024", "LEG-OV-071"}
        assert len(catalog_read(group_id="LG-VK-COLLECTORS").items) == 5
        assert catalog_read().entry_count == 365


# -------------------------------------------------------------- упаковка и воспроизводимость


class TestPackaging:
    def test_t23_catalog_loads_from_package_resource(self) -> None:
        """Тот же загрузчик, что у рабочего кода: importlib.resources, а не путь к репозиторию."""
        resource = files("app.services.calc.rules").joinpath("data", "legacy_catalog.json")
        assert resource.is_file()
        assert read_packaged_text() == resource.read_text("utf-8")
        catalog = load_catalog()
        assert catalog.catalog_version == "calc.legacy_catalog.v1"
        assert catalog.generator_version == "calc.legacy_build.v1"
        assert len(catalog.items) == 365

    def test_t23_package_data_declares_the_catalog(self) -> None:
        """Файл попадает в колесо: его путь подходит под шаблон данных пакета в pyproject."""
        with (API_ROOT / "pyproject.toml").open("rb") as stream:
            declared = tomllib.load(stream)["tool"]["setuptools"]["package-data"]
        patterns = declared["app.services.calc.rules"]
        assert any(fnmatch.fnmatch("data/legacy_catalog.json", item) for item in patterns)

    async def test_t23_catalog_loads_from_a_zipped_package(self, tmp_path: Path) -> None:
        """Как после установки: пакет без рабочей копии рядом, данные — только по шаблону
        package-data, чтение — из zip через importlib.resources, в отдельном процессе."""
        with (API_ROOT / "pyproject.toml").open("rb") as stream:
            patterns = tomllib.load(stream)["tool"]["setuptools"]["package-data"][
                "app.services.calc.rules"
            ]
        archive = tmp_path / "quantor_app.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for path in sorted((API_ROOT / "app").rglob("*.py")):
                bundle.write(path, path.relative_to(API_ROOT).as_posix())
            for pattern in patterns:
                for path in sorted(RULES_PACKAGE.glob(pattern)):
                    bundle.write(path, path.relative_to(API_ROOT).as_posix())
        code = (
            "import app.services.calc.rules.legacy as m; c = m.load_catalog(); "
            "print(m.__file__); print(len(c.items))"
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": str(archive)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, errors = await asyncio.wait_for(process.communicate(), timeout=120)
        assert process.returncode == 0, errors.decode("utf-8", errors="replace")
        module_file, count = output.decode("utf-8").split()
        assert module_file.startswith(str(archive))
        assert count == "365"

    def test_corrupted_catalog_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = json.loads(read_packaged_text())
        raw["items"][0]["rule_text"] = "подменено"
        monkeypatch.setattr(legacy_module, "read_packaged_text", lambda: json.dumps(raw))
        load_catalog.cache_clear()
        try:
            with pytest.raises(LegacyCatalogError):
                load_catalog()
            raw["entry_count"] = 364
            with pytest.raises(LegacyCatalogError):
                load_catalog()
        finally:
            monkeypatch.undo()
            load_catalog.cache_clear()
        assert len(load_catalog().items) == 365

    def test_t24_generation_is_deterministic_and_matches_the_package(self) -> None:
        first = legacy_build.build()
        second = legacy_build.build()
        assert first == second
        assert first["entry_count"] == len(first["items"]) == 365
        rendered = legacy_build.render(first)
        # Смысловое равенство и побайтное: каталог в пакете собран из разбора, а не правлен.
        assert json.loads(rendered) == json.loads(read_packaged_text())
        assert rendered == read_packaged_text()

    def test_t24_catalog_has_no_local_paths(self) -> None:
        text = read_packaged_text()
        assert str(REPO_ROOT) not in text
        assert not re.search(r"/home/|/Users/|[A-Z]:\\\\", text)


# ------------------------------------------------------------------- контракты (T10, T11)


class TestContracts:
    def test_valid_fixture_has_no_problems(self) -> None:
        assert validation.content_problems(content(), load_catalog()) == []
        assert _problems(content()) == []

    @pytest.mark.parametrize("field", ["code", "expression", "python", "script"])
    def test_t11_no_executable_fields(self, field: str) -> None:
        with pytest.raises(ValidationError):
            CalcRuleContent.model_validate(geometry_content(**{field: "__import__('os')"}))

    @pytest.mark.parametrize(
        "key",
        ["os.system('x').v1", "__import__.v1", "vk.riser_length", "vk.riser length.v1", "eval.v1x"],
    )
    def test_t11_implementation_key_is_a_name_not_code(self, key: str) -> None:
        with pytest.raises(ValidationError):
            content(implementation_key=key)

    def test_t11_formula_is_text_and_nothing_executes_it(self) -> None:
        """Формула — только текст. В модулях реестра нет ни одного пути исполнения строки."""
        rule = content(formula="__import__('os').system('rm -rf /')")
        assert rule.formula.startswith("__import__")
        forbidden = {"eval", "exec", "compile", "__import__"}
        for path in RULES_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden, f"{path.name}: {node.func.id}"
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr != "import_module", path.name

    def test_t10_incompatible_input_unit(self) -> None:
        rule = geometry_content()
        rule["inputs"][0]["unit"] = "kPa"
        problems = validation.content_problems(content(**rule), load_catalog())
        assert any("не совместима" in item for item in problems)

    def test_t10_unknown_unit(self) -> None:
        rule = geometry_content()
        rule["outputs"][0]["unit"] = "kg"
        problems = validation.content_problems(content(**rule), load_catalog())
        assert any("неизвестная единица" in item for item in problems)

    def test_t10_dimension_mismatch(self) -> None:
        """Метры × давление не проходят как длина."""
        rule = geometry_content()
        rule["inputs"][1] = {
            "name": "floors",
            "kind": "FACT",
            "fact_type": "system.inlet_pressure",
            "unit": "kPa",
            "description": "Давление вместо этажей.",
        }
        problems = validation.content_problems(content(**rule), load_catalog())
        assert any("давление" in item for item in problems)

    def test_t10_non_numeric_fact_has_no_unit(self) -> None:
        rule = geometry_content()
        rule["inputs"].append(
            {
                "name": "material",
                "kind": "FACT",
                "fact_type": "system.pipe_material",
                "unit": "m",
                "description": "Материал.",
            }
        )
        problems = validation.content_problems(content(**rule), load_catalog())
        assert any("нет единицы" in item for item in problems)

    def test_names_do_not_repeat(self) -> None:
        rule = geometry_content()
        rule["parameters"][0]["name"] = "floors"
        with pytest.raises(ValidationError):
            content(**rule)


# ---------------------------------------------------------- утверждение (T04–T06, T12, T22)


class TestApproval:
    def test_t04_normative_needs_a_normative_document(self) -> None:
        rule = content(rule_type="NORMATIVE")
        assert any("нормативного документа" in item for item in _problems(rule))
        assert _problems(content(rule_type="NORMATIVE", sources=[normative_source()])) == []

    @pytest.mark.parametrize("missing", ["designation", "edition", "clause", "edition_date"])
    def test_t04_normative_source_needs_designation_edition_clause_date(self, missing: str) -> None:
        source = normative_source()
        del source[missing]
        with pytest.raises(ValidationError):
            content(rule_type="NORMATIVE", sources=[source])

    def test_t05_manufacturer_needs_manufacturer_document(self) -> None:
        scope = {
            **geometry_content()["applicability"],
            "manufacturer": "Тест-Завод",
            "product_line": "Линейка А",
        }
        without = content(rule_type="MANUFACTURER", applicability=scope)
        assert any("документа производителя" in item for item in _problems(without))

        other = content(
            rule_type="MANUFACTURER",
            applicability=scope,
            sources=[manufacturer_source(manufacturer="Другой завод")],
        )
        assert any("другого производителя" in item for item in _problems(other))

        no_scope = content(rule_type="MANUFACTURER", sources=[manufacturer_source()])
        assert any("производитель и линейка" in item for item in _problems(no_scope))

        good = content(
            rule_type="MANUFACTURER", applicability=scope, sources=[manufacturer_source()]
        )
        assert _problems(good) == []

    def test_t05_manufacturer_document_needs_version(self) -> None:
        source = manufacturer_source()
        del source["document_version"]
        with pytest.raises(ValidationError):
            content(rule_type="MANUFACTURER", sources=[source])

    def test_engineering_needs_method_and_limitations(self) -> None:
        rule = content(rule_type="ENGINEERING", sources=[decision_source()])
        problems = _problems(rule)
        assert any("без методики" in item for item in problems)
        assert any("ограничения" in item for item in problems)
        scope = {**geometry_content()["applicability"], "limitations": ["до 25 этажей"]}
        good = content(rule_type="ENGINEERING", applicability=scope, sources=[engineering_source()])
        assert _problems(good) == []

    def test_t06_tender_assumption_is_its_own_kind(self) -> None:
        assert validation.notice(CalcRuleType.TENDER_ASSUMPTION) == TENDER_NOTICE
        for rule_type in CalcRuleType:
            if rule_type is not CalcRuleType.TENDER_ASSUMPTION:
                assert validation.notice(rule_type) is None

        # Методика не заменяет решения ответственного лица.
        scope = {**geometry_content()["applicability"], "limitations": ["только стадия П"]}
        method_only = content(
            rule_type="TENDER_ASSUMPTION",
            applicability=scope,
            impact="Длина больше на 10 %.",
            sources=[engineering_source()],
        )
        assert any("решения ответственного лица" in item for item in _problems(method_only))
        no_impact = content(
            rule_type="TENDER_ASSUMPTION", applicability=scope, sources=[decision_source()]
        )
        assert any("влияние" in item for item in _problems(no_impact))
        good = content(
            rule_type="TENDER_ASSUMPTION",
            applicability=scope,
            impact="Длина больше на 10 %.",
            sources=[decision_source()],
        )
        assert _problems(good) == []

    def test_t12_approval_needs_implementation_and_basis(self) -> None:
        no_key = content(implementation_key=None)
        assert any("implementation_key" in item for item in _problems(no_key))
        legacy_only = content(sources=[{"kind": "LEGACY_CODE", "legacy_ids": ["LEG-VK-015"]}])
        review = CalcLegacyResolution(
            legacy_id="LEG-VK-015", resolution="Проверено по тестовой методике."
        )
        assert any("нет основания" in item for item in _problems(legacy_only, review))

    def _from_legacy(self, *legacy_ids: str) -> CalcRuleContent:
        sources = [
            {"kind": "OTHER", "description": "Тестовая геометрия."},
            {"kind": "LEGACY_CODE", "legacy_ids": list(legacy_ids)},
        ]
        return content(sources=sources)

    def _review(self, legacy_id: str, **outcomes: CalcHazardOutcome) -> CalcLegacyResolution:
        return CalcLegacyResolution(
            legacy_id=legacy_id,
            resolution="Сверено с тестовой методикой.",
            hazards=[
                {"hazard": hazard, "outcome": outcome, "comment": "Проверено на примере."}
                for hazard, outcome in outcomes.items()
            ],
        )

    def test_t22_every_hazard_needs_an_explicit_outcome(self) -> None:
        rule = self._from_legacy("LEG-OV-037")
        assert any("нет разбора" in item for item in _problems(rule))

        partial = self._review("LEG-OV-037", DOUBLE_MULTIPLICATION=CalcHazardOutcome.FIXED)
        assert any("DEFECT" in item for item in _problems(rule, partial))

        confirmed = self._review(
            "LEG-OV-037",
            DOUBLE_MULTIPLICATION=CalcHazardOutcome.REJECTED,
            DEFECT=CalcHazardOutcome.FIXED,
        )
        assert any("подтверждена и не устранена" in item for item in _problems(rule, confirmed))

        full = self._review(
            "LEG-OV-037",
            DOUBLE_MULTIPLICATION=CalcHazardOutcome.FIXED,
            DEFECT=CalcHazardOutcome.NOT_APPLICABLE,
        )
        assert _problems(rule, full) == []

    def test_t22_review_without_hazard_comment_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CalcLegacyResolution(
                legacy_id="LEG-OV-037",
                resolution="Сверено с тестовой методикой.",
                hazards=[{"hazard": "DEFECT", "outcome": "FIXED", "comment": ""}],
            )
        with pytest.raises(ValidationError):
            CalcLegacyResolution(
                legacy_id="LEG-OV-037",
                resolution="Сверено с тестовой методикой.",
                hazards=[
                    {"hazard": "DEFECT", "outcome": "FIXED", "comment": "Проверено дважды."},
                    {"hazard": "DEFECT", "outcome": "FIXED", "comment": "Проверено дважды."},
                ],
            )

    def test_t14_conflicting_group_needs_resolution_for_each_implementation(self) -> None:
        rule = self._from_legacy("LEG-VK-027", "LEG-VK-028")
        reviews = [self._resolve_all(item) for item in ("LEG-VK-027", "LEG-VK-028")]
        assert any("LEG-VK-028" in item for item in _problems(rule, reviews[0]))
        assert _problems(rule, *reviews) == []

    def _resolve_all(self, legacy_id: str) -> CalcLegacyResolution:
        entry = load_catalog().get(legacy_id)
        assert entry is not None and CalcLegacyHazard.CONFLICTING_CONSTANTS in entry.hazards
        return self._review(
            legacy_id, **{hazard.value: CalcHazardOutcome.FIXED for hazard in entry.hazards}
        )

    def test_review_of_unreferenced_legacy_is_refused(self) -> None:
        stray = self._review("LEG-VK-001", HIDDEN_DEFAULT=CalcHazardOutcome.FIXED)
        assert any("не ссылается" in item for item in _problems(content(), stray))

    def test_unknown_and_out_of_scope_legacy_references(self) -> None:
        unknown = content(sources=[{"kind": "LEGACY_CODE", "legacy_ids": ["LEG-VK-999"]}])
        assert any("нет в каталоге" in item for item in _problems(unknown))
        prices = content(sources=[{"kind": "LEGACY_CODE", "legacy_ids": ["LEG-EST-024"]}])
        assert any("вне расчётного контура" in item for item in _problems(prices))


class TestEligibility:
    @pytest.mark.parametrize(
        ("status", "eligible"),
        [
            (CalcRuleStatus.DRAFT, False),
            (CalcRuleStatus.UNVERIFIED_LEGACY, False),
            (CalcRuleStatus.REJECTED, False),
            (CalcRuleStatus.DEPRECATED, False),
            (CalcRuleStatus.APPROVED, True),
        ],
    )
    def test_only_approved_is_eligible(self, status: CalcRuleStatus, eligible: bool) -> None:
        assert validation.calculation_eligible(status, content(), date(2026, 9, 28)) is eligible

    def test_effective_dates(self) -> None:
        rule = content(valid_from="2025-01-01", valid_to="2025-12-31")
        on = validation.calculation_eligible
        assert on(CalcRuleStatus.APPROVED, rule, date(2025, 6, 1))
        assert not on(CalcRuleStatus.APPROVED, rule, date(2024, 12, 31))
        assert not on(CalcRuleStatus.APPROVED, rule, date(2026, 1, 1))
        with pytest.raises(ValidationError):
            content(valid_from="2026-01-01", valid_to="2025-01-01")


# --------------------------------------------------------------------- из старого правила


class TestLegacyDraft:
    def test_draft_content_takes_text_as_material_only(self) -> None:
        entry = load_catalog().get("LEG-VK-001")
        assert entry is not None
        payload = CalcRuleFromLegacy.model_validate(
            {
                "rule_key": "test.floor.height_input",
                "rule_type": "GEOMETRY",
                "discipline": "VK",
                "applicability": geometry_content()["applicability"],
                "outputs": geometry_content()["outputs"],
            }
        )
        draft = draft_from_legacy(entry, payload)
        assert draft.implementation_key is None
        assert draft.inputs == [] and draft.parameters == []
        assert "НЕ ПРОВЕРЕНО" in draft.description
        assert entry.rule_text in draft.formula
        assert validation.legacy_ids(draft) == ["LEG-VK-001"]
        # Такой черновик не утверждается, пока инженер не задаст основание и реализацию.
        problems = _problems(draft)
        assert any("implementation_key" in item for item in problems)
        assert any("нет основания" in item for item in problems)
        assert any("нет разбора" in item for item in problems)


# --------------------------------------------------------------- изоляция (T15, T16, T17)


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


class TestIsolation:
    def test_t15_registry_does_not_touch_facts(self) -> None:
        """Правило объявляет нужные факты, но не читает и не пишет реестр фактов."""
        forbidden = (
            "app.services.calc.facts",
            "app.services.calc.adapters",
            "app.services.calc.inspections",
            "app.models.calc.",
            "app.models.CalcFact",
            "app.models.CalcSource",
        )
        for path in RULES_MODULES:
            for module in _imports(path):
                assert not module.startswith(forbidden), f"{path.name}: {module}"

    @pytest.mark.parametrize(
        "rule",
        [
            {"sources": [decision_source(basis="Так в ВОР Заказчика, +15 %")]},
            {
                "parameters": [
                    {
                        "name": "reserve",
                        "value": "50",
                        "unit": "m",
                        "description": "Как в ведомости объёмов заказчика",
                    }
                ]
            },
            {"impact": "Приводит длину к ВОР"},
        ],
    )
    def test_t16_customer_vor_is_never_a_basis(self, rule: dict[str, Any]) -> None:
        problems = validation.content_problems(content(**rule), load_catalog())
        assert any("ВОР Заказчика" in item for item in problems)

    def test_t16_registry_has_no_path_to_customer_vor_facts(self) -> None:
        """Классы источников фактов — забота реестра фактов: реестр правил их не знает."""
        for path in RULES_MODULES:
            assert not any(module.endswith("CalcSourceClass") for module in _imports(path))

    def test_t17_calc_portal_stays_off(self) -> None:
        flag = FEATURES["calc.portal"]
        assert flag.default is False
        assert flag.admin_editable is False
