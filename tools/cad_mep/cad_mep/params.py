"""Параметры генератора (params/v1.json): значение, единица, источник и примечание каждой."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cad_mep.errors import MepError

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

SOURCES = ("observed", "derived", "assumed", "algorithm")
DEFAULT_PARAMS_PATH = Path(__file__).resolve().parent.parent / "params" / "v1.json"


@dataclass(frozen=True)
class Entry:
    value: JsonValue
    unit: str
    source: str
    note: str


class Params:
    """Типизированный доступ к параметрам; отсутствующий или неверный ключ — ошибка входа."""

    def __init__(self, entries: dict[str, Entry], sha256: str) -> None:
        self._e = entries
        self.sha256 = sha256

    # --- доступ
    def _v(self, name: str) -> JsonValue:
        try:
            return self._e[name].value
        except KeyError:
            raise MepError("params_invalid", f"нет параметра {name}") from None

    def num(self, name: str) -> float:
        v = self._v(name)
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise MepError("params_invalid", f"параметр {name}: ожидалось число")
        return float(v)

    def count(self, name: str) -> int:
        return round(self.num(name))

    def text(self, name: str) -> str:
        v = self._v(name)
        if not isinstance(v, str):
            raise MepError("params_invalid", f"параметр {name}: ожидалась строка")
        return v

    def texts(self, name: str) -> tuple[str, ...]:
        v = self._v(name)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise MepError("params_invalid", f"параметр {name}: ожидался список строк")
        return tuple(str(x) for x in v)

    def nums(self, name: str) -> tuple[float, ...]:
        v = self._v(name)
        if not isinstance(v, list) or not all(
            isinstance(x, int | float) and not isinstance(x, bool) for x in v
        ):
            raise MepError("params_invalid", f"параметр {name}: ожидался список чисел")
        return tuple(float(x) for x in v if isinstance(x, int | float))

    def num_map(self, name: str) -> dict[str, float]:
        v = self._v(name)
        if not isinstance(v, dict):
            raise MepError("params_invalid", f"параметр {name}: ожидался словарь")
        out: dict[str, float] = {}
        for k, x in v.items():
            if isinstance(x, bool) or not isinstance(x, int | float):
                raise MepError("params_invalid", f"параметр {name}.{k}: ожидалось число")
            out[k] = float(x)
        return out

    def colors(self, name: str) -> tuple[tuple[float, float, float], ...]:
        v = self._v(name)
        out: list[tuple[float, float, float]] = []
        if not isinstance(v, list):
            raise MepError("params_invalid", f"параметр {name}: ожидался список цветов")
        for c in v:
            if (
                not isinstance(c, list)
                or len(c) != 3
                or not all(isinstance(x, int | float) and not isinstance(x, bool) for x in c)
            ):
                raise MepError("params_invalid", f"параметр {name}: цвет — три числа")
            r, g, b = (float(x) for x in c if isinstance(x, int | float))
            out.append((r, g, b))
        return tuple(out)

    # --- выгрузка
    def dump(self) -> dict[str, dict[str, JsonValue]]:
        return {
            k: {"value": e.value, "unit": e.unit, "source": e.source, "note": e.note}
            for k, e in self._e.items()
        }

    def assumed(self) -> list[dict[str, JsonValue]]:
        """Допущения оператора/алгоритма, которые нельзя считать наблюдаемыми."""
        return [
            {"name": k, "value": e.value, "unit": e.unit, "note": e.note}
            for k, e in self._e.items()
            if e.source == "assumed"
        ]


def canonical_sha256(raw: object) -> str:
    text = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse(raw: object) -> dict[str, Entry]:
    if not isinstance(raw, dict):
        raise MepError("params_invalid", "файл параметров: ожидался объект")
    out: dict[str, Entry] = {}
    for name, item in raw.items():
        if not isinstance(item, dict) or not {"value", "unit", "source", "note"} <= set(item):
            raise MepError("params_invalid", f"параметр {name}: нужны value, unit, source, note")
        source, unit, note = item["source"], item["unit"], item["note"]
        if source not in SOURCES or not isinstance(unit, str) or not isinstance(note, str):
            raise MepError("params_invalid", f"параметр {name}: неверные source/unit/note")
        out[str(name)] = Entry(item["value"], unit, str(source), note)
    return out


def load_params(path: Path | None = None) -> Params:
    """Читает файл параметров; набор ключей должен совпадать с эталонным params/v1.json."""
    target = path or DEFAULT_PARAMS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MepError("params_invalid", f"не читается файл параметров: {exc}") from exc
    entries = _parse(raw)
    if target.resolve() != DEFAULT_PARAMS_PATH.resolve():
        try:
            ref = _parse(json.loads(DEFAULT_PARAMS_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise MepError("params_invalid", f"не читается эталон параметров: {exc}") from exc
        missing = sorted(set(ref) - set(entries))
        if missing:
            raise MepError("params_invalid", f"в параметрах нет ключей: {', '.join(missing)}")
    return Params(entries, canonical_sha256(raw))
