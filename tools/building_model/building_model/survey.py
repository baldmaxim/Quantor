"""Обзор комплекта: агрегаты по каждому листу-плану и по группам типовых этажей.

Выход содержит только числа и номера страниц (без названий, марок и текстов штампов), чтобы его
можно было читать и печатать по реальному комплекту.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from collections.abc import Sequence

from pydantic import JsonValue

from building_model.modelstats import band_label
from building_model.params import Params
from building_model.pipeline import TenderArgs, build_sheet_model
from building_model.reader import Document, Excluded, SheetValidationError, read_sheet

Row = dict[str, JsonValue]


def _num(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _obj(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _row(page: int, stats: dict[str, JsonValue], seconds: float) -> Row:
    walls = _obj(stats["walls"])
    openings = _obj(stats["openings"])
    review = _obj(stats["review"])
    sheet = _obj(stats["sheet"])
    floors = sheet.get("floors")
    return {
        "page": page,
        "building_group": sheet.get("building_group"),
        "section_present": bool(sheet.get("section")),
        "floors_count": len(floors) if isinstance(floors, list) else 0,
        "pieces_input": walls["pieces_total"],
        "rejected_thin": walls["rejected_thin"],
        "rejected_short": walls["rejected_short"],
        "no_centerline": walls["without_segments"],
        "no_centerline_area_m2": walls["without_segments_area_m2"],
        "plangeom_wall_area_m2": walls["plangeom_area_m2"],
        "outline_axis": walls["outline_axis"],
        "walls_merged": walls["merged"],
        "bridged_gaps": walls["bridged_gaps"],
        "dangling_ends": walls["dangling_ends"],
        "dangling_ends_near_opening": walls["dangling_ends_near_opening"],
        "wall_length_m": walls["length_m_total"],
        "kept_pieces_length_m": walls["kept_pieces_length_m"],
        "bridged_gap_length_m": walls["bridged_gap_length_m"],
        "dangling_gap_to_face_mm": walls["dangling_gap_to_face_mm"],
        "wall_area_m2": walls["area_m2"],
        "wall_length_m_by_band": walls["length_m_by_thickness_band"],
        "doors": openings.get("door_total", 0),
        "doors_hosted": openings.get("door_hosted", 0),
        "doors_host_compared": openings.get("door_host_compared_with_plangeom", 0),
        "doors_host_matches": openings.get("door_host_matches_plangeom", 0),
        "windows": openings.get("window_total", 0),
        "windows_hosted": openings.get("window_hosted", 0),
        "voids": openings.get("opening_total", 0),
        "voids_hosted": openings.get("opening_hosted", 0),
        "blockers": review["blocker"],
        "warnings": review["warning"],
        "info": review["info"],
        "review_by_code": stats["review_by_code"],
        "seconds": round(seconds, 2),
    }


def _sum_hist(rows: Sequence[Row]) -> dict[str, JsonValue]:
    total: dict[str, float] = {}
    for r in rows:
        for label, count in _obj(r["dangling_gap_to_face_mm"]).items():
            total[label] = total.get(label, 0.0) + _num(count)
    return {k: int(v) for k, v in total.items()}


def _sum_outline(rows: Sequence[Row]) -> dict[str, JsonValue]:
    total: dict[str, dict[str, JsonValue]] = {}
    for r in rows:
        for outcome, value in _obj(r["outline_axis"]).items():
            bucket = total.setdefault(outcome, {"walls": 0, "area_m2": 0.0, "axis_length_m": 0.0})
            for field, number in _obj(value).items():
                bucket[field] = _num(bucket[field]) + _num(number)
    return {
        outcome: {
            "walls": int(_num(b["walls"])),
            "area_m2": round(_num(b["area_m2"]), 1),
            "axis_length_m": round(_num(b["axis_length_m"]), 1),
        }
        for outcome, b in total.items()
    }


def _spread(values: Sequence[float]) -> dict[str, JsonValue]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "max": round(max(values), 2),
    }


def _group_summary(rows: Sequence[Row], bands: Sequence[float]) -> dict[str, JsonValue]:
    labels = sorted({k for r in rows for k in _obj(r["wall_length_m_by_band"])})
    # Порядок классов — по возрастанию границы, а не по алфавиту.
    order = [band_label(b - 0.5, bands) for b in sorted(bands)] + [band_label(max(bands), bands)]
    ordered = [lbl for lbl in order if lbl in labels]
    by_band: dict[str, JsonValue] = {
        lbl: _spread([_num(_obj(r["wall_length_m_by_band"]).get(lbl, 0.0)) for r in rows])
        for lbl in ordered
    }
    return {
        "sheets": len(rows),
        "wall_length_m": _spread([_num(r["wall_length_m"]) for r in rows]),
        "wall_area_m2": _spread([_num(r["wall_area_m2"]) for r in rows]),
        "wall_length_m_by_band": by_band,
        "doors": _spread([_num(r["doors"]) for r in rows]),
        "windows": _spread([_num(r["windows"]) for r in rows]),
        "voids": _spread([_num(r["voids"]) for r in rows]),
    }


def _pick_typical(rows: Sequence[Row], groups: dict[int, list[Row]]) -> dict[str, JsonValue] | None:
    """Лист с ≥2 этажей штампа, разделом АР или пустым и площадью стен у медианы группы."""
    best: tuple[float, int, int] | None = None
    for group, members in groups.items():
        median = statistics.median(_num(r["wall_area_m2"]) for r in members)
        if median <= 0:
            continue
        for r in members:
            if _num(r["floors_count"]) < 2 or r["section_present_ar"] is False:
                continue
            deviation = abs(_num(r["wall_area_m2"]) - median) / median
            page = int(_num(r["page"]))
            candidate = (deviation, page, group)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        return None
    return {
        "page": best[1],
        "building_group": best[2],
        "area_deviation_from_median": round(best[0], 4),
    }


def run_survey(doc: Document, params: Params, tender: TenderArgs) -> dict[str, JsonValue]:
    rows: list[Row] = []
    excluded: Counter[str] = Counter()
    failed: list[JsonValue] = []
    for page in doc.pages():
        raw_section = doc.sheets[page].get("section")
        try:
            started = time.perf_counter()
            sheet = read_sheet(doc, page)
            if isinstance(sheet, Excluded):
                excluded[sheet.reason] += 1
                continue
            model = build_sheet_model(
                sheet, doc.known_elevations_mm(page), doc.building_of(page), tender, params
            )
            seconds = time.perf_counter() - started
        except SheetValidationError as exc:
            excluded["invalid"] += 1
            failed.append({"page": page, "error": str(exc)})
            continue
        row = _row(page, model.stats, seconds)
        # Раздел АР: пусто тоже годится (раздел комплекта не определён, его задаёт портал).
        row["section_present_ar"] = raw_section in (None, "", "АР")
        rows.append(row)

    groups: dict[int, list[Row]] = {}
    for r in rows:
        g = r["building_group"]
        groups.setdefault(int(_num(g)) if g is not None else -1, []).append(r)
    group_out: dict[str, JsonValue] = {}
    for g, members in sorted(groups.items()):
        typical = [r for r in members if _num(r["floors_count"]) >= 2]
        group_out[str(g)] = {
            "all": _group_summary(members, params.survey_thickness_bands_mm),
            "typical_2plus_floors": _group_summary(typical, params.survey_thickness_bands_mm),
        }
    total_doors = sum(_num(r["doors_host_compared"]) for r in rows)
    total_match = sum(_num(r["doors_host_matches"]) for r in rows)
    totals: dict[str, JsonValue] = {
        "plan_sheets_built": len(rows),
        "pieces_input": sum(_num(r["pieces_input"]) for r in rows),
        "rejected_thin": sum(_num(r["rejected_thin"]) for r in rows),
        "rejected_short": sum(_num(r["rejected_short"]) for r in rows),
        "walls_merged": sum(_num(r["walls_merged"]) for r in rows),
        "outline_axis": _sum_outline(rows),
        "no_centerline": sum(_num(r["no_centerline"]) for r in rows),
        "no_centerline_area_m2": round(sum(_num(r["no_centerline_area_m2"]) for r in rows), 1),
        "plangeom_wall_area_m2": round(sum(_num(r["plangeom_wall_area_m2"]) for r in rows), 1),
        "bridged_gaps": sum(_num(r["bridged_gaps"]) for r in rows),
        "dangling_ends": sum(_num(r["dangling_ends"]) for r in rows),
        "dangling_ends_near_opening": sum(_num(r["dangling_ends_near_opening"]) for r in rows),
        "kept_pieces_length_m": round(sum(_num(r["kept_pieces_length_m"]) for r in rows), 1),
        "wall_length_m": round(sum(_num(r["wall_length_m"]) for r in rows), 1),
        "bridged_gap_length_m": round(sum(_num(r["bridged_gap_length_m"]) for r in rows), 1),
        "dangling_gap_to_face_mm": _sum_hist(rows),
        "doors": sum(_num(r["doors"]) for r in rows),
        "doors_hosted": sum(_num(r["doors_hosted"]) for r in rows),
        "doors_host_compared": total_doors,
        "doors_host_matches": total_match,
        "doors_host_match_share": round(total_match / total_doors, 4) if total_doors else None,
        "windows": sum(_num(r["windows"]) for r in rows),
        "windows_hosted": sum(_num(r["windows_hosted"]) for r in rows),
        "voids": sum(_num(r["voids"]) for r in rows),
        "voids_hosted": sum(_num(r["voids_hosted"]) for r in rows),
        "blockers": sum(_num(r["blockers"]) for r in rows),
        "warnings": sum(_num(r["warnings"]) for r in rows),
        "seconds_total": round(sum(_num(r["seconds"]) for r in rows), 1),
    }
    return {
        "pages_in_set": len(doc.sheets),
        "excluded_by_reason": dict(sorted(excluded.items())),
        "invalid_sheets": failed,
        "totals": totals,
        "sheets": list(rows),
        "groups": group_out,
        "typical_candidate": _pick_typical(rows, groups),
    }


def _fmt_spread(spread: JsonValue) -> str:
    s = _obj(spread)
    if not s.get("n"):
        return "-"
    return f"{s['min']}/{s['median']}/{s['max']}"


def print_survey(result: dict[str, JsonValue]) -> None:
    """Печать только агрегатов: числа, счётчики и номера страниц."""
    print(f"страниц в комплекте: {result['pages_in_set']}")
    print(f"исключено по причинам: {json.dumps(result['excluded_by_reason'], ensure_ascii=False)}")
    print(f"итоги: {json.dumps(result['totals'], ensure_ascii=False)}")
    print(
        "лист: группа, этажей штампа | участков, тонких, коротких, стен, мостов, висячих(у проёма)"
        " | длина м, площадь м2 | двери хозяин/всего, окна хозяин/всего, проёмы хозяин/всего"
        " | блок, предупр | с"
    )
    for row in result["sheets"] if isinstance(result["sheets"], list) else []:
        r = _obj(row)
        print(
            f"{r['page']}: g{r['building_group']}, fl{r['floors_count']} | "
            f"{r['pieces_input']}, {r['rejected_thin']}, {r['rejected_short']}, "
            f"{r['walls_merged']}, "
            f"{r['bridged_gaps']}, {r['dangling_ends']}({r['dangling_ends_near_opening']}) | "
            f"{r['wall_length_m']}, {r['wall_area_m2']} | "
            f"{r['doors_hosted']}/{r['doors']}, {r['windows_hosted']}/{r['windows']}, "
            f"{r['voids_hosted']}/{r['voids']} | {r['blockers']}, {r['warnings']} | {r['seconds']}"
        )
    print("группы (min/медиана/max):")
    for g, summary in _obj(result["groups"]).items():
        for subset, label in (("all", "все планы"), ("typical_2plus_floors", "типовые >=2 этажей")):
            s = _obj(_obj(summary)[subset])
            if not s.get("sheets"):
                print(f"  группа {g}, {label}: листов 0")
                continue
            bands = {k: _fmt_spread(v) for k, v in _obj(s["wall_length_m_by_band"]).items()}
            print(
                f"  группа {g}, {label}: листов {s['sheets']}; "
                f"длина стен м {_fmt_spread(s['wall_length_m'])}; "
                f"площадь м2 {_fmt_spread(s['wall_area_m2'])}; двери {_fmt_spread(s['doors'])}; "
                f"окна {_fmt_spread(s['windows'])}; проёмы {_fmt_spread(s['voids'])}; "
                f"по классам толщины {json.dumps(bands, ensure_ascii=False)}"
            )
    print(f"кандидат типового листа: {json.dumps(result['typical_candidate'], ensure_ascii=False)}")
