"""Чтение PDF библиотекой plangeom: единственное место в коде, где она подключается.

plangeom (лицензии у Quantor нет, решение владельца записано в ADR-0035) стоит только в окружении
`.venv-reader` (`setup_reader_env.sh`) и подключается через `importlib.import_module` внутри
функции: нормализатор, mypy и тесты работают без неё. Результат `parse_document` пишется как
JSON и дальше читается нормализатором как обычный выход plangeom.
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

MODULE_NAME = "plangeom"
SETUP_HINT = (
    "запустите tools/building_model/setup_reader_env.sh и работайте окружением .venv-reader"
)


class _Plangeom(Protocol):
    """Нужная часть интерфейса plangeom 0.1.0a2."""

    def parse_document(
        self,
        path: Path,
        pages: list[int] | None = None,
        sections: list[str] | None = None,
        workers: int = 2,
        timeout_s: float = 300.0,
    ) -> object: ...


@dataclass(frozen=True)
class ParseSummary:
    """Агрегаты разбора: без имён, путей и содержимого чертежей."""

    seconds: float
    sheets: int
    verdicts: dict[str, int]
    bytes_written: int


def parse_pages(arg: str) -> list[int]:
    """`51,33` -> [51, 33]; повторы и отрицательные номера — ошибка."""
    try:
        pages = [int(part) for part in arg.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("--pages: ожидался список номеров через запятую, например 51,33") from exc
    if not pages:
        raise ValueError("--pages: список номеров пуст")
    if any(p < 0 for p in pages) or len(set(pages)) != len(pages):
        raise ValueError("--pages: номера должны быть неотрицательными и без повторов")
    return pages


def _load_plangeom() -> _Plangeom:
    try:
        module = importlib.import_module(MODULE_NAME)
    except ImportError as exc:
        raise ValueError(f"библиотека {MODULE_NAME} не найдена: {SETUP_HINT}") from exc
    return cast(_Plangeom, module)


def _as_json_object(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return {str(k): v for k, v in result.items()}
    for method in ("model_dump", "to_dict", "dict"):
        func = getattr(result, method, None)
        if callable(func):
            converted = func()
            if isinstance(converted, dict):
                return {str(k): v for k, v in converted.items()}
    raise ValueError(f"неожиданный тип результата plangeom: {type(result).__name__}")


def _summarize(data: dict[str, object], seconds: float, size: int) -> ParseSummary:
    raw_sheets = data.get("sheets")
    sheets = raw_sheets if isinstance(raw_sheets, list) else [data]
    verdicts: dict[str, int] = {}
    for sheet in sheets:
        verdict = sheet.get("verdict") if isinstance(sheet, dict) else None
        name = verdict if isinstance(verdict, str) else "none"
        verdicts[name] = verdicts.get(name, 0) + 1
    return ParseSummary(
        seconds=seconds,
        sheets=len(sheets),
        verdicts=dict(sorted(verdicts.items())),
        bytes_written=size,
    )


def parse_pdf(
    pdf: Path, out: Path, pages: list[int] | None = None, workers: int = 1
) -> ParseSummary:
    """PDF -> `parse_document` -> JSON (UTF-8) в `out`. Текст ошибок не содержит путей."""
    if workers < 1:
        raise ValueError("--workers: нужно целое число не меньше 1")
    if not pdf.is_file():
        raise ValueError("PDF не найден или не файл")
    plangeom = _load_plangeom()
    started = time.monotonic()
    try:
        result = plangeom.parse_document(pdf, pages=pages, workers=workers)
    except Exception as exc:
        # Текст ошибки библиотеки может содержать путь к PDF: сообщаем только вид ошибки.
        raise ValueError(f"{MODULE_NAME} завершилась ошибкой: {type(exc).__name__}") from exc
    seconds = time.monotonic() - started
    data = _as_json_object(result)
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return _summarize(data, seconds, len(text.encode("utf-8")))
