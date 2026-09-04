"""Границы этапа как проверяемое свойство.

Эти тесты не про функциональность, а про то, чего в проекте не должно быть. Они не дают
случайно втащить SDK модели или включить возможность, которой ещё нет.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.contracts.models import (
    CostClass,
    Modality,
    ModelCapabilities,
    ModelProvider,
    ModelRequirement,
    select,
)
from app.contracts.pipeline import STAGE_CONTRACTS, PipelineStage
from app.contracts.quantities import GeometryType, MeasurementSource, ScaleSource
from app.core.features import DEFAULTS, STAGE2_FEATURES, parse_overrides, resolve
from app.domain import JobType

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# Пакеты, появление которых означало бы, что этап вышел за свои границы.
FORBIDDEN_PACKAGES = (
    "anthropic",
    "openai",
    "langchain",
    "llama-index",
    "vllm",
    "transformers",
    "torch",
    "opencv",
    "ultralytics",
    "easyocr",
    "paddleocr",
    "tesseract",
    "ifcopenshell",
    "celery",
    "temporalio",
)


def _declared_dependencies() -> list[str]:
    with PYPROJECT.open("rb") as stream:
        data = tomllib.load(stream)
    project = data["project"]
    dependencies: list[str] = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        dependencies.extend(extra)
    return [item.lower() for item in dependencies]


class TestStageBoundaries:
    @pytest.mark.parametrize("package", FORBIDDEN_PACKAGES)
    def test_no_model_or_vision_sdk_in_dependencies(self, package: str) -> None:
        assert all(package not in item for item in _declared_dependencies()), (
            f"{package} не должен появляться в зависимостях Stage 1"
        )

    def test_only_one_real_job_type(self) -> None:
        """Реальный тип задания ровно один: остальные шаги пока только контракт."""
        assert [job_type.value for job_type in JobType] == ["legacy_import"]

    def test_future_stages_are_contracts_only(self) -> None:
        assert set(STAGE_CONTRACTS) == set(PipelineStage)
        assert PipelineStage.MEASURE.value not in [job_type.value for job_type in JobType]

    def test_quantity_calculation_never_uses_models(self) -> None:
        """Модель не является калькулятором: величина должна воспроизводиться."""
        assert STAGE_CONTRACTS[PipelineStage.QUANTITY_CALCULATE].uses_models is False

    def test_model_provider_has_no_implementations(self) -> None:
        """Протокол объявлен, реализаций на этом этапе нет."""
        assert not ModelProvider.__subclasses__()


class TestFeatureFlags:
    @pytest.mark.parametrize("name", STAGE2_FEATURES)
    def test_stage2_features_are_off_by_default(self, name: str) -> None:
        assert DEFAULTS[name] is False

    def test_overrides_are_parsed(self) -> None:
        assert parse_overrides("takeoff.ai=true,reports=false") == {
            "takeoff.ai": True,
            "reports": False,
        }

    def test_unknown_flag_is_ignored(self) -> None:
        """Опечатка в окружении не должна порождать флаг, которого нет в продукте."""
        assert parse_overrides("takeof.ai=true") == {}

    def test_resolve_keeps_defaults_for_untouched_flags(self) -> None:
        flags = resolve("reports=true")

        assert flags["reports"] is True
        assert flags["takeoff.ai"] is False

    async def test_meta_exposes_flags(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/meta")).json()

        assert body["features"]["takeoff.ai"] is False
        assert body["features"]["projects"] is True


class TestModelSelection:
    @staticmethod
    def _model(
        model_id: str, *, vision: bool, cost: CostClass, local: bool = False
    ) -> ModelCapabilities:
        modalities = {Modality.TEXT}
        if vision:
            modalities.add(Modality.VISION)
        return ModelCapabilities(
            provider_id="test",
            model_id=model_id,
            modalities=frozenset(modalities),
            structured_output=True,
            tool_calling=False,
            context_tokens=128_000,
            max_output_tokens=4096,
            cost_class=cost,
            runs_locally=local,
        )

    def test_selection_is_by_capability_not_by_name(self) -> None:
        models = [
            self._model("text-only", vision=False, cost=CostClass.LOW),
            self._model("vision", vision=True, cost=CostClass.HIGH),
        ]

        chosen = select(models, ModelRequirement(modalities=frozenset({Modality.VISION})))

        assert chosen is not None
        assert chosen.model_id == "vision"

    def test_cheapest_suitable_model_wins(self) -> None:
        models = [
            self._model("expensive", vision=True, cost=CostClass.HIGH),
            self._model("cheap", vision=True, cost=CostClass.LOW),
        ]

        chosen = select(models, ModelRequirement(modalities=frozenset({Modality.VISION})))

        assert chosen is not None
        assert chosen.model_id == "cheap"

    def test_local_only_requirement_is_respected(self) -> None:
        """Проектная документация может не иметь права покидать периметр заказчика."""
        models = [self._model("remote", vision=True, cost=CostClass.LOW)]

        assert select(models, ModelRequirement(must_run_locally=True)) is None

    def test_no_suitable_model_returns_none(self) -> None:
        models = [self._model("text-only", vision=False, cost=CostClass.LOW)]

        assert select(models, ModelRequirement(min_context_tokens=1_000_000)) is None


class TestQuantityContracts:
    def test_three_concepts_stay_separate(self) -> None:
        """Region, Measurement и Quantity — разные сущности, а не разные названия одного."""
        from app.models import Region

        assert not hasattr(Region, "geometry_type")
        assert not hasattr(Region, "value")
        assert not hasattr(Region, "unit")

    def test_measurement_records_its_origin(self) -> None:
        assert set(MeasurementSource) == {
            MeasurementSource.MANUAL,
            MeasurementSource.AI,
            MeasurementSource.IMPORTED,
        }

    def test_scale_sources_include_manual(self) -> None:
        """Масштаб можно задать руками — автоматическое определение появится позже."""
        assert ScaleSource.MANUAL in set(ScaleSource)

    def test_geometry_types_cover_takeoff_needs(self) -> None:
        assert set(GeometryType) == {
            GeometryType.COUNT,
            GeometryType.LINE,
            GeometryType.POLYLINE,
            GeometryType.POLYGON,
        }
