"""Все инженерные константы прототипа в одном месте.

Это параметры прототипа, а не установленные факты: они попадают в выход (`params`), чтобы любая
цифра модели читалась вместе с допущениями. Значения по умолчанию — из ТЗ этапа M1; подбор по
реальным данным не проводился.
"""

from pydantic import BaseModel, ConfigDict


class Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- стены ---
    min_wall_thickness_mm: float = 60.0
    min_wall_length_mm: float = 100.0
    thickness_tol_mm: float = 10.0
    angle_tol_deg: float = 1.0
    axis_tol_mm: float = 30.0
    join_gap_mm: float = 50.0
    opening_gap_slack_mm: float = 150.0
    dangling_tol_mm: float = 50.0
    # Только отчёт: насколько дальше допуска висит конец (зазор до грани ближайшей другой стены).
    dangling_report_reach_mm: float = 450.0
    dangling_excess_bands_mm: tuple[float, ...] = (100.0, 200.0, 400.0)

    # Ось по контуру для стен plangeom без осевых линий (прототип; не наблюдение, а вывод).
    outline_axis_corner_tol_deg: float = 5.0
    outline_axis_min_aspect: float = 1.5
    outline_axis_duplicate_share: float = 0.5

    # --- проёмы ---
    door_height_mm: float = 2100.0
    door_gap_warn_mm: float = 150.0
    window_sill_mm: float = 900.0
    window_head_mm: float = 2400.0
    host_tol_mm: float = 150.0
    host_ambiguity_mm: float = 20.0
    host_window_angle_deg: float = 10.0
    # Лист двери ориентирован вдоль стены в пределах этого угла (иначе стена не кандидат).
    door_wall_angle_deg: float = 20.0
    # Две записи leaves == 2 образуют пару, если раскрытия равны в пределах допуска, а расстояние
    # между петлями отличается от раскрытия не больше чем на double_door_hinge_tol_mm.
    pair_opening_tol_mm: float = 2.0
    double_door_hinge_tol_mm: float = 200.0

    # --- этажи, плиты, помещения ---
    level_height_mm: float = 3300.0
    # Высота этажа по соседней отметке комплекта принимается, только если правдоподобна.
    level_height_min_mm: float = 2000.0
    level_height_max_mm: float = 6000.0
    slab_thickness_mm: float = 200.0
    room_area_tol_pct: float = 10.0

    # --- система координат и ключи ---
    origin_angle_min_deg: float = 60.0
    origin_angle_max_deg: float = 120.0
    key_round_mm: float = 10.0

    # --- обзор комплекта (survey): границы классов толщины стен, мм ---
    survey_thickness_bands_mm: tuple[float, ...] = (100.0, 150.0, 250.0, 400.0)
