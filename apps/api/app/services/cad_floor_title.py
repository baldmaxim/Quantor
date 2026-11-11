"""Подпись этажа по заголовку плана: «К9 · С3 · 14 эт.» (зеркало `formatFloorTitle` веб-клиента)."""

from __future__ import annotations

from app.contracts.cad_constructions import CadSheetFloorTitle


def floors_text(floors: list[str]) -> str | None:
    """Этажи: один — «14», подряд — «2–5», иначе перечисление «2, 4». Нет этажей — `None`."""
    if not floors:
        return None
    numbers = [int(f) for f in floors if f.lstrip("-").isdigit()]
    if len(numbers) == len(floors) and len(numbers) > 1:
        ordered = sorted(numbers)
        if ordered[-1] - ordered[0] == len(ordered) - 1 and len(set(ordered)) == len(ordered):
            return f"{ordered[0]}–{ordered[-1]}"
    return ", ".join(floors)


def format_floor_title(title: CadSheetFloorTitle | None, fallback: str) -> str:
    """Короткая подпись листа этажом; ни корпуса, ни секции, ни этажа нет — `fallback`."""
    if title is None:
        return fallback
    parts: list[str] = []
    if title.corps:
        parts.append(f"К{title.corps}")
    if title.section:
        parts.append(f"С{title.section}")
    floors = floors_text(title.floors)
    if floors:
        parts.append(f"{floors} эт.")
    return " · ".join(parts) if parts else fallback
