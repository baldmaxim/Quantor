"""Контракты реестра фактов (ADR-0030, PROMPT 01): место, единицы, значения, типы фактов.

Чистые проверки без базы: всё, что решает, одинаковы ли два значения и можно ли их сравнить,
должно ловиться до хранения.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts.calc import draft
from app.contracts.calc.enums import CalcDiscipline, CalcValueKind
from app.contracts.calc.fact_types import (
    REGISTRY,
    FactUnitError,
    FactValueError,
    canonicalize,
    check_subject,
    fact_key,
    values_agree,
)
from app.contracts.calc.subjects import CalcFactSubject, normalize_system_code
from app.contracts.calc.units import UNITS, UnitError, compatible, to_canonical
from app.contracts.calc.values import (
    CalcCountValue,
    CalcEnumValue,
    CalcNumberValue,
    CalcRangeValue,
    CalcTextValue,
    decimal_text,
)


class TestSubject:
    def test_latin_lookalikes_become_cyrillic(self) -> None:
        """«B1» с латинской B и «В1» — одна система, иначе xlsx и распознанный текст разойдутся."""
        assert normalize_system_code("b1") == "В1"
        assert normalize_system_code("T 3") == "Т3"
        assert normalize_system_code("К1") == "К1"

    def test_system_needs_discipline(self) -> None:
        """«В1» водопровода и «В1» вытяжки — разные системы: без раздела их не отличить."""
        with pytest.raises(ValidationError):
            CalcFactSubject(system_code="В1")

    def test_floor_codes(self) -> None:
        assert CalcFactSubject(building="1", floor=" 07 ").floor == "7"
        assert CalcFactSubject(building="1", floor="2..24").floor == "2..24"
        assert CalcFactSubject(building="1", floor="-1").floor == "-1"
        for bad in ("24..2", "первый", "2-24"):
            with pytest.raises(ValidationError):
                CalcFactSubject(building="1", floor=bad)

    def test_separators_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalcFactSubject(building="1|2")

    def test_key_is_canonical(self) -> None:
        subject = CalcFactSubject(
            building=" 1 ", floor="12", discipline=CalcDiscipline.VK, system_code="b1"
        )
        assert subject.key() == "building=1|floor=12|discipline=VK|system_code=В1"
        assert CalcFactSubject().key() == "project"
        assert fact_key("floor.height", subject).startswith("floor.height@building=1")


class TestUnits:
    def test_conversion_to_canonical(self) -> None:
        assert to_canonical(Decimal("3300"), "mm", "m") == Decimal("3.3")
        assert to_canonical(Decimal("330"), "cm", "m") == Decimal("3.3")

    def test_typed_counts_do_not_mix(self) -> None:
        """Этажи не переводятся в квартиры: так ловится двойное умножение старого портала."""
        assert not compatible("floor", "apartment")
        with pytest.raises(UnitError):
            to_canonical(Decimal(3), "floor", "apartment")

    def test_length_and_area_do_not_mix(self) -> None:
        assert not compatible("m", "m2")

    def test_decimal_text_is_canonical(self) -> None:
        assert decimal_text(Decimal("3.300")) == "3.3"
        assert decimal_text(Decimal("1E+2")) == "100"
        assert decimal_text(Decimal("-0.0")) == "0"


class TestCanonicalValue:
    def test_number_is_converted_to_type_unit(self) -> None:
        value = canonicalize(REGISTRY["floor.height"], CalcNumberValue(value="3300", unit="mm"))
        assert value == CalcNumberValue(value="3.3", unit="m")

    def test_incompatible_unit_is_an_error_not_zero(self) -> None:
        with pytest.raises(FactUnitError):
            canonicalize(REGISTRY["floor.height"], CalcNumberValue(value="3.3", unit="m2"))

    def test_count_of_wrong_entity_is_refused(self) -> None:
        with pytest.raises(FactUnitError):
            canonicalize(REGISTRY["floor.apartments_count"], CalcCountValue(value=9, unit="floor"))

    def test_count_takes_type_unit_when_omitted(self) -> None:
        value = canonicalize(REGISTRY["floor.apartments_count"], CalcCountValue(value=9))
        assert value == CalcCountValue(value=9, unit="apartment")

    def test_kind_must_match_type(self) -> None:
        with pytest.raises(FactValueError):
            canonicalize(REGISTRY["floor.height"], CalcCountValue(value=3))

    def test_negative_length_is_refused(self) -> None:
        with pytest.raises(FactValueError):
            canonicalize(REGISTRY["floor.height"], CalcNumberValue(value="-3.3", unit="m"))

    def test_enum_must_be_declared(self) -> None:
        with pytest.raises(FactValueError):
            canonicalize(REGISTRY["floor.function"], CalcEnumValue(value="CASINO"))

    def test_text_is_cleaned(self) -> None:
        value = canonicalize(REGISTRY["room.purpose"], CalcTextValue(value="  санузел   ПУИ "))
        assert value == CalcTextValue(value="санузел ПУИ")

    def test_range_needs_a_bound_and_order(self) -> None:
        with pytest.raises(ValidationError):
            CalcRangeValue(unit="m")
        with pytest.raises(ValidationError):
            CalcRangeValue(low="5", high="3", unit="m")

    def test_number_text_rejects_floats_in_exponent_form(self) -> None:
        """Числа строками без экспоненты: «1e3» — не десятичная запись контракта."""
        with pytest.raises(ValidationError):
            CalcNumberValue(value="1e3", unit="m")


class TestAgreement:
    def test_within_tolerance_is_agreement(self) -> None:
        height = REGISTRY["floor.height"]
        assert values_agree(
            height, CalcNumberValue(value="3.3", unit="m"), CalcNumberValue(value="3.305", unit="m")
        )
        assert not values_agree(
            height, CalcNumberValue(value="3.3", unit="m"), CalcNumberValue(value="3.0", unit="m")
        )

    def test_counts_are_exact(self) -> None:
        apartments = REGISTRY["floor.apartments_count"]
        assert not values_agree(
            apartments,
            CalcCountValue(value=9, unit="apartment"),
            CalcCountValue(value=8, unit="apartment"),
        )

    def test_text_ignores_case(self) -> None:
        material = REGISTRY["system.pipe_material"]
        assert values_agree(material, CalcTextValue(value="PE-X"), CalcTextValue(value="pe-x"))


class TestFactTypes:
    def test_every_type_is_described(self) -> None:
        for definition in REGISTRY.values():
            assert definition.title and definition.description, definition.key
            if definition.value_kind in (
                CalcValueKind.NUMBER,
                CalcValueKind.COUNT,
                CalcValueKind.RANGE,
            ):
                assert definition.unit in UNITS, definition.key
            if definition.value_kind is CalcValueKind.ENUM:
                assert definition.options, definition.key
            assert definition.required_subject <= definition.allowed_subject, definition.key

    def test_customer_vor_admits_only_qualitative_facts(self) -> None:
        """ВОР Заказчика — не эталон: количества из него в реестр не принимаются вовсе."""
        quantitative = {CalcValueKind.NUMBER, CalcValueKind.COUNT, CalcValueKind.RANGE}
        admitted = [d for d in REGISTRY.values() if d.customer_vor_admissible]
        assert admitted
        assert all(d.value_kind not in quantitative for d in admitted)

    def test_subject_is_checked_against_type(self) -> None:
        floor = REGISTRY["floor.apartments_count"]
        assert check_subject(floor, CalcFactSubject(building="1", floor="12")) is None
        assert check_subject(floor, CalcFactSubject(building="1")) is not None
        assert check_subject(floor, CalcFactSubject(building="1", floor="12", room="кв. 1"))


class TestDraftContracts:
    ENTITIES = (
        "CalcCalculationInput",
        "CalcAssumption",
        "CalcRuleReference",
        "CalcCalculationRun",
        "CalcCalculationStep",
        "CalcCalculationResult",
        "CalcExpectedQuantity",
        "CalcCustomerVorItem",
        "CalcVorMatch",
        "CalcProjectQuestion",
    )

    def test_future_entities_exist_as_contracts_only(self) -> None:
        """Сущности следующих промтов — контракты без таблиц: пустых таблиц не заводим."""
        from app.db.base import Base

        for name in self.ENTITIES:
            assert hasattr(draft, name), name
        tables = set(Base.metadata.tables)
        for forbidden in ("calc_runs", "calc_steps", "calc_results", "calc_vor_items"):
            assert forbidden not in tables
