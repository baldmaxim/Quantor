"""Исходные величины для высоты стены: отметка пола и высота этажа из заголовков планов.

Отметка и высота разбираются теми же правилами, что у генератора трасс (cad_mep.elevations),
без значений человека. Объём считает API: скрипт отдаёт исходные величины, не итог.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf

from cad_walls.errors import WallsError
from cad_walls.params import Params

if TYPE_CHECKING:
    from cad_mep.params import Params as MepParams


def _base(p: Params) -> dict[str, object]:
    return {
        "floor_elevation_mm": None,
        "floor_height_mm": None,
        "elevation_status": "missing",
        "height_status": "missing",
        "evidence": None,
        "message": None,
        "slab_thickness_mm": p.count("slab_thickness_mm"),
        "slab_status": "assumption",
        "door_height_mm": p.count("door_height_mm"),
        "door_height_status": "assumption",
        "title": None,
    }


def _plan_title(
    pdf: Path, page: int, at: tuple[float, float], mep: MepParams
) -> dict[str, object] | None:
    """Заголовок плана листа: корпус, секция, этажи. Не найден — None.

    Выбор как у отметки пола: однозначный заголовок «План N этажа на отм. …» ближе к центру листа,
    иначе ближайший заголовок с этажами; отметка для заголовка не обязательна.
    """
    from cad_mep import elevations
    from cad_mep.errors import MepError

    try:
        titles = elevations.parse_titles(elevations.read_lines(pdf, mep), mep)
    except MepError:
        return None
    on_page = [t for t in titles if t.page == page and t.floors]
    if not on_page:
        return None
    single = [t for t in on_page if len(t.pairs) == 1 and len(t.floors) == 1]
    pool = single or on_page
    best = min(pool, key=lambda t: (t.cx - at[0]) ** 2 + (t.cy - at[1]) ** 2)
    return {
        "corps": best.corps,
        "section": best.section,
        "floors": list(best.floors),
        "text": best.text,
    }


def resolve_heights(pdf: Path | None, page: int | None, p: Params) -> dict[str, object]:
    """Блок `heights` результата; без PDF или при ошибке разбора — статус `missing` с текстом."""
    out = _base(p)
    if pdf is None or page is None:
        out["message"] = "PDF плана не передан: отметка пола и высота этажа не определены"
        return out
    from cad_mep import elevations
    from cad_mep.errors import MepError
    from cad_mep.params import load_params

    try:
        doc = pymupdf.open(str(pdf))
    except (OSError, RuntimeError, ValueError) as exc:
        raise WallsError("pdf_unreadable", f"PDF не открывается: {exc}") from exc
    try:
        if not 0 <= page < doc.page_count:
            raise WallsError("bad_page", f"в PDF нет страницы с индексом {page}")
        rect = doc[page].rect
        at = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    finally:
        doc.close()
    mep = load_params(None)
    out["title"] = _plan_title(pdf, page, at, mep)
    try:
        resolved = elevations.resolve(pdf, page, at, mep, None, None)
    except MepError as exc:
        out["message"] = exc.message
        return out
    out["floor_elevation_mm"] = resolved.elevation.value_mm
    out["floor_height_mm"] = resolved.height.value_mm
    out["elevation_status"] = resolved.elevation.source
    out["height_status"] = resolved.height.source
    out["evidence"] = f"{resolved.elevation.evidence}; {resolved.height.evidence}"
    return out
