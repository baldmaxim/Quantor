"""Команда `run`: PDF -> plangeom -> модели и разметка. Пакеты для Revit здесь не строятся."""

from __future__ import annotations

from pathlib import Path

from building_model.markup import MarkupResult, run_markup, write_index
from building_model.parse_pdf import parse_pdf

NEXT_STEP = (
    "Следующий шаг: откройте {index}, проверьте листы по PNG и легенде, подтвердите масштаб и "
    "модель листа командой approve (команда есть в таблице), затем соберите пакет командой revit "
    "с --approval."
)


def run_pipeline(
    pdf: Path | None,
    out_dir: Path,
    pages: list[int] | None,
    input_path: Path | None,
    workers: int,
) -> tuple[MarkupResult, Path]:
    """parse (пропускается при готовом входе) -> markup. Возвращает результат и index.html."""
    if input_path is None:
        if pdf is None:
            raise ValueError("нужен --pdf или готовый --input")
        input_path = out_dir / "set.json"
        summary = parse_pdf(pdf, input_path, pages, workers)
        verdicts = ", ".join(f"{k}: {v}" for k, v in summary.verdicts.items())
        print(f"parse: листов {summary.sheets} ({verdicts}), {summary.seconds:.1f} с")
    result = run_markup(input_path, pdf, out_dir, pages)
    index = write_index(result, out_dir)
    return result, index
