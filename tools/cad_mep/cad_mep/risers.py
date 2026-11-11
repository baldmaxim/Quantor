"""Реестр стояков листа из ИОС (cad_risers.v1): чтение и проверка входного файла `--risers`."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from cad_mep.errors import MepError

SCHEMA = "cad_risers.v1"
SYSTEMS = ("V1", "T3", "T4", "VPV", "AUP", "FS")
WATER_SYSTEMS = ("V1", "T3", "T4")
ROLES = ("own", "transit")
MAX_RISERS = 40
MARK_MAX = 32
DN_MIN, DN_MAX = 10, 400
COUNT_MIN, COUNT_MAX = 1, 8
TEXT_MAX = 200
SHAFT_ID_RE = re.compile(r"^S\d{2,3}$")

JsonObj = dict[str, object]


@dataclass(frozen=True)
class RiserEntry:
    system: str
    mark: str
    dn_mm: int | None
    role: str
    count: int
    shaft_id: str | None
    source: str | None
    note: str | None

    def to_json(self) -> JsonObj:
        return {
            "system": self.system,
            "mark": self.mark,
            "dn_mm": self.dn_mm,
            "role": self.role,
            "count": self.count,
            "shaft_id": self.shaft_id,
            "source": self.source,
            "note": self.note,
        }

    def label(self) -> str:
        """Подпись стояка в DXF: марка, диаметр и пометка транзита."""
        text = self.mark if self.dn_mm is None else f"{self.mark} Ø{self.dn_mm}"
        return f"{text} транзит" if self.role == "transit" else text


def registry_json(entries: list[RiserEntry]) -> JsonObj:
    return {"schema": SCHEMA, "risers": [e.to_json() for e in entries]}


def _fail(message: str) -> MepError:
    return MepError("risers_invalid", f"реестр стояков: {message}")


def _int_field(row: JsonObj, key: str, lo: int, hi: int, where: str, default: int | None) -> int:
    value = row.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise _fail(f"{where}: {key} — целое {lo}…{hi}")
    return value


def _text_field(row: JsonObj, key: str, where: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > TEXT_MAX:
        raise _fail(f"{where}: {key} — строка до {TEXT_MAX} символов или null")
    return value


def _entry(raw: object, index: int) -> RiserEntry:
    where = f"запись {index + 1}"
    if not isinstance(raw, dict):
        raise _fail(f"{where}: ожидался объект")
    row: JsonObj = {str(k): v for k, v in raw.items()}
    system = row.get("system")
    if not isinstance(system, str) or system not in SYSTEMS:
        raise _fail(f"{where}: system — одно из {', '.join(SYSTEMS)}")
    mark = row.get("mark")
    if not isinstance(mark, str) or not mark.strip() or len(mark) > MARK_MAX:
        raise _fail(f"{where}: mark — строка 1…{MARK_MAX} символов")
    dn = row.get("dn_mm")
    dn_mm = None if dn is None else _int_field(row, "dn_mm", DN_MIN, DN_MAX, where, None)
    role = row.get("role")
    if not isinstance(role, str) or role not in ROLES:
        raise _fail(f"{where}: role — own или transit")
    count = _int_field(row, "count", COUNT_MIN, COUNT_MAX, where, 1)
    shaft = row.get("shaft_id")
    if shaft is not None and (not isinstance(shaft, str) or not SHAFT_ID_RE.match(shaft)):
        raise _fail(f"{where}: shaft_id — вид S12 или null")
    return RiserEntry(
        system,
        mark,
        dn_mm,
        role,
        count,
        shaft,
        _text_field(row, "source", where),
        _text_field(row, "note", where),
    )


def parse_risers(data: object) -> list[RiserEntry]:
    if not isinstance(data, dict):
        raise _fail("ожидался объект JSON")
    if data.get("schema") != SCHEMA:
        raise _fail(f"schema должна быть {SCHEMA}")
    rows = data.get("risers")
    if not isinstance(rows, list):
        raise _fail("risers — список")
    if len(rows) > MAX_RISERS:
        raise _fail(f"записей {len(rows)}, не больше {MAX_RISERS}")
    return [_entry(raw, i) for i, raw in enumerate(rows)]


def load_risers(path: Path) -> list[RiserEntry]:
    """Записи реестра из файла; нечитаемый файл или неверный формат — ошибка генератора."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise MepError("risers_unreadable", f"нет файла реестра стояков {path.name}") from None
    except ValueError:
        raise _fail("файл не является JSON") from None
    return parse_risers(data)
