"""Профиль фасада (простенки и остекление) и створки дверей — без прогона всего конвейера."""

from __future__ import annotations

import math

import numpy as np
from ezdxf.filemanagement import new as new_dxf

from cad_mep import dxfin
from cad_mep.facade import _drop_narrow, _true_runs
from cad_mep.params import load_params


def test_true_runs() -> None:
    flags = np.array([1, 1, 0, 1, 0, 0, 1, 1, 1], dtype=np.bool_)
    assert _true_runs(flags) == [(0, 2), (3, 1), (6, 3)]
    assert _true_runs(np.zeros(4, dtype=np.bool_)) == []


def test_narrow_solids_are_mullions_not_piers() -> None:
    """Узкий сплошной участок — импост; контур замкнут, участок через начало массива — один."""
    solid = np.zeros(40, dtype=np.bool_)
    solid[10:13] = True  # 3 шага — импост
    solid[20:30] = True  # простенок
    solid[38:] = True  # простенок из 4 шагов: продолжается с начала массива
    solid[:2] = True
    out = _drop_narrow(solid, 4)
    assert not out[10:13].any()
    assert out[20:30].all()
    assert out[38:].all() and out[:2].all()
    assert int(out.sum()) == 14


def _arc(radius: float, points: int) -> list[tuple[float, float]]:
    step = math.pi / 2 / (points - 1)
    return [(radius * math.cos(k * step), radius * math.sin(k * step)) for k in range(points)]


def test_double_door_has_two_leaves() -> None:
    """Двустворчатая дверь: дуга малой створки короче (5 точек), замкнутые полилинии — не дуги."""
    doc = new_dxf("R2018")
    blk = doc.blocks.new("AR_DOOR_BLOCK_000")
    # большая створка: петля в (0, 0), полотно открыто вдоль +Y, закрытое — до (940, 0)
    blk.add_line((0, 0), (0, 940))
    blk.add_lwpolyline(_arc(940, 7))
    # малая створка: петля в (1350, 0), закрытое полотно — до (940, 0)
    blk.add_line((1350, 0), (1350, 410))
    blk.add_lwpolyline([(1350 - x, y) for x, y in _arc(410, 5)])
    blk.add_lwpolyline([(0, 0), (40, 0), (40, 940), (0, 940), (0, 0)], close=True)  # полотно
    doc.modelspace().add_blockref("AR_DOOR_BLOCK_000", (5000, 7000))
    doors = dxfin.load_doors(doc, load_params(None), (1000.0, 2000.0))
    assert len(doors) == 2
    spans = sorted((round(min(d.a[0], d.b[0])), round(max(d.a[0], d.b[0]))) for d in doors)
    assert spans == [(4000, 4940), (4940, 5350)]  # вместе — весь проём 1350 мм
    assert all(round(d.a[1]) == round(d.b[1]) == 5000 for d in doors)
