"""Точка входа подпроцесса разбора одного PDF.

    python -m ... passport_cli <pdf> <имя> <out.json> <text_out>

Запускается исполнителем с пределом адресного пространства (RLIMIT_AS): тяжёлый файл убивает
только этот процесс. Результат - два файла: `out.json` (JSON-список кандидатов) и `text_out`
(gzip с текстом страниц, формат `consistency.page_text.v1` - JSON Lines, см. `page_texts`).
Текст пишется потоково по мере обхода страниц, весь документ в памяти не копится. Stdout и
stderr пусты (содержимое документов никуда не пишется).

Коды выхода: 0 - готово, 1 - прочий отказ разбора, 2 - неверные аргументы, 3 - не хватило
памяти, 4 - файл не открывается как PDF (обрезан или не PDF: `PdfReadError`/`PdfStreamError`
при открытии).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from pypdf.errors import PdfReadError, PdfStreamError

from app.services.consistency.page_texts import PageTextWriter
from app.services.consistency.passport_codec import candidate_to_json
from app.services.consistency.sheet_passport import (
    PARSER_VERSION,
    PageInput,
    extract_pdf_pages,
    parse_page,
)

EXIT_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_MEMORY: Final = 3
EXIT_UNREADABLE: Final = 4


class PdfUnreadableError(Exception):
    """PDF не открылся: pypdf не смог прочитать структуру файла."""


def _opened_pages(pages: Iterator[PageInput]) -> Iterator[PageInput]:
    """Первый шаг генератора открывает файл: отказ pypdf на нём - файл нечитаем."""
    try:
        first = next(pages, None)
    except (PdfReadError, PdfStreamError) as error:
        raise PdfUnreadableError from error
    if first is None:
        return
    yield first
    yield from pages


def run(pdf_path: Path, file_name: str, out_path: Path, text_path: Path) -> None:
    items: list[dict[str, Any]] = []
    with pdf_path.open("rb") as stream, PageTextWriter(text_path, PARSER_VERSION) as writer:
        for page in _opened_pages(extract_pdf_pages(stream, file_name)):
            items.append(candidate_to_json(parse_page(page)))
            writer.add(page.page_index, page.page_label, page.text)
    out_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return EXIT_USAGE
    try:
        run(Path(argv[0]), argv[1], Path(argv[2]), Path(argv[3]))
    except MemoryError:
        return EXIT_MEMORY
    except PdfUnreadableError:
        return EXIT_UNREADABLE
    except Exception:
        return EXIT_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
