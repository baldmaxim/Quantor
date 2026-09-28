"""Адаптеры распознанного пакета и нормализация (ADR-0030, PROMPT 02) — без базы.

Тексты блоков синтетические, но в формате импорта legacy-v1: строки метаданных `> **…**` в
начале, таблицы GFM, шапка-название («Экспликация квартир 3 этажа | | |»), строки групп
«Секция № …» и «Квартира № …», разделитель следующей страницы `## Page N`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDiscipline,
    CalcDocumentStage,
    CalcFactMethod,
    CalcInspectionIssueCode,
    CalcSourceClass,
    CalcTableKind,
)
from app.contracts.calc.facts import CalcRegionTableLocator, CalcRegionTextLocator
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.units import UnitError, to_canonical
from app.contracts.calc.values import CalcCountValue, CalcNumberValue
from app.services.calc.adapters.candidates import (
    CalcCandidate,
    CandidateEvidence,
    CollectionDeclaration,
)
from app.services.calc.adapters.markdown_tables import parse_tables
from app.services.calc.adapters.normalize import parse_decimal_ru, parse_floor_scope
from app.services.calc.adapters.pipeline import (
    AcceptedCandidate,
    CollectionResult,
    collect,
    validate_candidate,
)
from app.services.calc.adapters.recognized import RecognizedDocument, RecognizedRegion
from app.services.calc.adapters.table_kinds import classify

STAMP = (
    "> **Created:** 2026-09-28\n"
    "> **Crop:** [Crop](https://example.invalid/crop/1)\n"
    "> **Stamp:** Code: 00-000-АР | Stage: П | Sheet: 12 | Object: Синтетический дом | "
    "Name: План 3 этажа на отм. +6.600 | Organization: Синтетика | Revisions: -\n"
)

APARTMENTS_A = (
    STAMP
    + """
### Экспликация квартир 3 этажа
| № п/п | Имя | Площадь, м² | Кат. пом. |
| :--- | :--- | :--- | :--- |
| **Секция № 1** | | | |
| Квартира № 21 | | | |
| 1 | Кухня-ниша | 10,2 | |
| 2 | Комната | 18,4 | |
| 3 | Санузел | 4,1 | |
| | | 32,7 | |
| Квартира № 22 | | | |
| 1 | Кухня | 9,8 | |
| 2 | Комната | 16,0 | |
| 3 | Комната | 12,5 | |
| 4 | Санузел | 3,9 | |
| 5 | Санузел | 2,1 | |
| | | 44,3 | |
## Page 5
"""
)

# Соседняя колонка того же листа: шапка — название, настоящая шапка — первая строка,
# продолжение без своей секции и повтор квартиры № 22 со страницы.
APARTMENTS_B = (
    STAMP
    + """
| Экспликация квартир 3 этажа | | | |
| :--- | :--- | :--- | :--- |
| № п/п | Имя | Площадь, м² | Кат. пом. |
| Квартира № 23 | | | |
| 1 | Кухня-столовая | 14,0 | |
| 2 | Ванная | 5,0 | |
| Секция № 2 | | | |
| Квартира № 24 | | | |
| 1 | Кухня | 8,0 | |
| 2 | С/у | 3,0 | |
| Квартира № 22 | | | |
"""
)

RANGE_TABLE = """### Экспликация квартир 4-5 этажа
| № п/п | Имя | Площадь, м² | Кат. пом. |
| :--- | :--- | :--- | :--- |
| Квартира № 31, 41 | | | |
| 1 | Кухня | 9,0 | |
| 2 | Санузел | 4,0 | |
| Квартира № 32, 42 | | | |
| 1 | Кухня | 9,0 | |
| 2 | Санузел | 4,0 | |
"""

COMMON_AREAS = """### Экспликация МОП 3 этажа
| Номер помещения | Имя помещения | Площадь, м² | Кат. пом. |
| :--- | :--- | :--- | :--- |
| Секция № 1 | | | |
| 1 | Лифтовый холл | 20,0 | |
| 2 | ПУИ | 3,0 | |
| Секция № 2 | | | |
| 1 | Лифтовый холл | 21,0 | |
| 2 | ПУИ | 3,1 | |
| 3 | С/у | 2,5 | |
"""

SUMMARY = """### Квартирография
| Тип квартиры | Количество квартир типа, шт. | % от общего количества квартир |
| :--- | :--- | :--- |
| 1 ККВ | 96 | 50 |
| 2 ККВ | 64 | 33,3 |
| 2Е | 16 | 8,3 |
| 3 ККВ | 16 | 8,3 |
| Итого | 192 | 100 |
"""

NOTE = """Этажность здания — 25 этажей.
Количество секций — 2.
Высота этажей со 2 по 24 — 3300 мм.
Высота этажа — 3,3
Гарантированный напор в точке подключения — 25 м.
Проектом предусмотрены системы: В1 — хозяйственно-питьевой водопровод, Т3, Т4 — горячее
водоснабжение, К1 — бытовая канализация.
"""

ARCHITECTURE = CollectionDeclaration(CalcSourceClass.ARCHITECTURE, "1", None)
NOTE_DECLARED = CollectionDeclaration(CalcSourceClass.EXPLANATORY_NOTE, "1", None)


def region(text: str, *, page: int = 0, block_type: str = "text") -> RecognizedRegion:
    return RecognizedRegion(
        id=uuid.uuid4(),
        sheet_id=uuid.uuid5(uuid.NAMESPACE_URL, f"sheet-{page}"),
        page_index=page,
        block_type=block_type,
        text=text,
        bbox=(0.1, 0.1, 0.5, 0.5),
    )


def document(*regions: RecognizedRegion) -> RecognizedDocument:
    return RecognizedDocument(revision_id=uuid.uuid4(), regions=regions)


def accepted(result: CollectionResult, fact_type: str, **subject: str) -> AcceptedCandidate:
    wanted = CalcFactSubject(**subject).key() if subject else None
    found = [
        item
        for item in result.accepted
        if item.candidate.fact_type == fact_type
        and (wanted is None or item.candidate.subject.key() == wanted)
    ]
    assert len(found) == 1, [item.fact_key for item in result.accepted]
    return found[0]


def issue_codes(result: CollectionResult) -> set[CalcInspectionIssueCode]:
    return {item.code for item in result.issues}


class TestTables:
    def test_title_row_is_not_the_header(self) -> None:
        [table] = parse_tables(APARTMENTS_B)
        assert table.title == "Экспликация квартир 3 этажа"
        assert table.header == ("№ п/п", "Имя", "Площадь, м²", "Кат. пом.")
        assert table.rows[0][0] == "Квартира № 23"

    def test_bold_group_rows_and_page_separator_are_cleaned(self) -> None:
        [table] = parse_tables(APARTMENTS_A)
        assert table.rows[0][0] == "Секция № 1"
        assert table.context == ("Экспликация квартир 3 этажа",)
        assert all(not row[0].startswith("##") for row in table.rows)

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            (APARTMENTS_A, CalcTableKind.APARTMENT_EXPLICATION),
            (COMMON_AREAS, CalcTableKind.ROOM_EXPLICATION),
            (SUMMARY, CalcTableKind.APARTMENT_SUMMARY),
            (
                "### Сводная экспликация машиномест -1 этажа\n| № | Имя | Площадь |\n"
                "| --- | --- | --- |\n| 1 | Машиноместо | 13,3 |\n",
                CalcTableKind.PARKING_STORAGE,
            ),
            (
                "| Поз. | Наименование | Тип, марка | Ед. измерения | Количество |\n"
                "| --- | --- | --- | --- | --- |\n| 1 | Насос | X | шт. | 2 |\n",
                CalcTableKind.EQUIPMENT_SPEC,
            ),
            (
                "| Прибор | Количество |\n| --- | --- |\n| Умывальник | 207 |\n| Унитаз | 207 |\n",
                CalcTableKind.SANITARY_FIXTURES,
            ),
            ("| Лист | Примечание |\n| --- | --- |\n| 1 | — |\n", CalcTableKind.UNKNOWN),
        ],
    )
    def test_kind_is_read_from_title_and_header(self, text: str, kind: CalcTableKind) -> None:
        [table] = parse_tables(text)
        assert classify(table).kind is kind


class TestNormalization:
    @pytest.mark.parametrize(
        ("text", "scope"),
        [
            ("Экспликация квартир 4-5 этажа", "4..5"),
            ("Экспликация помещений -1 этажа", "-1"),
            ("Экспликация МОП 2–10 этажа", "2..10"),
            ("высота этажей со 2 по 24", "2..24"),
            ("План 3-го этажа", "3"),
            ("Экспликация квартир типового этажа", None),
            ("План антресоли -1 уровня", None),
        ],
    )
    def test_floor_scope(self, text: str, scope: str | None) -> None:
        assert parse_floor_scope(text) == scope

    def test_russian_numbers_keep_their_precision(self) -> None:
        assert parse_decimal_ru("3,30") == Decimal("3.30")
        assert parse_decimal_ru("1 280") == Decimal("1280")
        assert parse_decimal_ru("−5.600") == Decimal("-5.600")
        assert parse_decimal_ru("3,3 м") is None

    def test_mm_to_m_keeps_the_stated_value(self) -> None:
        result = collect(document(region(NOTE)), NOTE_DECLARED)
        height = accepted(result, "floor.height", building="1", floor="2..24")
        assert height.candidate.value == CalcNumberValue(value="3300", unit="mm")
        assert height.canonical == CalcNumberValue(value="3.3", unit="m")

    def test_number_without_unit_is_not_guessed(self) -> None:
        result = collect(document(region("Высота этажей 2-24 — 3,3\n")), NOTE_DECLARED)
        assert not [item for item in result.accepted if item.candidate.fact_type == "floor.height"]
        assert CalcInspectionIssueCode.UNIT_MISSING in issue_codes(result)

    def test_unit_by_rule_elevation_and_head(self) -> None:
        """Единица без слова «м» допустима только по правилу: отметки и напор."""
        result = collect(document(region(STAMP + NOTE)), NOTE_DECLARED)
        elevation = accepted(result, "floor.elevation", building="1", floor="3")
        assert elevation.candidate.value == CalcNumberValue(value="6.600", unit="m")
        head = accepted(result, "system.inlet_pressure")
        assert head.candidate.value == CalcNumberValue(value="25", unit="m_h2o")
        assert head.canonical == CalcNumberValue(value="245.16625", unit="kPa")

    def test_incompatible_unit_is_rejected(self) -> None:
        text = region("x")
        bad = CalcCandidate(
            extractor="document_text",
            source_class=CalcSourceClass.EXPLANATORY_NOTE,
            fact_type="floor.height",
            subject=CalcFactSubject(building="1", floor="3"),
            value=CalcNumberValue(value="3.3", unit="m2"),
            method=CalcFactMethod.DOCUMENT_EXPLICIT,
            confidence=CalcConfidence.HIGH,
            note="",
            evidence=(
                CandidateEvidence(text, CalcRegionTextLocator(start=0, end=1), "фраза", "x"),
            ),
        )
        checked = validate_candidate(bad, frozenset({str(text.id)}))
        assert not isinstance(checked, AcceptedCandidate)
        assert checked.code is CalcInspectionIssueCode.UNIT_MISMATCH

    def test_conversion_that_would_invent_precision_is_refused(self) -> None:
        with pytest.raises(UnitError):
            to_canonical(Decimal("10"), "m3_h", "l_s")
        assert to_canonical(Decimal("6.5"), "l_s", "m3_h") == Decimal("23.4")


class TestExplications:
    def test_floor_is_counted_across_columns_without_double_counting(self) -> None:
        """Две колонки одного этажа, повтор квартиры № 22 — четыре квартиры, а не пять."""
        result = collect(document(region(APARTMENTS_A), region(APARTMENTS_B)), ARCHITECTURE)
        apartments = accepted(result, "floor.apartments_count", building="1", floor="3")
        assert apartments.canonical == CalcCountValue(value=4, unit="apartment")
        assert apartments.candidate.method is CalcFactMethod.TABLE_COUNTED
        assert apartments.candidate.source_class is CalcSourceClass.APARTMENT_SCHEDULE
        kitchens = accepted(result, "floor.kitchens_count", building="1", floor="3")
        assert kitchens.canonical == CalcCountValue(value=4, unit="kitchen")
        bathrooms = accepted(result, "floor.bathrooms_count", building="1", floor="3")
        assert bathrooms.canonical == CalcCountValue(value=5, unit="bathroom")

    def test_evidence_points_to_rows_of_each_table(self) -> None:
        first, second = region(APARTMENTS_A), region(APARTMENTS_B)
        result = collect(document(first, second), ARCHITECTURE)
        apartments = accepted(result, "floor.apartments_count", building="1", floor="3")
        by_region = {item.region.id: item for item in apartments.evidence}
        assert set(by_region) == {first.id, second.id}
        locator = by_region[first.id].locator
        assert isinstance(locator, CalcRegionTableLocator)
        assert locator.table_index == 0
        assert locator.rows == [1, 6]
        assert "Квартира № 21" in by_region[first.id].excerpt
        assert by_region[first.id].region.sha256() == first.sha256()

    def test_range_table_counts_positions_per_floor(self) -> None:
        result = collect(document(region(RANGE_TABLE)), ARCHITECTURE)
        apartments = accepted(result, "floor.apartments_count", building="1", floor="4..5")
        assert apartments.canonical == CalcCountValue(value=2, unit="apartment")

    def test_wet_rooms_of_common_areas_keep_sections_apart(self) -> None:
        """Два ПУИ № 2 в разных секциях — два помещения, а не один повтор."""
        result = collect(document(region(COMMON_AREAS)), ARCHITECTURE)
        wet = accepted(result, "floor.nonresidential_wet_rooms_count", building="1", floor="3")
        assert wet.canonical == CalcCountValue(value=3, unit="room")
        assert wet.candidate.source_class is CalcSourceClass.ROOM_SCHEDULE

    def test_table_without_floor_is_reported_not_guessed(self) -> None:
        body = APARTMENTS_A[APARTMENTS_A.index("| № п/п") :]
        text = "### Экспликация квартир типового этажа\n" + body
        result = collect(document(region(text)), ARCHITECTURE)
        assert not [
            item for item in result.accepted if item.candidate.fact_type.startswith("floor.")
        ]
        assert CalcInspectionIssueCode.UNSCOPED in issue_codes(result)

    def test_other_building_is_a_scope_mismatch(self) -> None:
        text = APARTMENTS_A.replace("квартир 3 этажа", "квартир 3 этажа корпуса 2")
        result = collect(document(region(text)), ARCHITECTURE)
        assert CalcInspectionIssueCode.SCOPE_MISMATCH in issue_codes(result)
        assert not result.accepted or all(
            item.candidate.fact_type == "floor.elevation" for item in result.accepted
        )


class TestSummaryAndText:
    def test_value_from_table_cell(self) -> None:
        result = collect(document(region(SUMMARY)), ARCHITECTURE)
        total = accepted(result, "building.apartments_total", building="1")
        assert total.canonical == CalcCountValue(value=192, unit="apartment")
        assert total.candidate.method is CalcFactMethod.TABLE_EXPLICIT
        [evidence] = total.evidence
        assert evidence.locator == CalcRegionTableLocator(table_index=0, rows=[4], column=1)
        two_room = accepted(result, "building.apartments_by_type", building="1", qualifier="R2")
        assert two_room.canonical == CalcCountValue(value=64, unit="apartment")
        # «2Е» — евроформат: не угадывается, видно в сводке.
        assert CalcInspectionIssueCode.UNMAPPED_LABEL in issue_codes(result)

    def test_explicit_text_value_keeps_its_place(self) -> None:
        note = region(NOTE)
        result = collect(document(note), NOTE_DECLARED)
        floors = accepted(result, "building.floors_above_ground", building="1")
        assert floors.canonical == CalcCountValue(value=25, unit="floor")
        [evidence] = floors.evidence
        assert isinstance(evidence.locator, CalcRegionTextLocator)
        assert note.text[evidence.locator.start : evidence.locator.end].startswith("Этажность")

    def test_systems_named_in_a_note(self) -> None:
        result = collect(document(region(NOTE)), NOTE_DECLARED)
        codes = {
            item.candidate.subject.system_code
            for item in result.accepted
            if item.candidate.fact_type == "system.present"
        }
        assert codes == {"В1", "Т3", "Т4", "К1"}

    def test_ventilation_document_does_not_give_water_systems(self) -> None:
        """«В1» в разделе ОВ — вытяжка; без заявленного раздела — видно, а не угадано."""
        text = region("Система В1 — водопровод хозяйственно-питьевой.\n")
        ventilation = CollectionDeclaration(CalcSourceClass.MEP_DESIGN, "1", CalcDiscipline.OV)
        assert not collect(document(text), ventilation).accepted
        undeclared = collect(
            document(text), CollectionDeclaration(CalcSourceClass.MEP_DESIGN, "1", None)
        )
        assert CalcInspectionIssueCode.DISCIPLINE_MISSING in issue_codes(undeclared)

    def test_image_descriptions_are_not_observations(self) -> None:
        image = region(
            "**[IMAGE]** | Type: План\n**Summary:** Этажность здания — 30", block_type="image"
        )
        assert not collect(document(image), NOTE_DECLARED).accepted

    def test_same_value_twice_is_one_candidate_with_two_places(self) -> None:
        result = collect(document(region(NOTE), region(NOTE, page=1)), NOTE_DECLARED)
        floors = accepted(result, "building.floors_above_ground", building="1")
        assert len(floors.evidence) == 2

    def test_document_contradicting_itself_writes_nothing(self) -> None:
        other = NOTE.replace("25 этажей", "26 этажей")
        result = collect(document(region(NOTE), region(other, page=1)), NOTE_DECLARED)
        assert not [
            item
            for item in result.accepted
            if item.candidate.fact_type == "building.floors_above_ground"
        ]
        assert CalcInspectionIssueCode.SELF_CONTRADICTION in issue_codes(result)

    def test_stamp_gives_stage_and_section(self) -> None:
        result = collect(document(region(APARTMENTS_A)), ARCHITECTURE)
        assert result.stamp.stage is CalcDocumentStage.P
        assert result.stamp.section == "АР"


class TestCustomerVor:
    VOR = """### Водопровод хозяйственно-питьевой В1
| № | Наименование | Ед. изм. | Количество |
| --- | --- | --- | --- |
| 1 | Трубопровод В1 из PP-R Ø50 | м | 1280 |
| 2 | Стояк К1 канализации Ø110 | м | 320 |
"""
    DECLARED = CollectionDeclaration(CalcSourceClass.CUSTOMER_VOR, "1", None)

    def test_only_the_expectation_of_a_system_is_kept(self) -> None:
        result = collect(document(region(self.VOR)), self.DECLARED)
        assert {item.candidate.fact_type for item in result.accepted} == {"system.present"}
        assert {item.candidate.subject.system_code for item in result.accepted} == {"В1", "К1"}
        assert all(
            item.candidate.source_class is CalcSourceClass.CUSTOMER_VOR for item in result.accepted
        )

    def test_quantities_and_diameters_are_counted_not_taken(self) -> None:
        result = collect(document(region(self.VOR)), self.DECLARED)
        counts = {item.code: item.count for item in result.issues}
        assert counts[CalcInspectionIssueCode.VOR_QUANTITY_IGNORED] == 2
        assert counts[CalcInspectionIssueCode.VOR_DIAMETER_IGNORED] == 2
        values = {str(item.canonical.model_dump().get("value")) for item in result.accepted}
        assert not values & {"1280", "320", "50", "110"}
