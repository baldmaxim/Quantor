"""Синтез структуры системы ВК стадии П (PROMPT 06) — общий построитель для В1, Т3, Т4, К1.

```text
источник ─ магистраль ─ стояки ─ этажные подключения (на стояк и этаж, ×этажей с квартирами)
             │            │
             │            ├─ арматура стояков (по узлам, правилом)
             │            └─ шахты — размещение не выбирается
             └─ длина: только документ или обмер
зоны, насосы, узлы учёта, выпуски, вентиляция стояков — если названы в П
```

Порядок оснований: наблюдено в П → рассчитано ядром → синтезировано утверждённым правилом →
неопределённость. Документальное значение не заменяется расчётным: расхождение — предупреждение.
Число стояков-диапазон остаётся диапазоном; в MINIMUM — нижняя оценка с пометкой. Трасса и
координаты не выдумываются: неизвестная длина — неопределённость ROUTE, а не число.
"""

from __future__ import annotations

from typing import Final

from app.contracts.calc.engine import CalcResultRead, CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcElementProvenance,
    CalcQuantityBasis,
    CalcScenario,
    CalcUnresolvedKind,
)
from app.contracts.calc.fact_types import fact_type_def
from app.contracts.calc.synthesis import (
    CalcCardinality,
    CalcElementSource,
    CalcQuantityAttr,
    CalcScenarioEstimate,
    CalcSynthesisVariant,
    CalcSystemEdge,
    CalcSystemGraph,
    CalcSystemNode,
    CalcUnresolvedItem,
    CalcVariantSelection,
)
from app.services.calc.synthesis.definitions import BuildFn, BuildResult, SynthesisContext
from app.services.calc.synthesis.rules import AppliedRule
from app.services.calc.systems.vk.graph_parts import (
    attr,
    attr_value,
    code_of,
    count_of,
    fact_source,
    flag_of,
    number_of,
    result_source,
    whole,
)
from app.services.calc.systems.vk.spec import VkSystemSpec
from app.services.calc.systems.vk.structure_links import link

MAX_VARIANTS: Final = 5
LOWER_BOUND_NOTE: Final = "Это нижняя оценка, не проектное решение"
_O, _C, _S = (
    CalcElementProvenance.OBSERVED,
    CalcElementProvenance.CALCULATED,
    CalcElementProvenance.SYNTHESIZED,
)


def _option_title(fact_type: str, code: str) -> str:
    definition = fact_type_def(fact_type)
    options = {} if definition is None else {item.value: item.title for item in definition.options}
    return options.get(code, code)


class _Builder:
    def __init__(self, spec: VkSystemSpec, context: SynthesisContext) -> None:
        self.spec = spec
        self.context = context
        self.nodes: list[CalcSystemNode] = []
        self.edges: list[CalcSystemEdge] = []
        self.unresolved: list[CalcUnresolvedItem] = []
        self.warnings: list[str] = []
        self.variant_counts: list[int] = []

    # ------------------------------------------------------------------------- доступ

    def fact(self, name: str) -> CalcSnapshotItem | None:
        return self.context.facts.get(name)

    def result(self, key: str) -> CalcResultRead | None:
        return self.context.results.get(key)

    def rule(self, name: str) -> AppliedRule | None:
        used = self.context.rules.get(name)
        return used if isinstance(used, AppliedRule) else None

    def node(self, **values: object) -> CalcSystemNode:
        node = CalcSystemNode.model_validate({"scope": self.context.scope, **values})
        self.nodes.append(node)
        return node

    def edge(self, **values: object) -> None:
        self.edges.append(CalcSystemEdge.model_validate(values))

    def issue(
        self,
        key: str,
        kind: CalcUnresolvedKind,
        title: str,
        known: str,
        needed: str,
        *,
        structural: bool,
        element_id: str | None = None,
    ) -> None:
        self.unresolved.append(
            CalcUnresolvedItem(
                key=key,
                kind=kind,
                title=title,
                element_id=element_id,
                known=known,
                needed=needed,
                structural=structural,
            )
        )

    def observed_count(
        self, name: str, node_id: str, semantic: str, title: str, support: str
    ) -> CalcSystemNode | None:
        item = self.fact(name)
        count = None if item is None else count_of(item)
        if item is None or count is None:
            return None
        return self.node(
            id=node_id,
            semantic_type=semantic,
            title=title,
            provenance=_O,
            sources=[fact_source(item)],
            cardinality=CalcCardinality(min=count, max=count),
            support=f"{support}: {count}",
        )

    # ------------------------------------------------------------------------ источник

    def source(self) -> CalcSystemNode | None:
        spec = self.spec
        if spec.source == "INLET":
            found = self.observed_count(
                "inlets", "source", "INLET", "Ввод", "Вводы указаны в документации"
            )
            missing = "Вводы в документации не указаны"
        elif spec.source == "OUTLET":
            found = self.observed_count(
                "outlets", "source", "OUTLET_GROUP", "Выпуски", "Выпуски указаны в документации"
            )
            missing = "Выпуски в документации не указаны"
        elif spec.source == "HOT_SOURCE":
            item = self.fact("hot_source")
            code = None if item is None else code_of(item)
            found = None
            if item is not None and code is not None:
                title = _option_title("system.hot_water_source", code)
                found = self.node(
                    id="source",
                    semantic_type="HOT_WATER_SOURCE",
                    title=f"Источник горячей воды: {title}",
                    provenance=_O,
                    sources=[fact_source(item)],
                    cardinality=CalcCardinality(min=1, max=1),
                    support=f"Источник горячей воды указан в документации: {title}",
                )
            missing = "Источник горячей воды в документации не указан"
        else:
            return None
        if found is None:
            self.issue(
                "source",
                CalcUnresolvedKind.MISSING_INPUT,
                "Начало системы",
                missing,
                "документ П: схема, записка или ТУ",
                structural=False,
            )
        return found

    def zones(self) -> None:
        if self.spec.zones_rule is None:
            return
        observed = self.fact("zones")
        count = None if observed is None else count_of(observed)
        calculated = self.result("structure.zones")
        if observed is not None and count is not None:
            if calculated is not None and whole(calculated) != count:
                self.warnings.append(
                    f"Зоны: в документе {count}, правило даёт {whole(calculated)} — принят "
                    "документ, расхождение показано"
                )
            self.node(
                id="zones",
                semantic_type="ZONE_GROUP",
                title="Зоны",
                provenance=_O,
                sources=[fact_source(observed)],
                cardinality=CalcCardinality(min=count, max=count),
                support=f"Зоны заданы проектом: {count}",
            )
        elif calculated is not None:
            zones = whole(calculated)
            self.node(
                id="zones",
                semantic_type="ZONE_GROUP",
                title="Зоны",
                provenance=_C,
                sources=[result_source(self.context, calculated)],
                cardinality=CalcCardinality(min=zones, max=zones),
                support=f"Зоны следуют из расчёта по утверждённому правилу: {zones}",
            )
        else:
            self.issue(
                "zones",
                CalcUnresolvedKind.MISSING_INPUT,
                "Зонирование",
                "зоны в П не заданы, правило зонирования не применено",
                f"зоны по схеме П или утверждённое правило {self.spec.zones_rule}",
                structural=True,
            )

    def equipment(self) -> None:
        if self.spec.source != "INLET":
            return
        pump = self.fact("pump")
        present = None if pump is None else flag_of(pump)
        if pump is not None and present:
            self.node(
                id="pump_station",
                semantic_type="PUMP_STATION",
                title="Насосная установка",
                provenance=_O,
                sources=[fact_source(pump)],
                cardinality=CalcCardinality(min=1, max=1),
                support="Насосная установка предусмотрена документацией; модель не определяется",
            )
        elif present is None:
            self.issue(
                "pump_station",
                CalcUnresolvedKind.MISSING_INPUT,
                "Насосная установка",
                "в документации не сказано, нужна ли",
                "схема или записка П; напор ТУ",
                structural=False,
            )
        self.observed_count(
            "meters", "meters", "METER_UNITS", "Узлы учёта", "Узлы учёта указаны в документации"
        )

    # -------------------------------------------------------------------------- стояки

    def riser_attributes(self) -> tuple[list[CalcQuantityAttr], list[CalcElementSource]]:
        attributes: list[CalcQuantityAttr] = []
        sources: list[CalcElementSource] = []
        for name, key, note in (
            ("interfloor_length", "structure.interfloor_length", "от 1-го до верхнего этажа"),
            ("slab_crossings", "structure.slab_crossings", "перекрытий между 1-м и верхним"),
            ("bottom_length", "quantity.end_bottom", "ниже 1-го этажа — по правилу"),
            ("top_length", "quantity.end_top", "выше верхнего этажа — по правилу"),
        ):
            found = self.result(key)
            if found is not None:
                attributes.append(attr(name, found, note=note))
                sources.append(result_source(self.context, found))
        diameter = self.fact("riser_diameter")
        value = None if diameter is None else number_of(diameter)
        if diameter is not None and value is not None:
            attributes.append(
                attr_value("diameter", value, "mm", CalcQuantityBasis.PER_INSTANCE, "по схеме")
            )
            sources.append(fact_source(diameter))
        return attributes, sources

    def risers(self) -> CalcSystemNode | None:
        attributes, sources = self.riser_attributes()
        observed = self.fact("risers")
        count = None if observed is None else count_of(observed)
        low_result = self.result("structure.risers_min")
        high_result = self.result("structure.risers_max")
        common = {"id": "risers", "semantic_type": "RISER_GROUP", "title": "Стояки"}
        if observed is not None and count is not None:
            if low_result is not None and high_result is not None:
                low, high = whole(low_result), whole(high_result)
                if not low <= count <= high:
                    self.warnings.append(
                        f"Стояки: в документе {count}, правило даёт {low}–{high} — принят "
                        "документ, расхождение показано"
                    )
            return self.node(
                **common,
                provenance=_O,
                sources=[fact_source(observed), *sources],
                attributes=attributes,
                cardinality=CalcCardinality(min=count, max=count),
                support=f"Стояки указаны в документации: {count}",
            )
        if low_result is None or high_result is None:
            self.issue(
                "risers.count",
                CalcUnresolvedKind.MISSING_INPUT,
                "Число стояков",
                "в П стояки не указаны; утверждённого правила числа стояков нет или ему не "
                "хватило данных",
                f"стояки по схеме П или утверждённое правило {self.spec.risers_rule}",
                structural=True,
            )
            return None
        low, high = whole(low_result), whole(high_result)
        estimate = None
        if low != high:
            self.issue(
                "risers.count",
                CalcUnresolvedKind.COUNT_RANGE,
                "Число стояков",
                f"{low}–{high} по расчёту",
                "стояки по схеме П или решение инженера — середина диапазона не выбирается",
                structural=True,
                element_id="risers",
            )
            if self.context.scenario is CalcScenario.MINIMUM:
                estimate = CalcScenarioEstimate(
                    value=low, meaning="LOWER_BOUND", note=LOWER_BOUND_NOTE
                )
            elif high - low + 1 <= MAX_VARIANTS:
                self.variant_counts = list(range(low, high + 1))
            else:
                self.warnings.append(f"Вариантов больше {MAX_VARIANTS} — хранится диапазон")
        return self.node(
            **common,
            provenance=_C,
            sources=[
                result_source(self.context, low_result),
                result_source(self.context, high_result),
                *sources,
            ],
            attributes=attributes,
            cardinality=CalcCardinality(min=low, max=high),
            estimate=estimate,
            support=f"Число стояков следует из расчёта по утверждённому правилу: "
            f"{low if low == high else f'{low}–{high}'}",
        )

    def shafts(self) -> None:
        found = self.result("structure.shafts_max")
        if found is None:
            return
        count = whole(found)
        self.node(
            id="shafts",
            semantic_type="SHAFT_GROUP",
            title="Шахты ВК",
            provenance=_C,
            sources=[result_source(self.context, found)],
            cardinality=CalcCardinality(min=count, max=count),
            support=f"Шахт и ниш ВК на этаже по документации — до {count}",
        )
        self.issue(
            "risers.placement",
            CalcUnresolvedKind.PLACEMENT,
            "Размещение стояков по шахтам",
            f"шахт на этаже до {count}",
            "схема П; правила размещения стояков нет — стояки по шахтам не раскладываются",
            structural=False,
            element_id="shafts",
        )

    def served_floors(self) -> CalcSystemNode | None:
        served = self.result("structure.served_floors")
        top = self.result("structure.top_floor")
        if served is None or top is None:
            self.issue(
                "floors",
                CalcUnresolvedKind.MISSING_INPUT,
                "Этажи с квартирами",
                "квартирография не покрывает все надземные этажи или её нет",
                "квартиры по каждому надземному этажу (0 — тоже значение)",
                structural=True,
            )
            return None
        count = whole(served)
        return self.node(
            id="served_floors",
            semantic_type="SERVED_FLOORS",
            title="Обслуживаемые этажи",
            provenance=_C,
            sources=[result_source(self.context, served), result_source(self.context, top)],
            cardinality=CalcCardinality(min=1, max=1),
            multiplicity=count,
            support=f"Этажей с квартирами {count}, верхний — {whole(top)}-й: типовая группа "
            f"повторяется ×{count}, а не копируется",
        )

    def build(self) -> BuildResult:
        source = self.source()
        self.zones()
        self.equipment()
        risers = self.risers()
        self.shafts()
        floors = self.served_floors()
        link(self, source, risers, floors)
        graph = CalcSystemGraph(
            graph_type=f"vk.{self.spec.slug}.structure",
            discipline=CalcDiscipline.VK,
            system_code=self.context.scope.system_code,
            scope=self.context.scope,
            scenario=self.context.scenario,
            synthesizer_id=self.context.definition.synthesizer_id,
            synthesizer_version=self.context.definition.version,
            nodes=self.nodes,
            edges=self.edges,
            unresolved=self.unresolved,
            assumptions=[],
            warnings=self.warnings,
        )
        return BuildResult(graph, self.variants())

    def variants(self) -> tuple[CalcSynthesisVariant, ...]:
        if not self.variant_counts:
            return ()
        low, high = self.variant_counts[0], self.variant_counts[-1]
        others = [
            item.title for item in self.unresolved if item.structural and item.key != "risers.count"
        ]
        return tuple(
            CalcSynthesisVariant(
                key=f"risers_{count}",
                title=f"{count} стояков",
                selections=[CalcVariantSelection(node_id="risers", count=count)],
                reasons=[
                    f"{count} в пределах расчёта {low}–{high}",
                    "основания выбрать нет — вариант не выбран и не взвешен",
                ],
                open_questions=others,
            )
            for count in self.variant_counts
        )


Builder = _Builder


def build_for(spec: VkSystemSpec) -> BuildFn:
    def build(context: SynthesisContext) -> BuildResult:
        return _Builder(spec, context).build()

    return build
