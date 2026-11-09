"""Адаптер `пакеты листов -> RevitBuildingPackage` (`quantor.revit_building_package.v0`).

Чистая функция без ввода-вывода: те же входы дают те же байты. Каждый лист сначала проходит
адаптер листа (`build_package`), затем листы совмещаются по пересечениям осей сетки: начала
координат у листов свои, поэтому к плану каждого листа добавляется смещение до системы опорного
листа. Поворот не учитывается (он проявится в невязке). Ключи `QTO_Key` остаются ключами моделей
листов. Все отказы копятся и выдаются одним `RevitRefusalError`.
Подробно: docs/building-model/05-revit-building-package-v0.md.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from building_model.approval import ApprovalOut
from building_model.canonical import BuildingModel
from building_model.coords import angle_between_deg, intersection
from building_model.geometry import Pt, rnd, rnd_pt
from building_model.params import Params
from building_model.reader import AxisIn
from building_model.revit import RevitRefusalError, build_package, refusal_reasons
from building_model.revit_format import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    AdapterRef,
    Assumptions,
    AxisMatch,
    BuildingInfo,
    BuildingManifest,
    ColumnPkg,
    Coverage,
    FloorPkg,
    HolePkg,
    LevelPkg,
    NotExported,
    OpeningPkg,
    RevitBuildingPackage,
    RevitPackage,
    RoomPkg,
    ScaleStatus,
    SheetEntry,
    SkippedPage,
    StackPkg,
    WallPkg,
    WallType,
)

# Пороги прототипа, по эталону не подбирались.
AXIS_MIN_SHARED = 3
AXIS_RESIDUAL_MAX_MM = 50.0
# Невязка пары осей больше этого значения считается выбросом (счётчик в manifest, отказа не даёт).
OUTLIER_RESIDUAL_MM = 50.0
LEVEL_ELEVATION_TOL_MM = 1.0
# Сколько однотипных причин (дубликаты id) перечислять поимённо.
MAX_LISTED_DUPLICATES = 10

AxisKey = tuple[str, str]
_Placed = WallPkg | OpeningPkg | FloorPkg | ColumnPkg | StackPkg | RoomPkg


@dataclass(frozen=True)
class SheetInput:
    page: int
    model: BuildingModel
    approval: ApprovalOut | None
    model_sha256: str
    # Оси листа из входа plangeom (система листа, мм): в модели их нет.
    axes: Sequence[AxisIn]


@dataclass(frozen=True)
class Alignment:
    offset: Pt
    match: AxisMatch


def sheet_intersections(
    axes: Sequence[AxisIn], origin_sheet: Pt, params: Params
) -> dict[AxisKey, Pt]:
    """Пересечения осей в системе модели листа; ключ — отсортированная пара меток.

    Метки, встретившиеся на листе дважды, и оси без метки не участвуют.
    """
    counts = Counter(a.label for a in axes if a.label)
    usable = sorted(
        ((a.label, a) for a in axes if a.label and counts[a.label] == 1), key=lambda t: t[0]
    )
    ox, oy = origin_sheet
    result: dict[AxisKey, Pt] = {}
    for i, (first_label, first) in enumerate(usable):
        for second_label, second in usable[i + 1 :]:
            angle = angle_between_deg(first, second)
            if not params.origin_angle_min_deg <= angle <= params.origin_angle_max_deg:
                continue
            point = intersection(first, second)
            if point is None:
                continue
            key: AxisKey = (min(first_label, second_label), max(first_label, second_label))
            result[key] = (point[0] - ox, oy - point[1])
    return result


def _no_residual(shared: int) -> AxisMatch:
    return AxisMatch(shared=shared, residual_median_mm=0.0, residual_max_mm=0.0, outliers=0)


def _align_to(reference: int, points: dict[int, dict[AxisKey, Pt]]) -> dict[int, Alignment]:
    ref_points = points[reference]
    result: dict[int, Alignment] = {}
    for page, own in points.items():
        keys = sorted(set(ref_points) & set(own))
        diffs = [(ref_points[k][0] - own[k][0], ref_points[k][1] - own[k][1]) for k in keys]
        if page == reference:
            result[page] = Alignment((0.0, 0.0), _no_residual(len(own)))
            continue
        if not diffs:
            result[page] = Alignment((0.0, 0.0), _no_residual(0))
            continue
        offset = rnd_pt(
            (statistics.median(d[0] for d in diffs), statistics.median(d[1] for d in diffs)), 1
        )
        residuals = [((d[0] - offset[0]) ** 2 + (d[1] - offset[1]) ** 2) ** 0.5 for d in diffs]
        result[page] = Alignment(
            offset,
            AxisMatch(
                shared=len(diffs),
                residual_median_mm=rnd(statistics.median(residuals), 1),
                residual_max_mm=rnd(max(residuals), 1),
                outliers=sum(1 for r in residuals if r > OUTLIER_RESIDUAL_MM),
            ),
        )
    return result


def align_sheets(
    points: dict[int, dict[AxisKey, Pt]],
) -> tuple[int, dict[int, Alignment]]:
    """Опорный лист и смещения остальных.

    Опорный — лист, с которым остальные сходятся лучше всего: меньше отказов, выбросов и невязка.
    При равенстве — с наибольшим числом пересечений, затем с наименьшей страницей. Лист с самым
    большим числом осей опорным быть не обязан: ошибка в его метках испортила бы все смещения.
    """

    def rank(page: int) -> tuple[int, int, float, int, int]:
        items = [a.match for p, a in _align_to(page, points).items() if p != page]
        failed = sum(
            1
            for m in items
            if m.shared < AXIS_MIN_SHARED or m.residual_median_mm > AXIS_RESIDUAL_MAX_MM
        )
        return (
            failed,
            sum(m.outliers for m in items),
            rnd(sum(m.residual_median_mm for m in items), 1),
            -len(points[page]),
            page,
        )

    reference = min(points, key=rank)
    return reference, _align_to(reference, points)


def _alignment_reasons(reference: int, alignments: dict[int, Alignment]) -> list[str]:
    reasons: list[str] = []
    for page, item in sorted(alignments.items()):
        if page == reference:
            continue
        if item.match.shared < AXIS_MIN_SHARED:
            reasons.append(
                f"страница {page}: общих пересечений осей с опорным листом {reference} — "
                f"{item.match.shared}, нужно не меньше {AXIS_MIN_SHARED}"
            )
        elif item.match.residual_median_mm > AXIS_RESIDUAL_MAX_MM:
            reasons.append(
                f"страница {page}: медиана невязки осей {item.match.residual_median_mm} мм "
                f"больше {AXIS_RESIDUAL_MAX_MM} мм (опорный лист {reference})"
            )
    return reasons


def level_conflicts(packages: Sequence[tuple[int, RevitPackage]]) -> list[str]:
    """Уровни разных листов не должны совпадать ни по ключу, ни по отметке (в пределах допуска)."""
    entries = sorted(
        ((page, lv) for page, pkg in packages for lv in pkg.levels), key=lambda e: (e[0], e[1].id)
    )
    reasons: list[str] = []
    for i, (page_a, lv_a) in enumerate(entries):
        for page_b, lv_b in entries[i + 1 :]:
            if page_a == page_b:
                continue
            where = (
                f"{lv_a.id} (страница {page_a}, отметка {lv_a.elevation_mm} мм) и "
                f"{lv_b.id} (страница {page_b}, отметка {lv_b.elevation_mm} мм)"
            )
            if lv_a.id == lv_b.id:
                reasons.append(f"конфликт уровней: одинаковый ключ у {where}")
            elif abs(lv_a.elevation_mm - lv_b.elevation_mm) <= LEVEL_ELEVATION_TOL_MM:
                reasons.append(
                    f"конфликт уровней: разные ключи, но отметки отличаются не больше "
                    f"{LEVEL_ELEVATION_TOL_MM} мм у {where}"
                )
    return reasons


def _shift(p: Pt, offset: Pt) -> Pt:
    return rnd_pt((p[0] + offset[0], p[1] + offset[1]), 1)


def _shift_all(points: Sequence[Pt], offset: Pt) -> list[Pt]:
    return [_shift(p, offset) for p in points]


def shift_package(package: RevitPackage, offset: Pt) -> RevitPackage:
    """Копия пакета листа со смещёнными координатами плана; всё остальное не меняется."""
    return package.model_copy(
        update={
            "walls": [
                w.model_copy(
                    update={"start": _shift(w.start, offset), "end": _shift(w.end, offset)}
                )
                for w in package.walls
            ],
            "openings": [
                o.model_copy(update={"at": _shift(o.at, offset)}) for o in package.openings
            ],
            "floors": [
                f.model_copy(
                    update={
                        "boundary": _shift_all(f.boundary, offset),
                        "holes": [
                            HolePkg(kind=h.kind, boundary=_shift_all(h.boundary, offset))
                            for h in f.holes
                        ],
                    }
                )
                for f in package.floors
            ],
            "columns": [
                c.model_copy(update={"outline": _shift_all(c.outline, offset)})
                for c in package.columns
            ],
            "stacks": [
                s.model_copy(
                    update={
                        "outline": _shift_all(s.outline, offset),
                        "slab_opening": None
                        if s.slab_opening is None
                        else _shift_all(s.slab_opening, offset),
                    }
                )
                for s in package.stacks
            ],
            "rooms": [
                r.model_copy(
                    update={
                        "boundary": _shift_all(r.boundary, offset),
                        "point": _shift(r.point, offset),
                    }
                )
                for r in package.rooms
            ],
            "not_exported": [
                n.model_copy(update={"at": None if n.at is None else _shift(n.at, offset)})
                for n in package.not_exported
            ],
        }
    )


def _distinct(values: dict[int, str]) -> str:
    groups: dict[str, list[int]] = {}
    for page, value in sorted(values.items()):
        groups.setdefault(value, []).append(page)
    return "; ".join(
        f"страницы {', '.join(str(p) for p in pages)}: {value}" for value, pages in groups.items()
    )


def _uniformity_reasons(packages: Sequence[tuple[int, RevitPackage]]) -> list[str]:
    reasons: list[str] = []
    checks: dict[str, dict[int, str]] = {
        "разные читатель или версия нормализатора": {
            p: pkg.manifest.reader.model_dump_json() for p, pkg in packages
        },
        "разные версии тендера": {p: pkg.manifest.tender.model_dump_json() for p, pkg in packages},
        "разные допущения (параметры прототипа)": {
            p: pkg.manifest.assumptions.params.model_dump_json() for p, pkg in packages
        },
    }
    for title, values in checks.items():
        if len(set(values.values())) > 1:
            reasons.append(f"{title}: {_distinct(values)}")
    return reasons


def _sum_coverage(packages: Sequence[tuple[int, RevitPackage]]) -> dict[str, Coverage]:
    total: Counter[str] = Counter()
    exported: Counter[str] = Counter()
    for _, pkg in packages:
        for kind, cov in pkg.manifest.coverage.items():
            total[kind] += cov.total
            exported[kind] += cov.exported
    return {
        kind: Coverage(
            total=total[kind], exported=exported[kind], not_exported=total[kind] - exported[kind]
        )
        for kind in sorted(total)
    }


def _merge_wall_types(packages: Sequence[RevitPackage]) -> list[WallType]:
    merged: dict[str, WallType] = {}
    for pkg in packages:
        for t in pkg.wall_types:
            old = merged.get(t.id)
            count = t.count + (old.count if old is not None else 0)
            merged[t.id] = WallType(id=t.id, thickness_mm=t.thickness_mm, count=count)
    return sorted(merged.values(), key=lambda t: (t.thickness_mm, t.id))


def duplicate_reasons(shifted: Sequence[tuple[int, RevitPackage]]) -> list[str]:
    first: dict[str, int] = {}
    reasons: list[str] = []
    for page, pkg in shifted:
        groups: list[Sequence[_Placed]] = [
            pkg.walls,
            pkg.openings,
            pkg.floors,
            pkg.columns,
            pkg.stacks,
            pkg.rooms,
        ]
        for group in groups:
            for item in group:
                if item.id in first:
                    reasons.append(
                        f"дубликат id {item.id} после слияния (страницы {first[item.id]} и {page})"
                    )
                else:
                    first[item.id] = page
    if len(reasons) > MAX_LISTED_DUPLICATES:
        rest = len(reasons) - MAX_LISTED_DUPLICATES
        return [*reasons[:MAX_LISTED_DUPLICATES], f"дубликатов id ещё {rest}"]
    return reasons


def _missing_floors(levels: Sequence[LevelPkg]) -> list[int]:
    floors = {lv.floor for lv in levels if lv.floor is not None}
    if not floors:
        return []
    # Этажа с номером 0 в нумерации чертежей нет: после -1 идёт 1.
    return [f for f in range(min(floors), max(floors) + 1) if f != 0 and f not in floors]


def _sum_assumed(packages: Sequence[RevitPackage]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for pkg in packages:
        total.update(pkg.manifest.assumptions.assumed_elements)
    return dict(sorted(total.items()))


def build_building_package(
    sheets: Sequence[SheetInput],
    building: int,
    added_pages: Sequence[int],
    excluded_pages: Sequence[int],
    skipped: Sequence[SkippedPage],
    input_sha256: str,
) -> RevitBuildingPackage:
    """Пакет здания из листов. Отказ (`RevitRefusalError`) перечисляет все причины сразу."""
    if not sheets:
        raise ValueError("в составе нет ни одного листа-плана")
    pages = [s.page for s in sheets]
    if len(set(pages)) != len(pages):
        raise ValueError("страница листа повторяется в составе")
    ordered = sorted(sheets, key=lambda s: s.page)
    reasons: list[str] = []
    built: list[tuple[int, SheetInput, RevitPackage]] = []
    for sheet in ordered:
        own = refusal_reasons(sheet.model, sheet.approval, sheet.model_sha256)
        if own:
            reasons.extend(f"страница {sheet.page}: {r}" for r in own)
            continue
        package = build_package(sheet.model, sheet.approval, sheet.model_sha256)
        if package.manifest.page != sheet.page:
            reasons.append(f"страница {sheet.page}: файл модели относится к другой странице")
            continue
        built.append((sheet.page, sheet, package))
    if not built:
        raise RevitRefusalError("; ".join(reasons))
    packages = [(page, pkg) for page, _, pkg in built]
    reasons.extend(_uniformity_reasons(packages))
    reasons.extend(level_conflicts(packages))

    points: dict[int, dict[AxisKey, Pt]] = {}
    for page, sheet, _ in built:
        params = Params.model_validate(sheet.model.params)
        points[page] = sheet_intersections(sheet.axes, sheet.model.origin.sheet_mm, params)
    reference, alignments = align_sheets(points)
    reasons.extend(_alignment_reasons(reference, alignments))

    shifted = [(page, shift_package(pkg, alignments[page].offset)) for page, pkg in packages]
    if not reasons:
        reasons.extend(duplicate_reasons(shifted))
    if reasons:
        raise RevitRefusalError("; ".join(reasons))

    merged = [pkg for _, pkg in shifted]
    levels = sorted(
        (lv for pkg in merged for lv in pkg.levels), key=lambda lv: (lv.elevation_mm, lv.id)
    )
    ref_manifest = dict(packages)[reference].manifest
    approved_all = all(sheet.approval is not None for _, sheet, _ in built)
    scale_status: ScaleStatus = "human" if approved_all else "candidate"
    entries = [
        SheetEntry(
            page=page,
            model_sha256=sheet.model_sha256,
            scale_status=pkg.manifest.scale_status,
            approval=sheet.approval,
            levels=[lv.id for lv in pkg.levels],
            offset_mm=alignments[page].offset,
            axis_match=alignments[page].match,
            coverage=pkg.manifest.coverage,
            review_summary=pkg.manifest.review_summary,
        )
        for page, sheet, pkg in built
    ]
    manifest = BuildingManifest(
        building=BuildingInfo(
            group=building,
            reference_page=reference,
            added_pages=sorted(set(added_pages)),
            excluded_pages=sorted(set(excluded_pages)),
            skipped_pages=sorted(skipped, key=lambda s: s.page),
            missing_floors=_missing_floors(levels),
            input_sha256=input_sha256,
        ),
        sheets=entries,
        tender=ref_manifest.tender,
        reader=ref_manifest.reader,
        adapter=AdapterRef(name=ADAPTER_NAME, version=ADAPTER_VERSION),
        origin=ref_manifest.origin,
        scale_status=scale_status,
        coverage=_sum_coverage(packages),
        assumptions=Assumptions(
            params=ref_manifest.assumptions.params, assumed_elements=_sum_assumed(merged)
        ),
    )
    not_exported: list[NotExported] = [n for pkg in merged for n in pkg.not_exported]
    return RevitBuildingPackage(
        manifest=manifest,
        levels=levels,
        wall_types=_merge_wall_types(merged),
        walls=sorted((w for pkg in merged for w in pkg.walls), key=lambda x: x.id),
        openings=sorted((o for pkg in merged for o in pkg.openings), key=lambda x: x.id),
        floors=sorted((f for pkg in merged for f in pkg.floors), key=lambda x: x.id),
        columns=sorted((c for pkg in merged for c in pkg.columns), key=lambda x: x.id),
        stacks=sorted((s for pkg in merged for s in pkg.stacks), key=lambda x: x.id),
        rooms=sorted((r for pkg in merged for r in pkg.rooms), key=lambda x: x.id),
        not_exported=sorted(not_exported, key=lambda n: (n.kind, n.key, n.reason)),
    )
