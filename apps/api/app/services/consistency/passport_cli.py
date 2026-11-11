"""Точка входа подпроцесса разбора одного PDF: `python -m ... passport_cli <pdf> <имя> <out.json>`.

Запускается исполнителем с пределом адресного пространства (RLIMIT_AS): тяжёлый файл убивает
только этот процесс. Результат - JSON-список кандидатов в файле `out.json`; stdout и stderr
пусты (содержимое документов никуда не пишется). Коды выхода: 0 - готово, 2 - неверные
аргументы, 3 - не хватило памяти, 1 - прочий отказ разбора.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

from app.services.consistency.passport_codec import candidate_to_json
from app.services.consistency.sheet_passport import extract_pdf_pages, parse_page

EXIT_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_MEMORY: Final = 3


def run(pdf_path: Path, file_name: str, out_path: Path) -> None:
    with pdf_path.open("rb") as stream:
        pages = extract_pdf_pages(stream, file_name)
        items = [candidate_to_json(parse_page(page)) for page in pages]
    out_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return EXIT_USAGE
    try:
        run(Path(argv[0]), argv[1], Path(argv[2]))
    except MemoryError:
        return EXIT_MEMORY
    except Exception:
        return EXIT_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
