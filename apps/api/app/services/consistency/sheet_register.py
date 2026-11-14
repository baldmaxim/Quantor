"""Ведомость листов: кандидат по тексту страницы PDF (ADR-0043, С2, подэтап «ведомость ↔ листы»).

Чистый разборщик без БД. Вход - текстовый слой одной страницы (тот же, что у паспорта листа), без
OCR, растра и геометрии. Ищет заголовок ведомости листов («Ведомость рабочих чертежей основного
комплекта», «Ведомость листов», «Перечень листов графической части»…) и разбирает строки таблицы
под ним: номер листа и наименование. Ведомости ссылочных документов, спецификаций и отделки - не
ведомость листов. «Содержание тома» перечисляет документы, а не листы, и сюда не входит.

Строка ведомости в текстовом слое бывает двух видов: «5 План 3 этажа» (номер слева, как в форме по
ГОСТ Р 21.101) и «План 3 этажа 5» (номер справа). Вид выбирается большинством строк ведомости.
Не разобранная строка не становится догадкой: она или продолжает наименование предыдущей строки,
или считается шумом. Ведомость короче двух строк не принимается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

REGISTER_VERSION: Final = "consistency.sheet_register.v1"

MIN_ENTRIES: Final = 2
MAX_ENTRIES: Final = 400
TITLE_MAX: Final = 300
SNIPPET_MAX: Final = 160
_MAX_CONTINUATION: Final = 2
_MAX_NOISE: Final = 3
_SCAN_LINES: Final = 600

_FLAGS: Final = re.IGNORECASE
_SPACES_RE: Final = re.compile(r"[ \t ]+")

# Заголовок ведомости листов. После слова «ведомость» - только чертежи или листы: «Ведомость
# ссылочных…», «Ведомость спецификаций», «Ведомость отделки» сюда не подходят.
_HEADER_RE: Final = re.compile(
    r"^(?:"
    r"ведомость\s+(?:(?:рабочих|основных)\s+)?(?:чертежей|листов)\b"
    r"|(?:перечень|состав|содержание)\s+(?:(?:листов|чертежей)\s+)?графической\s+части\b"
    r"|перечень\s+(?:листов|чертежей)\b"
    r")",
    _FLAGS,
)
_CONTINUED_RE: Final = re.compile(r"продолжени|окончани", _FLAGS)
# Подписи колонок таблицы: строка только из них пропускается.
_COLUMN_WORDS: Final = frozenset(
    {
        "лист",
        "листа",
        "листы",
        "наименование",
        "примечание",
        "обозначение",
        "№",
        "п/п",
        "стр",
        "стр.",
    }
)
# Конец ведомости: следующий раздел листа или штамп.
_STOP_RE: Final = re.compile(
    r"^(?:ведомость|общие\s+указания|ссылочные|прилагаемые|спецификаци|условные\s+обозначения"
    r"|примечани[ея]\s*[:.]|технико|основные\s+показатели|изм\.?(?:\s|$)|кол\.?\s*уч"
    r"|подп\.?(?:\s|$)|разраб|н\.?\s*контр|гип\b|стадия|инв\.?\s*№|взам\.?\s*инв|согласовано)",
    _FLAGS,
)
_NUMBER: Final = r"(\d{1,3}(?:\.\d{1,2})?[а-яa-z]?)"
_LEADING_RE: Final = re.compile(rf"^(?:лист\s+)?{_NUMBER}(?:\s*[.)]\s*|\s+)(.+)$", _FLAGS)
_TRAILING_RE: Final = re.compile(rf"^(.+?)\s+(?:лист\s+)?{_NUMBER}$", _FLAGS)
_LETTER_RE: Final = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")
# Продолжение наименования на следующей строке.
_CONTINUATION_START_RE: Final = re.compile(
    r"^(?:[а-яё(]|на\s+отм|отм\.|в\s+осях|\(|\)|-)", re.UNICODE
)
_CONTINUATION_END_RE: Final = re.compile(r"(?:\b(?:на|и|в|по|с|для)|[,(\-–—])\s*$", _FLAGS)


class RegisterStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RowForm(StrEnum):
    LEADING = "leading"  # «5 План 3 этажа»
    TRAILING = "trailing"  # «План 3 этажа 5»


@dataclass(frozen=True, slots=True)
class RegisterEntry:
    number: str  # нормализованный номер листа: «05» → «5», «1.1» → «1.1»
    title: str
    snippet: str  # исходная строка, не длиннее SNIPPET_MAX


@dataclass(frozen=True, slots=True)
class RegisterPage:
    """Ведомость листов на одной странице."""

    heading: str
    continued: bool  # «(продолжение)»: строки дополняют ведомость предыдущей страницы
    form: RowForm
    entries: tuple[RegisterEntry, ...]
    duplicates: tuple[str, ...]  # номера, встреченные в ведомости больше одного раза


def normalize_number(raw: str) -> str | None:
    """Номер листа для сравнения: без ведущих нулей, «Лист 5» → «5»; не номер - None."""
    clean = _SPACES_RE.sub(" ", raw).strip().lower()
    clean = re.sub(r"^лист\s*", "", clean).rstrip(".")
    found = re.fullmatch(r"0*(\d{1,4})((?:\.\d{1,2})?[а-яa-z]?)", clean)
    if found is None:
        return None
    return f"{int(found.group(1))}{found.group(2)}"


def _lines(text: str) -> list[str]:
    result = []
    for raw in text.splitlines():
        line = _SPACES_RE.sub(" ", raw).strip()
        if line:
            result.append(line)
    return result


def _snippet(line: str) -> str:
    return line[:SNIPPET_MAX]


def _is_columns(line: str) -> bool:
    words = [word.lower() for word in line.replace("|", " ").split()]
    return bool(words) and all(word in _COLUMN_WORDS for word in words)


def _row(line: str, form: RowForm) -> tuple[str, str] | None:
    """(номер, наименование) строки ведомости заданного вида; не строка - None."""
    found = (_LEADING_RE if form is RowForm.LEADING else _TRAILING_RE).match(line)
    if found is None:
        return None
    number_raw, title = (
        (found.group(1), found.group(2))
        if form is RowForm.LEADING
        else (found.group(2), found.group(1))
    )
    number = normalize_number(number_raw)
    title = title.strip(" .;:|")
    if number is None or not _LETTER_RE.search(title):
        return None
    return number, title


def _form_of(lines: list[str]) -> RowForm:
    """Вид строк ведомости по большинству; при равенстве - номер слева (форма ГОСТ)."""
    leading = sum(1 for line in lines if _row(line, RowForm.LEADING) is not None)
    trailing = sum(
        1
        for line in lines
        if _row(line, RowForm.LEADING) is None and _row(line, RowForm.TRAILING) is not None
    )
    return RowForm.TRAILING if trailing > leading else RowForm.LEADING


def _body(lines: list[str]) -> list[str]:
    """Строки таблицы после заголовка: до следующего раздела или штампа."""
    body = []
    for line in lines[:_SCAN_LINES]:
        if _STOP_RE.match(line):
            break
        body.append(line)
    return body


def _continues(previous: str, line: str) -> bool:
    return bool(_CONTINUATION_START_RE.match(line) or _CONTINUATION_END_RE.search(previous))


def _entries(body: list[str], form: RowForm) -> tuple[list[RegisterEntry], list[str]]:
    titles: list[list[str]] = []
    numbers: list[str] = []
    snippets: list[str] = []
    continuation = 0
    noise = 0
    for line in body:
        if _is_columns(line):
            continue
        row = _row(line, form)
        if row is not None:
            numbers.append(row[0])
            titles.append([row[1]])
            snippets.append(_snippet(line))
            continuation = noise = 0
            if len(numbers) >= MAX_ENTRIES:
                break
            continue
        if titles and continuation < _MAX_CONTINUATION and _continues(titles[-1][-1], line):
            titles[-1].append(line.strip(" .;:|"))
            continuation += 1
            continue
        noise += 1
        if noise >= _MAX_NOISE:
            break
    entries: list[RegisterEntry] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for number, parts, snippet in zip(numbers, titles, snippets, strict=True):
        if number in seen:
            if number not in duplicates:
                duplicates.append(number)
            continue
        seen.add(number)
        title = " ".join(parts)[:TITLE_MAX]
        entries.append(RegisterEntry(number=number, title=title, snippet=snippet))
    return entries, duplicates


def parse_register_page(text: str) -> RegisterPage | None:
    """Ведомость листов на странице или None, если её нет или в ней меньше двух строк."""
    lines = _lines(text)
    for index, line in enumerate(lines):
        header = _HEADER_RE.match(line)
        if header is None:
            continue
        rest = line[header.end() :].strip(" .:|")
        tail = [rest] if rest and not _is_columns(rest) and not _CONTINUED_RE.search(rest) else []
        body = _body(tail + lines[index + 1 :])
        form = _form_of(body)
        entries, duplicates = _entries(body, form)
        if len(entries) < MIN_ENTRIES:
            continue
        return RegisterPage(
            heading=_snippet(line),
            continued=bool(_CONTINUED_RE.search(line)),
            form=form,
            entries=tuple(entries),
            duplicates=tuple(duplicates),
        )
    return None


# --------------------------------------------------------------------------- наименования

_ADDRESS_RE: Final = re.compile(
    r"(?<!\w)(?:корпус\w*|секци[яи]|блок[\s-]*секци[яи]|этап\w*)\s*\d+[а-яa-z]?(?:\s*[-,.]\s*\d+)*",
    _FLAGS,
)
_TOKEN_RE: Final = re.compile(r"[a-zа-я0-9]+")
TITLE_SIMILARITY_MIN: Final = 0.6


def title_tokens(title: str) -> frozenset[str]:
    """Слова наименования для сравнения: без адреса «Корпус 1. Секция 2», регистра и «ё»."""
    clean = _ADDRESS_RE.sub(" ", title.lower().replace("ё", "е"))
    return frozenset(
        token for token in _TOKEN_RE.findall(clean) if len(token) >= 3 or token.isdigit()
    )


def titles_agree(left: str, right: str) -> bool | None:
    """Наименования совпадают по словам (доля общих от меньшего ≥ 0,6); сравнивать нечего - None.

    Доля считается от меньшего набора слов: наименование в штампе часто короче, чем в ведомости.
    """
    a, b = title_tokens(left), title_tokens(right)
    if not a or not b:
        return None
    return len(a & b) / min(len(a), len(b)) >= TITLE_SIMILARITY_MIN
