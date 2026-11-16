"""Пороги качества результатов CAD-конвейера: конструкции листа и зоны помещений.

Ревью движка на ЖК Знаки (2026-11-16): результат с нулём конструкций, без высоты этажа или с
плитой «по стенам» публиковался как «готов», а зона, расходящаяся с экспликацией в разы, шла в
плиту и перегородки. Здесь - чистые функции: статус считает портал по уже проверенным файлам
генераторов (walls.json, zones.json), сам ничего не измеряет и физических величин не выдаёт.

Все допуски собраны в этом модуле.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.contracts.cad_constructions import WallsDocument
from app.services.cad_zones import derive_room_type

# --------------------------------------------------------------------------- допуски
# Допуски ревью 2026-11-16, владельцем не подтверждены.

# Конструкции: доля площади с неопределённой толщиной (`thickness_status = check`).
WALLS_CHECK_AREA_SHARE_MAX: Final = 0.05
# Конструкции: доля дверей, у которых не найден разрыв стены.
WALLS_DOORS_WITHOUT_GAP_SHARE_MAX: Final = 0.10
# Зоны: |площадь контура - экспликация| / экспликация, выше допуска - «на проверку».
ZONE_REVIEW_TOLERANCE_APARTMENT_ROOM: Final = 0.10
ZONE_REVIEW_TOLERANCE_BATH: Final = 0.15
ZONE_REVIEW_TOLERANCE_MOP: Final = 0.15
# Зоны: площадь контура больше или меньше экспликации в разы - зона отклонена.
ZONE_FAILED_AREA_RATIO_MAX: Final = 1.5
ZONE_FAILED_AREA_RATIO_MIN: Final = 0.5

# --------------------------------------------------------------------------- конструкции

# Запас сравнения с порогом: значение ровно на пороге (10,0 % при допуске 10 %) в допуске.
_EPSILON: Final = 1e-9

WallsQualityStatus = Literal["ok", "review"]
WALLS_SLAB_WALLS_ONLY: Final = "walls_only"
NO_EXPLICATION: Final = "нет данных экспликации"


@dataclass(frozen=True, slots=True)
class QualityReason:
    code: str
    text: str


def _num(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def walls_reasons(document: WallsDocument) -> list[QualityReason]:
    """Причины, по которым результат конструкций требует проверки; пусто - замечаний нет."""
    reasons: list[QualityReason] = []
    if not document.constructions:
        reasons.append(QualityReason("no_constructions", "на плане нет конструкций"))
    if document.heights.floor_height_mm is None:
        reasons.append(QualityReason("floor_height_missing", "высота этажа не определена"))
    if document.slab is not None and document.slab.basis == WALLS_SLAB_WALLS_ONLY:
        reasons.append(
            QualityReason("slab_walls_only", "плита построена только по стенам, без зон помещений")
        )
    total = math.fsum(item.area_plan_mm2 for item in document.constructions)
    unsure = math.fsum(
        item.area_plan_mm2 for item in document.constructions if item.thickness_status == "check"
    )
    if total > 0 and unsure / total > WALLS_CHECK_AREA_SHARE_MAX + _EPSILON:
        reasons.append(
            QualityReason(
                "thickness_check_share",
                f"толщина не определена у {_num(unsure / total * 100)} % площади конструкций "
                f"(порог {_num(WALLS_CHECK_AREA_SHARE_MAX * 100, 0)} %)",
            )
        )
    doors = [item for item in document.openings if item.kind == "door"]
    without_gap = sum(1 for item in doors if item.status == "no_data")
    if doors and without_gap / len(doors) > WALLS_DOORS_WITHOUT_GAP_SHARE_MAX + _EPSILON:
        reasons.append(
            QualityReason(
                "doors_without_gap",
                f"дверей без разрыва стены: {without_gap} из {len(doors)} "
                f"(порог {_num(WALLS_DOORS_WITHOUT_GAP_SHARE_MAX * 100, 0)} %)",
            )
        )
    return reasons


def walls_quality(document: WallsDocument) -> dict[str, object]:
    """Блок `quality` итога задания `cad_walls`: статус и причины по-русски."""
    reasons = walls_reasons(document)
    return {
        "status": "review" if reasons else "ok",
        "reasons": [{"code": item.code, "text": item.text} for item in reasons],
    }


def walls_result_quality(result: dict[str, Any]) -> tuple[WallsQualityStatus | None, list[str]]:
    """Качество из итога задания `cad_walls`: статус и причины; итога нет - `(None, [])`.

    Итог задания до появления порога блока `quality` не содержит. По нему видно только самое
    грубое: ни одной конструкции (счётчик `counts.constructions`) - этого достаточно, чтобы
    пустой лист не показывался готовым без пересчёта.
    """
    if not result:
        return None, []
    block = result.get("quality")
    if isinstance(block, dict):
        raw = block.get("reasons")
        texts = [
            str(item["text"])
            for item in (raw if isinstance(raw, list) else [])
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return ("review" if block.get("status") == "review" else "ok"), texts
    counts = result.get("counts")
    if isinstance(counts, dict) and counts.get("constructions") == 0:
        return "review", ["на плане нет конструкций"]
    return None, []


# --------------------------------------------------------------------------- зоны

ZoneQualityStatus = Literal["ok", "review", "failed"]


@dataclass(frozen=True, slots=True)
class ZoneQuality:
    status: ZoneQualityStatus
    reason: str | None


def polygon_key(points: Sequence[Sequence[float]]) -> tuple[tuple[float, float], ...]:
    """Ключ контура без учёта начальной вершины и направления обхода."""
    return tuple(sorted((round(float(x), 6), round(float(y), 6)) for x, y in points))


def duplicate_polygons(polygons: Sequence[Sequence[Sequence[float]]]) -> dict[int, int]:
    """Индексы зон с одинаковым контуром: индекс -> индекс другой зоны с тем же контуром."""
    seen: dict[tuple[tuple[float, float], ...], list[int]] = {}
    for index, points in enumerate(polygons):
        seen.setdefault(polygon_key(points), []).append(index)
    twins: dict[int, int] = {}
    for indexes in seen.values():
        if len(indexes) < 2:
            continue
        for index in indexes:
            twins[index] = next(other for other in indexes if other != index)
    return twins


def merged_apartments(kind: str, room_mark: str | None) -> list[str]:
    """Квартиры в марке слитой зоны (`6-5/1+6-6/6` -> `6-5`, `6-6`); одна квартира - пусто."""
    if kind != "room_apartment" or not room_mark or "+" not in room_mark:
        return []
    apartments = list(
        dict.fromkeys(part.split("/", 1)[0].strip() for part in room_mark.split("+") if "/" in part)
    )
    return apartments if len(apartments) > 1 else []


def zone_tolerance(kind: str, name: str | None) -> float:
    """Допуск расхождения с экспликацией по виду и названию зоны."""
    if kind == "room_mop":
        return ZONE_REVIEW_TOLERANCE_MOP
    if derive_room_type(kind, name) in ("bath", "wc"):
        return ZONE_REVIEW_TOLERANCE_BATH
    return ZONE_REVIEW_TOLERANCE_APARTMENT_ROOM


def zone_quality(
    *,
    kind: str,
    name: str | None,
    room_mark: str | None,
    area_m2: float | None,
    expl_area_m2: float | None,
    twin_mark: str | None = None,
    has_twin: bool = False,
) -> ZoneQuality:
    """Итог сверки авто-зоны помещения с экспликацией листа.

    `failed`: одинаковый контур у двух зон, зона слита из марок разных квартир, площадь больше
    1,5 или меньше 0,5 экспликации. `review`: расхождение выше допуска вида зоны либо площадь
    контура неизвестна. Экспликации нет - `ok` с пометкой.
    """
    if has_twin:
        other = f" ({twin_mark})" if twin_mark else ""
        return ZoneQuality("failed", f"одинаковый контур у двух зон{other}")
    apartments = merged_apartments(kind, room_mark)
    if apartments:
        return ZoneQuality("failed", f"зона слита из марок разных квартир: {', '.join(apartments)}")
    if expl_area_m2 is None or expl_area_m2 <= 0:
        return ZoneQuality("ok", NO_EXPLICATION)
    if area_m2 is None or area_m2 <= 0:
        return ZoneQuality(
            "review", "площадь контура не определена, сверка с экспликацией не выполнена"
        )
    ratio = area_m2 / expl_area_m2
    compared = (
        f"площадь {_num(area_m2, 2)} м² против {_num(expl_area_m2, 2)} м² по экспликации "
        f"({(ratio - 1) * 100:+.1f} %)".replace(".", ",")
    )
    if ratio > ZONE_FAILED_AREA_RATIO_MAX + _EPSILON:
        return ZoneQuality(
            "failed", f"{compared}: больше экспликации в {_num(ZONE_FAILED_AREA_RATIO_MAX)} раза"
        )
    if ratio < ZONE_FAILED_AREA_RATIO_MIN - _EPSILON:
        return ZoneQuality("failed", f"{compared}: меньше половины экспликации")
    tolerance = zone_tolerance(kind, name)
    if abs(ratio - 1) > tolerance + _EPSILON:
        return ZoneQuality("review", f"{compared}: допуск ±{_num(tolerance * 100, 0)} %")
    return ZoneQuality("ok", None)
