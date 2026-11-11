"""Текст страницы PDF для паспорта листа: быстрый путь для страниц с тяжёлой векторной графикой.

pypdf разбирает каждую операцию контент-потока; у страниц с миллионами операций линий
(`m l h S`) это секунды и десятки секунд на страницу. Текст при этом лежит в блоках `BT … ET`.
Тяжёлый поток урезается до этих блоков и операторов состояния (`q Q cm gs Tf Tc Tw Tz TL Tr Ts Do`):
без `Tf` вне блока шрифт не выбран и текст ломается. Урезанный поток подставляется только в копию
страницы; исходная страница и reader не меняются.
"""

from __future__ import annotations

import re
from typing import Final

from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject, StreamObject

HEAVY_CONTENT_BYTES: Final = 512 * 1024

# Символы, продолжающие токен слева и справа от оператора.
_LEFT: Final = rb"[\w.\-/*'\"]"
_AFTER: Final = rb"(?![\w*'\"])"
_STRING_BODY: Final = rb"(?:[^()\\]++|\\.|\((?:[^()\\]++|\\.)*+\))*+"

# Блок BT … ET целиком. Строки `( … )` (экранирование, один уровень вложенных скобок) и
# hex-строки `< … >` пропускаются целиком, чтобы `ET` внутри строки не обрывал блок.
# Шаблоны начинаются с литерала: поиск идёт быстро и без цикла Python по токенам.
_BLOCK: Final = (
    rb"BT(?<!"
    + _LEFT
    + rb"BT)"
    + _AFTER
    + rb"(?:"
    + rb"[^()<E]++"
    + rb"|\("
    + _STRING_BODY
    + rb"\)"
    + rb"|<<"
    + rb"|<[0-9A-Fa-f\s]*+>"
    + rb"|<"
    + rb"|E(?!T(?![\w*'\"]))"
    + rb"|(?<=[\w.\-/*'\"])E"
    + rb")*+"
    + rb"ET(?<!"
    + _LEFT
    + rb"ET)"
    + _AFTER
)

# Операторы состояния с операндами: операнды ищутся назад от оператора (их мало, цикл короткий).
_RARE_OP: Final = rb"(?:cm|gs|Tf|Tc|Tw|Tz|TL|Tr|Ts|Do)(?<!" + _LEFT + rb"..)" + _AFTER
_OPERAND_TOKEN: Final = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)|/[^\s()<>\[\]{}/%]*")
_OPERANDS_WINDOW: Final = 120
_OPERANDS_MAX: Final = 8

# q / Q — между важными элементами: пустые пары `q … Q` схлопываются.
_SAVE_RESTORE: Final = re.compile(rb"[qQ](?<!" + _LEFT + rb"[qQ])(?![\w*'\"])")
_EMPTY_PAIR: Final = re.compile(rb"q\s+Q")

_KEEP_RE: Final = re.compile(rb"(?:" + _BLOCK + rb")|(?:" + _RARE_OP + rb")")


def _save_restore_run(data: bytes, start: int, end: int) -> bytes:
    """q/Q между start и end без пустых пар `q Q`."""
    tokens = _SAVE_RESTORE.findall(data, start, end)
    if not tokens:
        return b""
    run = b" ".join(tokens)
    while len(tokens) > 1:
        shorter = _EMPTY_PAIR.sub(b" ", run)
        if shorter == run:
            break
        run = shorter
    return run.strip()


def _operands_before(data: bytes, floor: int, end: int) -> list[bytes]:
    """Операнды-числа и имена непосредственно перед оператором (не левее floor)."""
    start = max(floor, end - _OPERANDS_WINDOW)
    tokens = data[start:end].split()
    count = 0
    limit = len(tokens)
    if start > floor and start > 0 and not data[start - 1 : start].isspace():
        limit -= 1  # первый токен окна мог быть обрезан
    while count < min(limit, _OPERANDS_MAX) and _OPERAND_TOKEN.fullmatch(tokens[-1 - count]):
        count += 1
    return tokens[len(tokens) - count :]


def text_only_content(data: bytes) -> bytes:
    """Оставляет блоки `BT … ET`, операторы состояния текста и q/Q; остальное выбрасывает."""
    pieces: list[bytes] = []
    cursor = 0
    for match in _KEEP_RE.finditer(data):
        begin = match.start()
        run = _save_restore_run(data, cursor, begin)
        if run:
            pieces.append(run)
        item = match.group()
        if item.startswith(b"BT"):
            pieces.append(item)
        else:
            pieces.append(b" ".join([*_operands_before(data, cursor, begin), item]))
        cursor = match.end()
    run = _save_restore_run(data, cursor, len(data))
    if run:
        pieces.append(run)
    return b"\n".join(pieces)


def _stream_bytes(page: PageObject) -> bytes | None:
    """Распакованный контент-поток страницы одним куском; None — нет или не читается."""
    contents = page.get("/Contents")
    if contents is None:
        return None
    obj = contents.get_object()
    parts: list[bytes] = []
    if isinstance(obj, ArrayObject):
        for item in obj:
            part = item.get_object()
            if not isinstance(part, StreamObject):
                return None
            parts.append(part.get_data())
    elif isinstance(obj, StreamObject):
        parts.append(obj.get_data())
    else:
        return None
    return b"\n".join(parts)


def _trimmed_text(page: PageObject, reader: PdfReader, data: bytes) -> str:
    """extract_text на копии страницы с урезанным потоком."""
    copy = PageObject(reader)
    copy.update(page)
    stream = DecodedStreamObject()
    stream.set_data(text_only_content(data))
    copy[NameObject("/Contents")] = stream
    return copy.extract_text() or ""


def page_text(page: PageObject, reader: PdfReader) -> str:
    """Текст страницы без NUL: PostgreSQL не принимает 0x00 ни в text, ни в jsonb."""
    return _raw_page_text(page, reader).replace("\x00", "")


def _raw_page_text(page: PageObject, reader: PdfReader) -> str:
    """Тяжёлый поток урезается; любая ошибка урезанного пути — откат на полный."""
    try:
        data = _stream_bytes(page)
    except Exception:  # битый поток: полный путь сам решит, что делать
        data = None
    if data is not None and len(data) > HEAVY_CONTENT_BYTES:
        try:
            return _trimmed_text(page, reader, data)
        except Exception:
            return page.extract_text() or ""
    return page.extract_text() or ""
