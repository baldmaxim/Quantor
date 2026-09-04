"""Разбор `*_results.md` — терпимый индекс секций.

Markdown здесь не превращается в HTML и не разбирается семантически. Нужен только указатель:
какому block_id соответствует какой кусок исходного текста. Разбор Summary, Description
и Entities — задача следующего этапа, и делать его сейчас значит зафиксировать формат,
который ещё изменится.

Текст сохраняется как есть и на экране показывается как обычный текст, а не как разметка:
содержимое пришло из недоверенного архива.
"""

from __future__ import annotations

import re
from typing import Final

# Заголовок секции: `### BLOCK #27 [IMAGE]: blk_abc123`.
# Номер и тип необязательны — экспорт менялся, и требовать их значит терять данные
# на чуть более старых пакетах.
_HEADING: Final = re.compile(
    r"^\s{0,3}#{1,6}\s+BLOCK\s*(?:#(?P<ordinal>\d+))?\s*(?:\[(?P<type>[^\]]*)\])?\s*:?\s*"
    r"(?P<block_id>\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Ограничение на длину одной секции: содержимое приходит из недоверенного файла,
# и одна секция не должна занимать всю память процесса.
MAX_SECTION_CHARS: Final = 64 * 1024


def index_sections(text: str) -> dict[str, str]:
    """Возвращает соответствие block_id → исходный текст секции.

    Секция — всё между её заголовком и следующим заголовком блока. Если файл не разбирается
    или заголовков в нём нет, возвращается пустой указатель: это повод импортировать пакет
    без текстов, а не отказывать в импорте целиком.
    """
    sections: dict[str, str] = {}
    matches = list(_HEADING.finditer(text))

    for position, match in enumerate(matches):
        block_id = match.group("block_id").strip().strip(":")
        if not block_id:
            continue

        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        # При повторе block_id побеждает первая секция: экспорт иногда дублирует блоки,
        # и первая запись ближе к исходному порядку.
        sections.setdefault(block_id, body[:MAX_SECTION_CHARS])

    return sections


def decode(raw: bytes) -> str:
    """Декодирует файл, не падая на неожиданной кодировке.

    Русскоязычный Markdown обязан читаться. Ошибки декодирования заменяются, а не приводят
    к отказу: потерять один символ лучше, чем весь импорт.
    """
    return raw.decode("utf-8", errors="replace")
