"""Ведомость листов: разборщик страницы и проверки «ведомость ↔ листы» (чистые, без БД).

Тексты страниц - синтетические, в форме текстового слоя PDF: строки таблицы, подписи колонок, штамп.
"""

from __future__ import annotations

from app.services.consistency.frame_checks import CheckCode, CheckStatus, RefKind
from app.services.consistency.register_checks import (
    RegisterView,
    SheetView,
    check_register_sheets,
    check_register_titles,
    check_sheets_in_register,
    run_register_checks,
)
from app.services.consistency.sheet_register import (
    RegisterEntry,
    RowForm,
    normalize_number,
    parse_register_page,
    titles_agree,
)

GENERAL_DATA = """Общие данные
Ведомость рабочих чертежей основного комплекта
Лист Наименование Примечание
1 Общие данные
2 План 1 этажа на отм. 0,000
3 План типового этажа на отм. +3,300
(2-17 этажи)
4 Разрез 1-1
5 Фасад в осях 1-12
Ведомость ссылочных и прилагаемых документов
Обозначение Наименование Примечание
ГОСТ 21.501-2018 Правила выполнения рабочей документации
Изм. Кол.уч Лист №док Подп. Дата
Стадия Лист Листов
Р 1 5
"""

TRAILING = """ПД-00578355-14-АР.ТЧ
Перечень листов графической части
План подвала на отм. -3,000 1
План 1 этажа на отм. 0,000 2
Разрез 1-1 3
Изм. Кол.уч Лист №док Подп. Дата
"""


# --------------------------------------------------------------------------- разборщик


def test_leading_form_with_continuation_and_stop_at_next_register() -> None:
    page = parse_register_page(GENERAL_DATA)
    assert page is not None
    assert page.form is RowForm.LEADING and not page.continued
    assert [entry.number for entry in page.entries] == ["1", "2", "3", "4", "5"]
    assert page.entries[2].title == "План типового этажа на отм. +3,300 (2-17 этажи)"
    assert page.entries[4].title == "Фасад в осях 1-12"
    assert page.duplicates == ()


def test_trailing_form_by_majority() -> None:
    page = parse_register_page(TRAILING)
    assert page is not None
    assert page.form is RowForm.TRAILING
    assert [(entry.number, entry.title) for entry in page.entries] == [
        ("1", "План подвала на отм. -3,000"),
        ("2", "План 1 этажа на отм. 0,000"),
        ("3", "Разрез 1-1"),
    ]


def test_not_a_sheet_register() -> None:
    assert parse_register_page("Ведомость отделки помещений\n1 Кухня 12,5\n2 Санузел 3,1") is None
    assert parse_register_page("Ведомость ссылочных документов\n1 ГОСТ 21.501\n2 СП 54") is None
    # Одна строка - не ведомость.
    assert parse_register_page("Ведомость листов\n1 Общие данные\nИзм. Кол.уч") is None
    assert parse_register_page("План 1 этажа\n1 Общие данные\n2 План") is None  # нет заголовка


def test_continuation_page_and_duplicates() -> None:
    text = "Ведомость листов (продолжение)\n6 Схема В1\n7 Схема К1\n7 Схема К1 повтор\n"
    page = parse_register_page(text)
    assert page is not None and page.continued
    assert [entry.number for entry in page.entries] == ["6", "7"]
    assert page.duplicates == ("7",)


def test_noise_ends_register() -> None:
    text = "Ведомость чертежей\n1 Общие данные\n2 План\nШУМ\nЕщё шум\nПрочее\n3 Уже не ведомость\n"
    page = parse_register_page(text)
    assert page is not None
    assert [entry.number for entry in page.entries] == ["1", "2"]


def test_normalize_number_and_titles() -> None:
    assert normalize_number("05") == "5"
    assert normalize_number("Лист 3") == "3"
    assert normalize_number("1.1") == "1.1"
    assert normalize_number("2а") == "2а"
    assert normalize_number("стр") is None
    assert titles_agree("Корпус 1. Секция 2. План 3 этажа", "План 3 этажа") is True
    assert titles_agree("План 3 этажа на отм. +6,600", "Разрез 1-1") is False
    assert titles_agree("План", "-") is None


# --------------------------------------------------------------------------- проверки


def _sheet(
    number: str | None,
    *,
    sid: str | None = None,
    title: str | None = None,
    confirmed: bool = True,
    kind: str = "floor_plan",
    revision: str = "r1",
) -> SheetView:
    return SheetView(
        id=sid or f"p{number}",
        revision_id=revision,
        file_name="АР.pdf",
        page_index=int(number) if number and number.isdigit() else 0,
        sheet_number=number,
        sheet_kind=kind,
        section_mark="АР",
        title=title,
        confirmed=confirmed,
    )


def _register(*rows: tuple[str, str], duplicates: tuple[str, ...] = ()) -> RegisterView:
    return RegisterView(
        id="reg",
        revision_id="r1",
        file_name="АР.pdf",
        page_index=0,
        entries=tuple(RegisterEntry(number=n, title=t, snippet=f"{n} {t}") for n, t in rows),
        duplicates=duplicates,
    )


def test_register_sheets_match_mismatch_not_run() -> None:
    register = _register(("1", "Общие данные"), ("2", "План 1 этажа"))
    ok = check_register_sheets(register, [_sheet("1"), _sheet("02")])
    assert ok.status is CheckStatus.MATCH
    assert ok.refs[0].kind is RefKind.REGISTER and ok.refs[0].file_name == "АР.pdf"

    missing = check_register_sheets(register, [_sheet("1"), _sheet(None, sid="x")])
    assert missing.status is CheckStatus.MISMATCH
    assert "Нет листа с номером: 2" in missing.message
    assert "Страниц без номера листа в паспорте: 1" in missing.message

    pending = check_register_sheets(register, [_sheet("1"), _sheet("2", confirmed=False)])
    assert pending.status is CheckStatus.NOT_RUN
    assert "Паспорт листа не подтверждён: 2" in pending.message

    twice = check_register_sheets(register, [_sheet("1"), _sheet("2"), _sheet("2", sid="q")])
    assert twice.status is CheckStatus.MISMATCH
    assert "нескольких подтверждённых листах: 2" in twice.message


def test_text_part_pages_are_not_compared() -> None:
    register = _register(("1", "Общие данные"), ("2", "План"))
    sheets = [_sheet("1"), _sheet("2"), _sheet("3", kind="text")]
    results = run_register_checks([register], sheets, candidates=0)
    extra = next(item for item in results if item.code is CheckCode.SHEETS_IN_REGISTER)
    assert extra.status is CheckStatus.MATCH


def test_sheets_in_register() -> None:
    register = _register(("1", "Общие данные"))
    result = check_sheets_in_register([register], [_sheet("1"), _sheet("4"), _sheet(None)])
    assert result.status is CheckStatus.MISMATCH
    assert "Листов нет в ведомости: 4" in result.message
    assert "без номера не проверено: 1" in result.message
    assert [ref.id for ref in result.refs] == ["reg", "p4"]
    assert check_sheets_in_register([register], [_sheet("1", confirmed=False)]).status is (
        CheckStatus.NOT_RUN
    )


def test_register_titles() -> None:
    register = _register(("1", "Общие данные"), ("2", "План 1 этажа на отм. 0,000"))
    agree = check_register_titles(
        register, [_sheet("1", title="Общие данные"), _sheet("2", title="План 1 этажа")]
    )
    assert agree.status is CheckStatus.MATCH and "совпадают: 2" in agree.message.lower()

    differ = check_register_titles(
        register, [_sheet("1", title="Общие данные"), _sheet("2", title="Разрез 1-1")]
    )
    assert differ.status is CheckStatus.MISMATCH
    assert "лист 2: в ведомости «План 1 этажа на отм. 0,000», на листе «Разрез 1-1»" in (
        differ.message
    )
    assert [ref.id for ref in differ.refs] == ["reg", "p2"]

    unknown = check_register_titles(register, [_sheet("1"), _sheet("2")])
    assert unknown.status is CheckStatus.NOT_RUN


def test_without_confirmed_registers() -> None:
    none = run_register_checks([], [], candidates=0)
    assert [item.status for item in none] == [CheckStatus.NOT_RUN] * 3
    assert "запустите разбор" in none[0].message
    pending = run_register_checks([], [], candidates=2)
    assert "Найдено ведомостей листов: 2" in pending[0].message


def test_register_duplicates_are_mismatch() -> None:
    register = _register(("1", "Общие данные"), ("2", "План"), duplicates=("2",))
    result = check_register_sheets(register, [_sheet("1"), _sheet("2")])
    assert result.status is CheckStatus.MISMATCH
    assert "повторяется в самой ведомости: 2" in result.message
