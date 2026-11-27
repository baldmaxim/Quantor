"""Высоты окон плана по видам фасадов (ADR-0048 п. 3-5): чистые функции без базы.

Ожидаемые числа выписаны руками. План: плита 6000 x 4000 мм, чистый пол листа 47600, этаж 3000.
Вид «с юга»: оси 1 и 2 на долях 0.1 и 0.9 страницы фасада = 0 и 6000 мм плана, то есть
`c = 7500 * x - 750`.
"""

from __future__ import annotations

import uuid

from app.contracts.cad_constructions import WallsOpening
from app.contracts.cad_facades import FacadeAxis, FacadeWindow
from app.contracts.cad_floor3d import WallsOpeningExtras
from app.services import cad_facade_windows as fw

Z = 47600
LEVEL = fw.SheetLevel(floor_z_mm=Z, floor_height_mm=3000, elevation_known=True)
SLAB = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]
VERTICAL = {"1": 0.0, "2": 6000.0}
REVISION = uuid.uuid4()


def fx(mm: float) -> float:
    """Доля страницы южного вида для координаты x плана (оси 1 и 2 на 0.1 и 0.9)."""
    return (mm + 750.0) / 7500.0


def axis(label: str, x: float, full: str | None = None, u: int | None = None) -> FacadeAxis:
    return FacadeAxis(label=label, label_full=full, x=x, y=0.95, u_mm=u)


def fwindow(x0: float, x1: float, z_bottom: int, z_top: int) -> FacadeWindow:
    return FacadeWindow(
        bbox=(x0, 0.3, x1, 0.4),
        width_mm=1000,
        z_bottom_mm=z_bottom,
        z_top_mm=z_top,
        height_mm=z_top - z_bottom,
        source="observed",
    )


def view(
    windows: list[FacadeWindow],
    *,
    axes: list[FacadeAxis] | None = None,
    accepted: bool = True,
    scale: str = "fitted",
    corps: str | None = None,
    section: str | None = None,
    key: str = "p1v1",
) -> fw.FacadeViewInput:
    return fw.FacadeViewInput(
        id=uuid.uuid4(),
        revision_id=REVISION,
        view_key=key,
        page_index=3,
        title="Фасад в осях 1-2",
        corps=corps,
        section=section,
        accepted=accepted,
        scale_status=scale,
        axes=tuple(axes if axes is not None else [axis("1", 0.1), axis("2", 0.9)]),
        windows=tuple(windows),
    )


def plan_window(
    key: str,
    x0: float,
    x1: float,
    y0: float = 0.0,
    y1: float = 200.0,
    *,
    direction: tuple[float, float] = (1.0, 0.0),
) -> tuple[WallsOpening, WallsOpeningExtras]:
    opening = WallsOpening.model_validate(
        {
            "id": key,
            "kind": "window",
            "status": "no_data",
            "host_id": "c1",
            "adjacent_ids": [],
            "width_mm": max(x1 - x0, y1 - y0),
            "width_source": "window_bay",
            "thickness_mm": 200.0,
            "block_name": None,
            "handle": None,
            "center": [(x0 + x1) / 2, (y0 + y1) / 2],
            "opening_height_mm": None,
        }
    )
    extra = WallsOpeningExtras(
        id=key,
        direction=list(direction),
        lintel=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
    )
    return opening, extra


def run(
    windows: list[tuple[WallsOpening, WallsOpeningExtras]],
    views: list[fw.FacadeViewInput],
    *,
    slab_rings: list[list[list[float]]] | None = None,
    vertical: dict[str, float] | None = None,
    horizontal: dict[str, float] | None = None,
    level: fw.SheetLevel = LEVEL,
    corps: str | None = None,
    section: str | None = None,
    invalid_views: int = 0,
) -> fw.FacadeMatch:
    return fw.match_sheet_windows(
        openings=[o for o, _ in windows],
        extras=[e for _, e in windows],
        slab_rings=[SLAB] if slab_rings is None else slab_rings,
        vertical_axes=VERTICAL if vertical is None else vertical,
        horizontal_axes={} if horizontal is None else horizontal,
        corps=corps,
        section=section,
        level=level,
        views=views,
        invalid_views=invalid_views,
    )


SOUTH_WINDOW = plan_window("w1", 3000.0, 4000.0)
# окно фасада напротив SOUTH_WINDOW: подоконник 900, верх 2400 от чистого пола
FACADE_OK = fwindow(fx(3000.0), fx(4000.0), Z + 900, Z + 2400)


# ------------------------------------------------------------------ ориентация, плита, этаж


def test_south_view_by_positive_scale_assigns_sill_and_head() -> None:
    result = run([SOUTH_WINDOW], [view([FACADE_OK])])
    height = result.heights["w1"]
    assert (height.sill_mm, height.head_mm) == (900, 2400)
    assert height.accepted and not height.axes_checked
    assert (height.view_key, height.page_index, height.revision_id) == ("p1v1", 3, REVISION)
    assert height.overlap == 1.0
    assert result.issues == ()


def test_label_full_is_used_when_label_does_not_match() -> None:
    axes = [axis("x", 0.1, full="1"), axis("y", 0.9, full="2")]
    assert "w1" in run([SOUTH_WINDOW], [view([FACADE_OK], axes=axes)]).heights


def test_north_view_by_negative_scale_takes_the_north_window_only() -> None:
    north = plan_window("n1", 3000.0, 4000.0, 3800.0, 4000.0)
    axes = [axis("1", 0.9), axis("2", 0.1)]  # a = -7500, c = -7500 x + 6750
    window = fwindow((6750.0 - 4000.0) / 7500.0, (6750.0 - 3000.0) / 7500.0, Z + 900, Z + 2400)
    result = run([SOUTH_WINDOW, north], [view([window], axes=axes)])
    assert set(result.heights) == {"n1"}


def test_horizontal_axes_east_and_west_by_sign() -> None:
    east = plan_window("e1", 5800.0, 6000.0, 1000.0, 2000.0, direction=(0.0, 1.0))
    west = plan_window("v1", 0.0, 200.0, 1000.0, 2000.0, direction=(0.0, 1.0))
    horizontal = {"A": 0.0, "B": 4000.0}
    # a = 5000, c(y) = 5000 x - 500: y 1000..2000 -> x 0.3..0.5
    east_view = view([fwindow(0.3, 0.5, Z + 900, Z + 2400)], axes=[axis("A", 0.1), axis("B", 0.9)])
    result = run([east, west], [east_view], vertical={}, horizontal=horizontal)
    assert set(result.heights) == {"e1"}
    # a < 0: наблюдатель с запада; c(y) = -5000 x + 4500 -> y 1000..2000 -> x 0.5..0.7
    west_view = view([fwindow(0.5, 0.7, Z + 900, Z + 2400)], axes=[axis("A", 0.9), axis("B", 0.1)])
    result = run([east, west], [west_view], vertical={}, horizontal=horizontal)
    assert set(result.heights) == {"v1"}


def test_floor_is_chosen_by_z_with_a_margin() -> None:
    upper = fwindow(fx(3000.0), fx(4000.0), Z + 3500, Z + 5000)
    assert run([SOUTH_WINDOW], [view([upper])]).heights == {}
    # низ окна на 300 мм ниже чистого пола - всё ещё этаж; sill не меньше 0
    low = fwindow(fx(3000.0), fx(4000.0), Z - 200, Z + 1500)
    height = run([SOUTH_WINDOW], [view([low])]).heights["w1"]
    assert (height.sill_mm, height.head_mm) == (0, 1500)
    # верхняя граница: z_bottom < z_f + h - 300
    edge = fwindow(fx(3000.0), fx(4000.0), Z + 2700, Z + 2900)
    assert run([SOUTH_WINDOW], [view([edge])]).heights == {}


def test_outward_side_is_defined_by_the_slab_not_by_the_normal_sign() -> None:
    # Окно на северной стене, контур плиты тот же: наружу - север; южный вид его не берёт.
    north = plan_window("n1", 3000.0, 4000.0, 3800.0, 4000.0)
    assert run([north], [view([FACADE_OK])]).heights == {}


def test_window_inside_the_slab_is_not_on_the_outer_wall() -> None:
    inner = plan_window("i1", 3000.0, 4000.0, 1900.0, 2100.0)
    result = run([inner], [view([FACADE_OK])])
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_NOT_OUTER]


# ------------------------------------------------------------------ перекрытие, приоритет


def test_overlap_below_half_is_not_matched() -> None:
    far = fwindow(fx(3700.0), fx(4700.0), Z + 900, Z + 2400)  # перекрытие 300 из 1000
    result = run([SOUTH_WINDOW], [view([far])])
    assert result.heights == {} and result.issues == ()


def test_two_facade_windows_over_half_make_it_ambiguous() -> None:
    first = fwindow(fx(3000.0), fx(3800.0), Z + 900, Z + 2400)
    second = fwindow(fx(3200.0), fx(4000.0), Z + 900, Z + 2400)
    result = run([SOUTH_WINDOW], [view([first, second])])
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_AMBIGUOUS]


def test_only_the_outermost_plan_window_is_assigned_to_a_facade_window() -> None:
    # Ниша 3300..3700 x 0..400 вне плиты; наружное остекление в нише, окно глубже.
    slab = [
        [0.0, 0.0],
        [3300.0, 0.0],
        [3300.0, 400.0],
        [3700.0, 400.0],
        [3700.0, 0.0],
        [6000.0, 0.0],
        [6000.0, 4000.0],
        [0.0, 4000.0],
    ]
    outer = plan_window("out", 3300.0, 3700.0, 0.0, 200.0)
    inner = plan_window("inn", 3300.0, 3700.0, 400.0, 600.0)
    window = fwindow(fx(3300.0), fx(3700.0), Z + 900, Z + 2400)
    result = run([inner, outer], [view([window])], slab_rings=[slab])
    assert set(result.heights) == {"out"}
    assert [i.code for i in result.issues] == [fw.CODE_HIDDEN]


def test_accepted_view_beats_a_candidate_and_fitted_beats_weak() -> None:
    accepted = view([fwindow(fx(3000.0), fx(4000.0), Z + 900, Z + 2400)], key="acc")
    candidate = view(
        [fwindow(fx(3000.0), fx(4000.0), Z + 1000, Z + 2200)], accepted=False, key="cand"
    )
    height = run([SOUTH_WINDOW], [candidate, accepted]).heights["w1"]
    assert (height.accepted, height.view_key, height.sill_mm) == (True, "acc", 900)
    weak = view([fwindow(fx(3000.0), fx(4000.0), Z + 1000, Z + 2200)], scale="weak", key="weak")
    fitted = view([fwindow(fx(3000.0), fx(4000.0), Z + 900, Z + 2400)], key="fit")
    assert run([SOUTH_WINDOW], [weak, fitted]).heights["w1"].view_key == "fit"


def test_candidate_view_gives_a_candidate_height() -> None:
    height = run([SOUTH_WINDOW], [view([FACADE_OK], accepted=False)]).heights["w1"]
    assert height.accepted is False


def test_equal_priority_views_disagreeing_by_more_than_50_mm_assign_nothing() -> None:
    first = view([fwindow(fx(3000.0), fx(4000.0), Z + 900, Z + 2400)], key="a")
    second = view([fwindow(fx(3000.0), fx(4000.0), Z + 960, Z + 2400)], key="b")
    result = run([SOUTH_WINDOW], [first, second])
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_CONFLICT]
    near = view([fwindow(fx(3000.0), fx(4000.0), Z + 940, Z + 2400)], key="c")
    assert "w1" in run([SOUTH_WINDOW], [first, near]).heights


def test_window_with_top_not_above_bottom_is_not_assigned() -> None:
    broken = fwindow(fx(3000.0), fx(4000.0), Z - 200, Z - 100)
    # низ ниже пола обрезается до 0, верх -100 не выше низа
    result = run([SOUTH_WINDOW], [view([broken])])
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_INVALID]


# ------------------------------------------------------------------ корпус, секция, оси


def test_different_corps_or_section_skips_the_view() -> None:
    assert run([SOUTH_WINDOW], [view([FACADE_OK], corps="1")], corps="2").heights == {}
    assert run([SOUTH_WINDOW], [view([FACADE_OK], section="А")], section="Б").heights == {}
    # у одной из сторон не задано - вид не отбрасывается
    assert "w1" in run([SOUTH_WINDOW], [view([FACADE_OK], corps="1")]).heights
    assert (
        "w1" in run([SOUTH_WINDOW], [view([FACADE_OK], corps="1", section="А")], corps="1").heights
    )


def test_fewer_than_two_common_axes_gives_a_remark() -> None:
    one_axis = view([FACADE_OK], axes=[axis("1", 0.1), axis("Z", 0.9)])
    result = run([SOUTH_WINDOW], [one_axis])
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_NOT_LINKED]


def test_tie_between_orientations_is_a_remark() -> None:
    result = run(
        [SOUTH_WINDOW],
        [view([FACADE_OK])],
        vertical=VERTICAL,
        horizontal={"1": 0.0, "2": 4000.0},
    )
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_ORIENTATION]


def test_three_axes_within_150_mm_are_checked() -> None:
    axes = [axis("1", 0.1), axis("3", 0.5), axis("2", 0.9)]
    vertical = {"1": 0.0, "2": 6000.0, "3": 3100.0}  # ось 3: 3000 по виду, 3100 на плане
    result = run([SOUTH_WINDOW], [view([FACADE_OK], axes=axes)], vertical=vertical)
    assert result.heights["w1"].axes_checked is True


def test_axes_deviating_more_than_150_mm_unlink_the_view() -> None:
    axes = [axis("1", 0.1), axis("3", 0.5), axis("2", 0.9)]
    vertical = {"1": 0.0, "2": 6000.0, "3": 3400.0}
    result = run([SOUTH_WINDOW], [view([FACADE_OK], axes=axes)], vertical=vertical)
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_AXES_MISMATCH]


# ------------------------------------------------------------------ предпосылки листа


def test_no_elevation_or_floor_height_means_no_matching_and_a_remark() -> None:
    for level in (
        fw.SheetLevel(floor_z_mm=Z, floor_height_mm=3000, elevation_known=False),
        fw.SheetLevel(floor_z_mm=Z, floor_height_mm=None, elevation_known=True),
    ):
        result = run([SOUTH_WINDOW], [view([FACADE_OK])], level=level)
        assert result.heights == {}
        assert [i.code for i in result.issues] == [fw.CODE_NO_LEVEL]


def test_no_slab_means_no_matching_and_a_remark() -> None:
    result = fw.match_sheet_windows(
        openings=[SOUTH_WINDOW[0]],
        extras=[SOUTH_WINDOW[1]],
        slab_rings=None,
        vertical_axes=VERTICAL,
        horizontal_axes={},
        corps=None,
        section=None,
        level=LEVEL,
        views=[view([FACADE_OK])],
    )
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_NO_SLAB]


def test_slab_without_valid_rings_means_no_matching_and_a_remark() -> None:
    for rings in ([], [[[0.0, 0.0], [1.0, 1.0]]]):
        result = run([SOUTH_WINDOW], [view([FACADE_OK])], slab_rings=rings)
        assert result.heights == {}
        assert [i.code for i in result.issues] == [fw.CODE_NO_SLAB]


# Вторая часть плиты (лист из двух корпусов): правее первой, с зазором 1000 мм.
SECOND_PART = [[7000.0, 0.0], [13000.0, 0.0], [13000.0, 4000.0], [7000.0, 4000.0]]


def test_window_on_the_second_slab_part_is_matched_only_with_all_parts() -> None:
    window = plan_window("w2", 9000.0, 10000.0)
    facade = fwindow(fx(9000.0), fx(10000.0), Z + 900, Z + 2400)
    only_first = run([window], [view([facade])], slab_rings=[SLAB])
    assert only_first.heights == {}
    assert [i.code for i in only_first.issues] == [fw.CODE_NOT_OUTER]
    both = run([window], [view([facade])], slab_rings=[SLAB, SECOND_PART])
    assert (both.heights["w2"].sill_mm, both.heights["w2"].head_mm) == (900, 2400)
    assert both.issues == ()
    # Окно первой части по-прежнему сопоставляется при двух частях.
    assert "w1" in run([SOUTH_WINDOW], [view([FACADE_OK])], slab_rings=[SECOND_PART, SLAB]).heights


def test_outward_side_takes_the_nearest_slab_part_across_a_narrow_gap() -> None:
    # Зазор между частями 300 мм < пробы 600 мм: по объединению обе пробы внутри плиты.
    near = [[6300.0, 0.0], [12000.0, 0.0], [12000.0, 4000.0], [6300.0, 4000.0]]
    east = plan_window("e1", 5800.0, 6000.0, 1000.0, 2000.0, direction=(0.0, 1.0))
    planned = fw._plan_window(east[0], east[1], [SLAB, near])
    assert planned is not None and planned.outward == (1.0, 0.0)
    # Окно на стене второй части, обращённой к первой, смотрит на запад.
    west = plan_window("v1", 6300.0, 6500.0, 1000.0, 2000.0, direction=(0.0, 1.0))
    planned_west = fw._plan_window(west[0], west[1], [SLAB, near])
    assert planned_west is not None and planned_west.outward == (-1.0, 0.0)


def test_window_with_own_height_or_no_views_gives_an_empty_result() -> None:
    own = SOUTH_WINDOW[0].model_copy(update={"opening_height_mm": 1500})
    assert run([(own, SOUTH_WINDOW[1])], [view([FACADE_OK])]) == fw.FacadeMatch()
    assert run([SOUTH_WINDOW], []) == fw.FacadeMatch()


def test_grouped_warnings_keep_one_message_per_code_with_a_count() -> None:
    issues = [
        fw.MatchIssue(fw.CODE_AMBIGUOUS, "а"),
        fw.MatchIssue(fw.CODE_AMBIGUOUS, "а"),
        fw.MatchIssue(fw.CODE_HIDDEN, "б"),
    ]
    assert fw.grouped_warnings(issues) == [
        (fw.CODE_AMBIGUOUS, "а Случаев: 2."),
        (fw.CODE_HIDDEN, "б"),
    ]


def test_point_in_ring_even_odd() -> None:
    ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    assert fw.point_in_ring(5.0, 5.0, ring)
    assert not fw.point_in_ring(15.0, 5.0, ring)
    assert not fw.point_in_ring(5.0, -1.0, ring)


# ------------------------------------------------------------------ закрытие, глубина, сверка u_mm

NOOK_SLAB = [
    [0.0, 0.0],
    [3300.0, 0.0],
    [3300.0, 400.0],
    [3700.0, 400.0],
    [3700.0, 0.0],
    [6000.0, 0.0],
    [6000.0, 4000.0],
    [0.0, 4000.0],
]


def test_loggia_glazing_with_its_own_height_hides_the_wall_window_behind_it() -> None:
    glazing, glazing_extra = plan_window("gl", 3300.0, 3700.0, 0.0, 200.0)
    glazing = glazing.model_copy(update={"opening_height_mm": 2700})
    inner = plan_window("inn", 3300.0, 3700.0, 400.0, 600.0)
    window = fwindow(fx(3300.0), fx(3700.0), Z + 900, Z + 2400)
    result = run([(glazing, glazing_extra), inner], [view([window])], slab_rings=[NOOK_SLAB])
    # высоту остекления окно стены не получает; остекление свою высоту не меняет
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_HIDDEN]


def test_windows_at_the_same_depth_under_one_facade_window_both_get_the_height() -> None:
    first = plan_window("a", 3000.0, 3600.0)
    second = plan_window("b", 3400.0, 4000.0, 250.0, 450.0)  # глубже на 250 мм - в допуске
    result = run([first, second], [view([FACADE_OK])])
    assert set(result.heights) == {"a", "b"}
    assert result.issues == ()


def test_axes_with_matching_u_mm_are_checked_even_with_two_axes() -> None:
    axes = [axis("1", 0.1, u=0), axis("2", 0.9, u=6050)]
    height = run([SOUTH_WINDOW], [view([FACADE_OK], axes=axes)]).heights["w1"]
    assert height.axes_checked is True


def test_u_mm_disagreeing_with_plan_axes_unlinks_the_view() -> None:
    axes = [axis("1", 0.1, u=0), axis("2", 0.9, u=5000)]  # 5000 против 6000, допуск 180
    result = run([SOUTH_WINDOW], [view([FACADE_OK], axes=axes)])
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_UNITS_MISMATCH]


def test_u_mm_is_only_a_check_and_never_an_input() -> None:
    # Верные u_mm не меняют перевод: положение окна считается по осям плана и долям страницы.
    axes = [axis("1", 0.1, u=0), axis("2", 0.9, u=6000)]
    shifted = fwindow(fx(3000.0), fx(4000.0), Z + 900, Z + 2400)
    result = run([SOUTH_WINDOW], [view([shifted], axes=axes)])
    assert result.heights["w1"].overlap == 1.0


def test_corps_and_section_are_compared_like_group_of() -> None:
    assert "w1" in run([SOUTH_WINDOW], [view([FACADE_OK], corps="К  1")], corps="к 1").heights
    assert run([SOUTH_WINDOW], [view([FACADE_OK], section="A")], section="  a ").heights


def test_views_of_another_building_give_one_remark() -> None:
    other = [view([FACADE_OK], corps="1", key="a"), view([FACADE_OK], corps="1", key="b")]
    result = run([SOUTH_WINDOW], other, corps="2")
    assert result.heights == {}
    assert [i.code for i in result.issues] == [fw.CODE_OTHER_BUILDING]


def test_invalid_views_are_reported_not_silent() -> None:
    result = run([SOUTH_WINDOW], [view([FACADE_OK])], invalid_views=2)
    assert "w1" in result.heights
    assert [(i.code, "2" in i.message) for i in result.issues] == [(fw.CODE_VIEW_INVALID, True)]
    only_invalid = run([SOUTH_WINDOW], [], invalid_views=1)
    assert [i.code for i in only_invalid.issues] == [fw.CODE_VIEW_INVALID]
