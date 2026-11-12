"""Каталог вопросов к документации `consistency.doc_questions.v1`: структура, без поиска."""

from __future__ import annotations

import pytest

from app.services.consistency.dictionaries import SECTION_MARKS, SheetKind, normalize_mark
from app.services.consistency.doc_questions import (
    DOC_QUESTIONS,
    DOC_QUESTIONS_VERSION,
    AssumptionStatus,
    DocQuestionCode,
    DocValueKind,
    is_customer_document,
    question_by_code,
)


def test_version_and_codes_are_unique_and_complete() -> None:
    assert DOC_QUESTIONS_VERSION == "consistency.doc_questions.v1"
    codes = [question.code for question in DOC_QUESTIONS]
    assert len(codes) == len(set(codes))
    assert set(codes) == set(DocQuestionCode)
    params = [question.receiver_param for question in DOC_QUESTIONS]
    assert len(params) == len(set(params))
    assert all(question.title for question in DOC_QUESTIONS)


def test_receiver_params_for_cad_match_existing_trace_params() -> None:
    assert question_by_code(DocQuestionCode.CLEAR_HEIGHT).receiver_param == "clear_height_mm"
    assert question_by_code(DocQuestionCode.SLAB_THICKNESS).receiver_param == "slab_thickness_mm"
    ceiling = question_by_code(DocQuestionCode.CORRIDOR_CEILING_HEIGHT)
    assert ceiling.receiver_param == "corridor_ceiling_height_mm"


def test_every_question_has_sources_anchors_and_sane_range() -> None:
    marks = {normalize_mark(item.mark) for item in SECTION_MARKS}
    for question in DOC_QUESTIONS:
        assert question.sources, question.code
        assert question.anchors, question.code
        assert question.min_mm < question.max_mm
        assert all(1 <= anchor.weight <= 20 for anchor in question.anchors)
        if question.context_required:
            assert question.context, question.code
        for source in question.sources:
            assert source.customer or source.section_marks
            assert not (source.customer and source.section_marks)
            # Марки раздела - из словаря разделов, а не придуманные.
            assert {normalize_mark(mark) for mark in source.section_marks} <= marks


def test_source_order_is_priority_for_ceiling_question() -> None:
    ceiling = question_by_code(DocQuestionCode.CORRIDOR_CEILING_HEIGHT)
    labels = [source.label for source in ceiling.sources]
    assert labels[:4] == ["ПЗ АР", "Разрезы АР", "Ведомость отделки АР", "Договор / ТЗ Заказчика"]
    assert ceiling.sources[0].sheet_kinds == (SheetKind.TEXT,)
    assert ceiling.sources[3].customer


def test_value_kinds_cover_required_types() -> None:
    kinds = {question.value_kind for question in DOC_QUESTIONS}
    assert {DocValueKind.LENGTH_MM, DocValueKind.SECTION_MM, DocValueKind.TEXT} <= kinds
    assert DocValueKind.ENUM in kinds
    assert DocValueKind.RANGE_MM in kinds


def test_assumptions_only_where_norm_exists_with_reference() -> None:
    with_norm = {q.code: q.assumption for q in DOC_QUESTIONS if q.assumption is not None}
    assert set(with_norm) == {
        DocQuestionCode.HOT_OVER_COLD_GAP,
        DocQuestionCode.SPRINKLER_CEILING_GAP,
    }
    hot = with_norm[DocQuestionCode.HOT_OVER_COLD_GAP]
    assert hot.mm_from == 100
    assert hot.reference == "СП 40-101-96, п. 2.25"
    assert hot.status == AssumptionStatus.ANALOGY  # для PE-Xa это аналогия, а не прямая норма
    gap = with_norm[DocQuestionCode.SPRINKLER_CEILING_GAP]
    assert (gap.mm_from, gap.mm_to) == (80, 300)
    assert gap.reference == "СП 485.1311500.2020, п. 6.2.11"
    assert gap.status == AssumptionStatus.NORM


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("Договор_(общий).pdf", True),
        ("Приложение_№1_Техническое_задание.pdf", True),
        ("Приложение_№14_Стандарты_проектирования_объектов.pdf", True),
        ("Приложение №19 Чек-лист стандартов.pdf", True),
        ("ПД-00578355-Р6-АР1.pdf", False),
        ("МЛДГВ-КАМ-0925-П-ИОС4.2_ver5.pdf", False),
        ("Приложение_№9_СТУ_ПБ.pdf", False),
    ],
)
def test_customer_document_by_file_name(file_name: str, expected: bool) -> None:
    assert is_customer_document(file_name) is expected


def test_customer_document_by_first_page_heading_only() -> None:
    assert is_customer_document("scan001.pdf", "ДОГОВОР  № 12\nподряда на проектирование")
    assert is_customer_document("scan001.pdf", "Приложение к договору\nТехническое задание")
    assert not is_customer_document("scan001.pdf", "Пояснительная записка. Отделка по договору")
    assert not is_customer_document("scan001.pdf", None)
