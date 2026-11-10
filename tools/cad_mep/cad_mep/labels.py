"""Текст листа: марки помещений, подписи шахт, экспликация, отметки, номера квартир."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cad_mep.frame import Frame
from cad_mep.params import Params
from cad_mep.pdfsrc import WordPt


@dataclass(frozen=True)
class Word:
    text: str
    x0: float  # локальные мм
    y0: float
    x1: float
    y1: float
    pt: tuple[float, float, float, float]

    @property
    def c(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


def to_word(w: WordPt, frame: Frame) -> Word:
    ax, ay = frame.pt_to_local(w.x0, w.y1)
    bx, by = frame.pt_to_local(w.x1, w.y0)
    return Word(w.text, ax, ay, bx, by, (w.x0, w.y0, w.x1, w.y1))


@dataclass(frozen=True)
class ShaftLabel:
    word: Word
    systems: list[str]


@dataclass(frozen=True)
class RoomLabel:
    word: Word
    room_id: str
    section: str
    apt_index: int | None  # номер квартиры в секции; None для МОП
    mop: bool


@dataclass(frozen=True)
class ExplRow:
    room_id: str
    name: str
    area_m2: float


@dataclass
class Labels:
    shafts: list[ShaftLabel] = field(default_factory=list)
    rooms: list[RoomLabel] = field(default_factory=list)
    expl: dict[str, ExplRow] = field(default_factory=dict)
    pk: list[Word] = field(default_factory=list)
    apt_numbers: list[str] = field(default_factory=list)
    elevation_marks_mm: list[int] = field(default_factory=list)


def split_shaft_text(text: str, codes: tuple[str, ...]) -> list[str] | None:
    """«ОВВК» -> [ОВ, ВК]; «ЭО/СС» -> [ЭО, СС]; не шифр — None. Длинные коды — раньше коротких."""
    out: list[str] = []
    for part in (p for p in text.split("/") if p):
        rest = part
        while rest:
            for c in codes:
                if rest.startswith(c):
                    out.append(c)
                    rest = rest[len(c) :]
                    break
            else:
                return None
    return out or None


def parse_plan(words: list[Word], params: Params) -> Labels:
    room_re = re.compile(params.text("room_id_regex"))
    codes = tuple(sorted(params.texts("shaft_codes"), key=lambda c: (-len(c), c)))
    labels = Labels()
    for w in words:
        m = room_re.match(w.text)
        if m:
            mop = m.group(3) == "."
            labels.rooms.append(
                RoomLabel(w, w.text, m.group(1), None if mop else int(m.group(2)), mop)
            )
            continue
        systems = split_shaft_text(w.text, codes)
        if systems:
            labels.shafts.append(ShaftLabel(w, systems))
            if "ПК" in systems:
                labels.pk.append(w)
    return labels


def parse_explication(words: list[Word], params: Params) -> dict[str, ExplRow]:
    """Строки экспликации: «1-1/1 Спальня 18,54»; название и площадь — правее номера в строке."""
    room_re = re.compile(params.text("room_id_regex"))
    area_re = re.compile(params.text("area_regex"))
    y_tol = params.num("expl_row_y_tol_pt")
    max_dx = params.num("expl_row_max_dx_pt")
    rows: dict[str, ExplRow] = {}
    for idw in words:
        if not room_re.match(idw.text):
            continue
        yc = (idw.pt[1] + idw.pt[3]) / 2
        line = [
            w
            for w in words
            if w is not idw
            and abs((w.pt[1] + w.pt[3]) / 2 - yc) < y_tol
            and idw.pt[0] < w.pt[0] < idw.pt[0] + max_dx
            and not room_re.match(w.text)
        ]
        line.sort(key=lambda w: w.pt[0])
        if len(line) < 2 or not area_re.match(line[-1].text):
            continue
        rows[idw.text] = ExplRow(
            idw.text, " ".join(w.text for w in line[:-1]), float(line[-1].text.replace(",", "."))
        )
    return rows


def parse_elevations(words: list[WordPt], params: Params) -> list[int]:
    """Отметки вида «+47,600» на листе, мм (без повторов, по возрастанию)."""
    mark_re = re.compile(params.text("elevation_mark_regex"))
    found: set[int] = set()
    for w in words:
        if mark_re.match(w.text):
            found.add(round(float(w.text.replace(",", ".")) * 1000))
    return sorted(found)


def parse_apt_numbers(words: list[WordPt], params: Params) -> list[str]:
    """Номера квартир из подписей «Кв 3141» (метка и число — рядом на одной строке)."""
    tag_re = re.compile(params.text("apartment_tag_regex"))
    num_re = re.compile(params.text("apartment_number_regex"))
    max_gap = params.num("apartment_tag_gap_pt")
    line_tol = params.num("expl_row_y_tol_pt")
    out: set[str] = set()
    for tag in words:
        if not tag_re.match(tag.text):
            continue
        for w in words:
            same_line = abs((w.y0 + w.y1) / 2 - (tag.y0 + tag.y1) / 2) < line_tol
            if same_line and 0 <= w.x0 - tag.x1 < max_gap and num_re.match(w.text):
                out.add(w.text)
    return sorted(out)
