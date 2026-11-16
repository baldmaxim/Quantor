"""Самопроверка каталога пакета QMP v1 по разделу 9 спецификации.

Только стандартная библиотека: модуль можно скопировать и запускать отдельно
(`python qmp_check.py КАТАЛОГ`). Ошибка - пакет портал отклонит, предупреждение - сохранит.
Выгрузчик берёт отсюда канонический JSON и хеш манифеста, чтобы правила совпадали.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

SCHEMA = "quantor.model_package.v1"
MAX_PARTS = 2_000
MAX_ELEMENTS = 500_000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_PATH = 160
MAX_PROPS = 24
MAX_PROP_STR = 120
STOREY_HEIGHT_MM = (1_500.0, 12_000.0)
STOREY_EXTENT_MM = (5_000.0, 2_000_000.0)
HASH_EXCLUDED = ("manifest_sha256", "generated_at")

CATEGORIES = frozenset(
    {
        "wall",
        "slab",
        "column",
        "beam",
        "door",
        "window",
        "curtain_wall",
        "plate",
        "member",
        "railing",
        "stair",
        "covering",
        "roof",
        "furniture",
        "equipment",
        "pipe",
        "duct",
        "cable_carrier",
        "other",
    }
)
SOURCE_KINDS = frozenset({"ifc", "navisworks", "revit", "other"})
PART_KINDS = frozenset({"storeys", "grids", "elements", "geometry", "footprint"})
ELEVATION_SOURCES = frozenset({"ifc_storey_elevation", "slab_top", "level", "manual"})
FOOTPRINT_GROUPS = frozenset({"walls", "columns", "curtain"})
GLB_EXTENSIONS = frozenset({"KHR_materials_unlit", "KHR_mesh_quantization"})
GLB_FORBIDDEN = ("images", "textures", "samplers", "animations", "cameras", "skins")

PATH_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ELEMENT_ID_RE = re.compile(r"^[A-Za-z0-9_$.:-]{1,64}$")
DISCIPLINE_RE = re.compile(r"^[A-Z0-9]{1,16}$")
PART_PATH_RE: dict[str, re.Pattern[str]] = {
    "storeys": re.compile(r"^storeys\.json$"),
    "grids": re.compile(r"^grids\.json$"),
    "elements": re.compile(r"^elements/([A-Za-z0-9_-]{1,64})\.jsonl$"),
    "geometry": re.compile(
        r"^geometry/([A-Za-z0-9_-]{1,64})__([A-Z0-9]{1,16})(?:\.[0-9]{1,3})?\.glb$"
    ),
    "footprint": re.compile(r"^footprints/([A-Za-z0-9_-]{1,64})\.json$"),
}
NEEDS_STOREY = frozenset({"elements", "geometry", "footprint"})

# Поля объектов: (обязательные, необязательные). Лишние поля - предупреждение (см. README).
FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "manifest": (
        frozenset(
            {
                "schema",
                "generated_at",
                "generator",
                "source",
                "units",
                "frame",
                "disciplines",
                "parts",
                "counts",
                "manifest_sha256",
            }
        ),
        frozenset(),
    ),
    "source": (frozenset({"kind", "files"}), frozenset({"authoring", "ifc_schema"})),
    "source_file": (frozenset({"name", "bytes", "sha256"}), frozenset({"discipline"})),
    "frame": (frozenset({"axes", "origin_offset_mm"}), frozenset()),
    "discipline": (frozenset({"code", "name", "elements"}), frozenset()),
    "part": (
        frozenset({"path", "kind", "bytes", "sha256"}),
        frozenset({"storey_key", "discipline"}),
    ),
    "counts": (frozenset({"storeys", "elements", "triangles", "parts"}), frozenset()),
    "storey": (
        frozenset(
            {
                "storey_key",
                "name",
                "elevation_mm",
                "height_mm",
                "elevation_source",
                "bbox_mm",
            }
        ),
        frozenset(),
    ),
    "grids": (frozenset({"source", "axes"}), frozenset()),
    "axis": (frozenset({"tag", "dir", "p0", "p1"}), frozenset()),
    "element": (
        frozenset({"id", "category", "discipline", "storey_key", "part", "props"}),
        frozenset({"ifc_class", "name", "type", "bbox_mm"}),
    ),
    "footprint": (frozenset({"storey_key", "z_cut_mm", "polygons"}), frozenset()),
}


@dataclass(frozen=True, slots=True)
class Issue:
    level: str
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        label = "ОШИБКА" if self.level == "error" else "ПРЕДУПРЕЖДЕНИЕ"
        return f"{label} [{self.code}] {self.where}: {self.message}"


@dataclass(slots=True)
class Report:
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def error(self, code: str, where: str, message: str) -> None:
        self.issues.append(Issue("error", code, where, message))

    def warning(self, code: str, where: str, message: str) -> None:
        self.issues.append(Issue("warning", code, where, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class GlbInfo:
    nodes: list[str]
    triangles: int
    materials: list[str]


def canonical_json(value: Any) -> bytes:
    """Канонический JSON раздела 2: ключи по алфавиту, `,` и `:` без пробелов, UTF-8."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def manifest_digest(manifest: dict[str, Any]) -> str:
    """sha256 манифеста без `manifest_sha256` и `generated_at` (раздел 2)."""
    body = {k: v for k, v in manifest.items() if k not in HASH_EXCLUDED}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def file_digest(path: Path) -> tuple[int, str]:
    """Размер и sha256 файла (чтение кусками)."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return size, h.hexdigest()


def path_ok(path: str) -> bool:
    """Путь части по разделу 2: относительный, без `..`, алфавит `[A-Za-z0-9._-]`, до 160."""
    return (
        len(path) <= MAX_PATH
        and PATH_RE.match(path) is not None
        and not any(p in (".", "..") for p in path.split("/"))
    )


def read_glb(data: bytes) -> dict[str, Any]:
    """JSON-блок GLB. ValueError с понятным текстом, если заголовок или блок не читаются."""
    if len(data) < 20:
        raise ValueError("файл короче заголовка GLB")
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("нет заголовка glTF")
    if version != 2:
        raise ValueError(f"версия GLB {version}, нужна 2")
    if length != len(data):
        raise ValueError(f"длина в заголовке {length} не равна размеру файла {len(data)}")
    chunk_len, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON" or 20 + chunk_len > len(data):
        raise ValueError("первый блок GLB не JSON или обрезан")
    try:
        doc = json.loads(data[20 : 20 + chunk_len].rstrip(b" \x00").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"JSON-блок GLB не читается: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("JSON-блок GLB не объект")
    return doc


def glb_info(doc: dict[str, Any]) -> GlbInfo:
    """Имена узлов, число треугольников (по индексам) и имена материалов GLB."""
    nodes = [n.get("name", "") for n in doc.get("nodes", []) if isinstance(n, dict)]
    accessors = doc.get("accessors", [])
    triangles = 0
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            idx = prim.get("indices")
            if prim.get("mode", 4) == 4 and isinstance(idx, int) and idx < len(accessors):
                triangles += int(accessors[idx].get("count", 0)) // 3
    materials = [m.get("name", "") for m in doc.get("materials", []) if isinstance(m, dict)]
    return GlbInfo(nodes, triangles, materials)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _num_list(value: Any, n: int) -> bool:
    return isinstance(value, list) and len(value) == n and all(_is_num(v) for v in value)


def _fields(obj: Any, kind: str, where: str, report: Report) -> bool:
    """Обязательные поля есть (иначе ошибка), лишние - предупреждение. False - не объект."""
    if not isinstance(obj, dict):
        report.error("SCHEMA", where, "ожидался объект JSON")
        return False
    required, optional = FIELDS[kind]
    missing = sorted(required - obj.keys())
    if missing:
        report.error("SCHEMA", where, f"нет полей: {', '.join(missing)}")
    extra = sorted(obj.keys() - required - optional)
    if extra:
        report.warning("EXTRA_FIELDS", where, f"неизвестные поля: {', '.join(extra)}")
    return True


def _load_json(path: Path, where: str, report: Report) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        report.error("JSON", where, f"не читается как JSON: {exc}")
        return None


class Checker:
    """Проверка одного каталога; состояние живёт в экземпляре."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.report = Report()
        self.manifest: dict[str, Any] = {}
        self.parts: dict[str, dict[str, Any]] = {}
        self.disciplines: set[str] = set()
        self.storey_keys: set[str] = set()
        self.glb: dict[str, GlbInfo | None] = {}

    def run(self, previous: Iterable[Path] = ()) -> Report:
        if not self._manifest():
            return self.report
        self._parts()
        self._storeys()
        self._grids()
        self._geometry()
        self._elements()
        self._footprints()
        self._unlisted()
        self._previous(previous)
        return self.report

    # --- манифест -------------------------------------------------------------------------

    def _manifest(self) -> bool:
        path = self.root / "manifest.json"
        if not path.is_file():
            self.report.error("MANIFEST", "manifest.json", "нет файла manifest.json")
            return False
        raw = _load_json(path, "manifest.json", self.report)
        if not _fields(raw, "manifest", "manifest.json", self.report):
            return False
        self.manifest = raw
        r = self.report
        if raw.get("schema") != SCHEMA:
            r.error("SCHEMA", "schema", f"ожидалось {SCHEMA!r}, в пакете {raw.get('schema')!r}")
        if not isinstance(raw.get("generated_at"), str):
            r.error("SCHEMA", "generated_at", "нужна строка времени ISO 8601")
        gen = raw.get("generator")
        if not (
            isinstance(gen, dict)
            and isinstance(gen.get("name"), str)
            and isinstance(gen.get("version"), str)
        ):
            r.error("SCHEMA", "generator", "нужен объект с name и version")
        self._source(raw.get("source"))
        if raw.get("units") != {"length": "mm"}:
            r.error("UNITS", "units", 'единицы длины пакета - только {"length": "mm"}')
        self._frame(raw.get("frame"))
        self._disciplines(raw.get("disciplines"))
        self._counts(raw.get("counts"))
        self._digest(raw)
        return True

    def _frame(self, frame: Any) -> None:
        if not _fields(frame, "frame", "frame", self.report):
            return
        if not isinstance(frame.get("axes"), str):
            self.report.error("SCHEMA", "frame.axes", "нужна строка")
        if not _num_list(frame.get("origin_offset_mm"), 3):
            self.report.error("SCHEMA", "frame.origin_offset_mm", "нужны три числа")

    def _counts(self, counts: Any) -> None:
        if not _fields(counts, "counts", "counts", self.report):
            return
        for key in sorted(FIELDS["counts"][0]):
            if not _is_count(counts.get(key)):
                self.report.error("SCHEMA", f"counts.{key}", "нужно целое ≥ 0")

    def _digest(self, raw: dict[str, Any]) -> None:
        r = self.report
        digest = raw.get("manifest_sha256")
        if not (isinstance(digest, str) and SHA_RE.match(digest)):
            r.error("SCHEMA", "manifest_sha256", "нужен sha256 (64 шестнадцатеричных знака)")
            return
        try:
            actual = manifest_digest(raw)
        except ValueError as exc:
            r.error("MANIFEST_HASH", "manifest_sha256", f"канонический JSON не строится: {exc}")
            return
        if actual != digest:
            r.error("MANIFEST_HASH", "manifest_sha256", "не совпал с содержимым манифеста")

    def _source(self, source: Any) -> None:
        r = self.report
        if not _fields(source, "source", "source", r):
            return
        if source.get("kind") not in SOURCE_KINDS:
            r.error("SCHEMA", "source.kind", f"допустимо: {', '.join(sorted(SOURCE_KINDS))}")
        files = source.get("files")
        if not isinstance(files, list):
            r.error("SCHEMA", "source.files", "нужен список")
            return
        for i, item in enumerate(files):
            where = f"source.files[{i}]"
            if not _fields(item, "source_file", where, r):
                continue
            if not isinstance(item.get("name"), str) or not item["name"]:
                r.error("SCHEMA", where, "нужно имя файла")
            if not _is_count(item.get("bytes")):
                r.error("SCHEMA", where, "bytes - целое ≥ 0")
            if not (isinstance(item.get("sha256"), str) and SHA_RE.match(item["sha256"])):
                r.error("SCHEMA", where, "sha256 - 64 шестнадцатеричных знака")

    def _disciplines(self, items: Any) -> None:
        r = self.report
        if not isinstance(items, list) or not items:
            r.error("SCHEMA", "disciplines", "нужен непустой список")
            return
        for i, item in enumerate(items):
            where = f"disciplines[{i}]"
            if not _fields(item, "discipline", where, r):
                continue
            code = item.get("code")
            if not (isinstance(code, str) and DISCIPLINE_RE.match(code)):
                r.error("DISCIPLINE", where, f"код {code!r}: латиница и цифры, до 16 знаков")
                continue
            if code in self.disciplines:
                r.error("DISCIPLINE", where, f"код {code} повторяется")
            self.disciplines.add(code)

    # --- части ----------------------------------------------------------------------------

    def _parts(self) -> None:
        r = self.report
        parts = self.manifest.get("parts")
        if not isinstance(parts, list):
            r.error("SCHEMA", "parts", "нужен список")
            return
        if len(parts) > MAX_PARTS:
            r.error("LIMIT", "parts", f"частей {len(parts)}, допустимо не больше {MAX_PARTS}")
        total = 0
        kinds: Counter[str] = Counter()
        for i, part in enumerate(parts):
            where = f"parts[{i}]"
            if not _fields(part, "part", where, r):
                continue
            path = part.get("path")
            if not isinstance(path, str) or not path_ok(path):
                r.error("PART_PATH", where, f"недопустимый путь {path!r}")
                continue
            if path in self.parts:
                r.error("PART_DUPLICATE", path, "путь части повторяется")
                continue
            self.parts[path] = part
            kinds[str(part.get("kind"))] += 1
            self._part_shape(path, part)
            total += self._part_file(path, part)
        if total > MAX_TOTAL_BYTES:
            r.error("LIMIT", "parts", f"общий размер {total} байт больше 1 ГиБ")
        if kinds["storeys"] != 1:
            r.error("STOREYS_PART", "parts", "нужна ровно одна часть storeys.json")
        if kinds["grids"] > 1:
            r.error("GRIDS_PART", "parts", "часть grids.json повторяется")
        if kinds["grids"] == 0:
            r.warning("NO_GRIDS", "grids.json", "сетки осей нет: привязка по осям невозможна")
        counts = self.manifest.get("counts")
        if isinstance(counts, dict) and counts.get("parts") != len(parts):
            r.error("COUNTS", "counts.parts", f"указано {counts.get('parts')}, частей {len(parts)}")
        r.stats["bytes_total"] = total
        r.stats["parts"] = len(parts)

    def _part_shape(self, path: str, part: dict[str, Any]) -> None:
        r = self.report
        kind = part.get("kind")
        if kind not in PART_KINDS:
            r.error("PART_KIND", path, f"неизвестный вид части {kind!r}")
            return
        match = PART_PATH_RE[kind].match(path)
        if match is None:
            r.error("PART_KIND_PATH", path, f"путь не подходит для части вида {kind}")
        key = part.get("storey_key")
        if kind in NEEDS_STOREY:
            if not (isinstance(key, str) and KEY_RE.match(key)):
                r.error("PART_STOREY", path, "нет допустимого storey_key")
            elif match is not None and match.group(1) != key:
                r.error("PART_STOREY", path, "storey_key не совпал с путём части")
        elif "storey_key" in part:
            r.warning("EXTRA_FIELDS", path, f"storey_key у части вида {kind} не нужен")
        if kind == "geometry":
            disc = part.get("discipline")
            if disc not in self.disciplines:
                r.error("PART_DISCIPLINE", path, f"дисциплины {disc!r} нет в disciplines")
            elif match is not None and match.group(2) != disc:
                r.error("PART_DISCIPLINE", path, "дисциплина не совпала с путём части")
        elif "discipline" in part:
            r.warning("EXTRA_FIELDS", path, f"discipline у части вида {kind} не нужна")

    def _part_file(self, path: str, part: dict[str, Any]) -> int:
        r = self.report
        raw = part.get("bytes")
        declared = raw if isinstance(raw, int) and _is_count(raw) else 0
        if not _is_count(raw):
            r.error("SCHEMA", path, "bytes - целое ≥ 0")
        if declared > MAX_PART_BYTES:
            r.error("LIMIT", path, f"часть {declared} байт больше 64 МиБ")
        file = self.root / path
        if not file.is_file():
            r.error("PART_MISSING", path, "часть объявлена, но файла нет")
            return declared
        size, digest = file_digest(file)
        if size != declared:
            r.error("PART_HASH", path, f"размер {size} не равен объявленному {declared}")
        if digest != part.get("sha256"):
            r.error("PART_HASH", path, "sha256 не совпал с манифестом")
        return size

    def _paths(self, kind: str) -> list[str]:
        return sorted(p for p, v in self.parts.items() if v.get("kind") == kind)

    # --- этажи и оси ----------------------------------------------------------------------

    def _storeys(self) -> None:
        r = self.report
        paths = self._paths("storeys")
        if not paths or not (self.root / paths[0]).is_file():
            return
        data = _load_json(self.root / paths[0], paths[0], r)
        if not isinstance(data, list) or not data:
            r.error("STOREYS", paths[0], "нужен непустой список этажей")
            return
        elevations: list[float] = []
        for i, st in enumerate(data):
            where = f"storeys.json[{i}]"
            if _fields(st, "storey", where, r) and (elev := self._storey(st, where)) is not None:
                elevations.append(elev)
        if any(b <= a for a, b in pairwise(elevations)):
            r.error("STOREY_ORDER", paths[0], "отметки этажей должны строго возрастать")
        counts = self.manifest.get("counts")
        if isinstance(counts, dict) and counts.get("storeys") != len(data):
            r.error(
                "COUNTS", "counts.storeys", f"указано {counts.get('storeys')}, этажей {len(data)}"
            )
        for path, part in self.parts.items():
            if part.get("kind") in NEEDS_STOREY and part.get("storey_key") not in self.storey_keys:
                r.error("PART_STOREY", path, "этажа части нет в storeys.json")
        r.stats["storeys"] = len(data)

    def _storey(self, st: dict[str, Any], where: str) -> float | None:
        r = self.report
        key = st.get("storey_key")
        if not (isinstance(key, str) and KEY_RE.match(key)):
            r.error("STOREY_KEY", where, f"недопустимый storey_key {key!r}")
        elif key in self.storey_keys:
            r.error("STOREY_KEY", where, f"storey_key {key} повторяется")
        else:
            self.storey_keys.add(key)
        if not isinstance(st.get("name"), str):
            r.error("SCHEMA", where, "name - строка")
        if st.get("elevation_source") not in ELEVATION_SOURCES:
            r.error("SCHEMA", where, f"elevation_source {st.get('elevation_source')!r}")
        height = st.get("height_mm")
        if height is not None and not _is_num(height):
            r.error("SCHEMA", where, "height_mm - число или null")
        elif height is not None and not STOREY_HEIGHT_MM[0] <= height <= STOREY_HEIGHT_MM[1]:
            r.warning("STOREY_HEIGHT", where, f"высота этажа {height:.0f} мм вне 1,5–12 м")
        bbox = st.get("bbox_mm")
        if bbox is not None and not _num_list(bbox, 4):
            r.error("SCHEMA", where, "bbox_mm - четыре числа или null")
        elif bbox is not None:
            extent = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
            if not STOREY_EXTENT_MM[0] <= extent <= STOREY_EXTENT_MM[1]:
                r.warning("STOREY_EXTENT", where, f"габарит {extent / 1000:.1f} м вне 5 м – 2 км")
        elev = st.get("elevation_mm")
        if isinstance(elev, (int, float)) and _is_num(elev):
            return float(elev)
        r.error("SCHEMA", where, "elevation_mm - число")
        return None

    def _grids(self) -> None:
        r = self.report
        for path in self._paths("grids"):
            if not (self.root / path).is_file():
                continue
            data = _load_json(self.root / path, path, r)
            if not _fields(data, "grids", path, r):
                continue
            axes = data.get("axes")
            if not isinstance(axes, list) or not axes:
                r.warning("NO_GRIDS", path, "список осей пуст")
                continue
            seen: set[tuple[str, str]] = set()
            for i, axis in enumerate(axes):
                where = f"{path}[{i}]"
                if not _fields(axis, "axis", where, r):
                    continue
                ok = (
                    isinstance(axis.get("tag"), str)
                    and axis.get("dir") in ("U", "V")
                    and _num_list(axis.get("p0"), 2)
                    and _num_list(axis.get("p1"), 2)
                )
                if not ok:
                    r.error("GRIDS_AXIS", where, "tag - строка, dir - U или V, p0/p1 - два числа")
                    continue
                pair = (axis["tag"], axis["dir"])
                if pair in seen:
                    r.error("GRIDS_AXIS", where, f"пара (tag, dir) {pair} повторяется")
                seen.add(pair)

    # --- геометрия ------------------------------------------------------------------------

    def _geometry(self) -> None:
        r = self.report
        triangles = 0
        for path in self._paths("geometry"):
            file = self.root / path
            if not file.is_file():
                self.glb[path] = None
                continue
            try:
                doc = read_glb(file.read_bytes())
            except ValueError as exc:
                r.error("GLB", path, str(exc))
                self.glb[path] = None
                continue
            info = glb_info(doc)
            self.glb[path] = info
            triangles += info.triangles
            self._glb_content(path, doc, info)
        r.stats["triangles"] = triangles
        counts = self.manifest.get("counts")
        if isinstance(counts, dict) and counts.get("triangles") != triangles:
            r.warning(
                "COUNTS",
                "counts.triangles",
                f"указано {counts.get('triangles')}, в GLB {triangles}",
            )

    def _glb_content(self, path: str, doc: dict[str, Any], info: GlbInfo) -> None:
        r = self.report
        for key in GLB_FORBIDDEN:
            if doc.get(key):
                r.error("GLB_CONTENT", path, f"в GLB запрещён раздел {key}")
        for ext in doc.get("extensionsUsed", []):
            if ext not in GLB_EXTENSIONS:
                r.error("GLB_CONTENT", path, f"расширение {ext} не разрешено")
        if not info.nodes or not all(info.nodes):
            r.error("GLB_NODES", path, "у части нет имён узлов")
        dup = [n for n, c in Counter(info.nodes).items() if c > 1]
        if dup:
            r.error("GLB_NODES", path, f"имена узлов повторяются: {', '.join(dup[:5])}")
        top = {i for s in doc.get("scenes", []) for i in s.get("nodes", [])}
        if len(top) != len(info.nodes):
            r.warning("GLB_NODES", path, "не все узлы - узлы верхнего уровня сцены")
        bad = [m for m in info.materials if not m.startswith("cat:") or m[4:] not in CATEGORIES]
        if bad:
            r.warning("GLB_MATERIAL", path, f"материалы не по категориям: {', '.join(bad[:5])}")

    # --- элементы -------------------------------------------------------------------------

    def _elements(self) -> None:
        r = self.report
        seen: set[str] = set()
        used: dict[str, set[str]] = {p: set() for p in self.glb}
        per_discipline: Counter[str] = Counter()
        categories: Counter[str] = Counter()
        for path in self._paths("elements"):
            file = self.root / path
            if not file.is_file():
                continue
            key = self.parts[path].get("storey_key")
            for number, row in self._jsonl(file, path):
                where = f"{path}:{number}"
                if not _fields(row, "element", where, r):
                    continue
                self._element(row, where, key, seen, used)
                per_discipline[str(row.get("discipline"))] += 1
                categories[str(row.get("category"))] += 1
        total = sum(per_discipline.values())
        r.stats["elements"] = total
        if total > MAX_ELEMENTS:
            r.error("LIMIT", "elements", f"элементов {total}, допустимо не больше {MAX_ELEMENTS}")
        counts = self.manifest.get("counts")
        if isinstance(counts, dict) and counts.get("elements") != total:
            r.error("COUNTS", "counts.elements", f"указано {counts.get('elements')}, строк {total}")
        if total and categories["other"] * 2 > total:
            r.warning(
                "CATEGORIES", "elements", f"категория other у {categories['other']} из {total}"
            )
        for item in self.manifest.get("disciplines", []):
            if (
                isinstance(item, dict)
                and item.get("elements") != per_discipline[str(item.get("code"))]
            ):
                r.warning("COUNTS", f"disciplines.{item.get('code')}", "число элементов не совпало")
        for path, names in used.items():
            info = self.glb.get(path)
            if info is not None and (extra := set(info.nodes) - names):
                r.warning("GLB_NODES", path, f"{len(extra)} узлов без строки в elements")

    def _jsonl(self, file: Path, where: str) -> Iterator[tuple[int, Any]]:
        try:
            text = file.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.report.error("JSON", where, f"не читается: {exc}")
            return
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except ValueError as exc:
                self.report.error("JSON", f"{where}:{number}", f"строка не JSON: {exc}")

    def _element(
        self,
        row: dict[str, Any],
        where: str,
        storey_key: Any,
        seen: set[str],
        used: dict[str, set[str]],
    ) -> None:
        r = self.report
        eid = row.get("id")
        if not (isinstance(eid, str) and ELEMENT_ID_RE.match(eid)):
            r.error("ELEMENT_ID", where, f"недопустимый id {eid!r}")
            return
        if eid in seen:
            r.error("ELEMENT_ID", where, f"id {eid} повторяется в пакете")
        seen.add(eid)
        if row.get("storey_key") != storey_key:
            r.error("ELEMENT_STOREY", where, "storey_key элемента не совпал с этажом файла")
        if row.get("category") not in CATEGORIES:
            r.error("ELEMENT_CATEGORY", where, f"неизвестная категория {row.get('category')!r}")
        if row.get("discipline") not in self.disciplines:
            r.error("ELEMENT_DISCIPLINE", where, f"дисциплины {row.get('discipline')!r} нет")
        bbox = row.get("bbox_mm")
        if bbox is not None and not _num_list(bbox, 6):
            r.error("SCHEMA", where, "bbox_mm - шесть чисел или null")
        self._props(row.get("props"), where)
        part = row.get("part")
        if part is not None:
            self._element_part(row, eid, part, where, storey_key, used)

    def _element_part(
        self,
        row: dict[str, Any],
        eid: str,
        part: Any,
        where: str,
        storey_key: Any,
        used: dict[str, set[str]],
    ) -> None:
        r = self.report
        if not isinstance(part, str) or part not in self.glb:
            r.error("ELEMENT_PART", where, f"части геометрии {part!r} нет в манифесте")
            return
        meta = self.parts[part]
        if meta.get("storey_key") != storey_key:
            r.warning("ELEMENT_PART", where, "часть геометрии другого этажа")
        if meta.get("discipline") != row.get("discipline"):
            r.warning("ELEMENT_PART", where, "дисциплина части не совпала с дисциплиной элемента")
        info = self.glb[part]
        if info is None:
            return
        if eid not in info.nodes:
            r.error("ELEMENT_NODE", where, f"в {part} нет узла {eid}")
        used[part].add(eid)

    def _props(self, props: Any, where: str) -> None:
        r = self.report
        if not isinstance(props, dict):
            r.error("ELEMENT_PROPS", where, "props - объект")
            return
        if len(props) > MAX_PROPS:
            r.error("ELEMENT_PROPS", where, f"свойств {len(props)}, не больше {MAX_PROPS}")
        for key, value in props.items():
            if isinstance(value, str):
                if len(value) > MAX_PROP_STR:
                    r.error("ELEMENT_PROPS", where, f"{key}: строка длиннее {MAX_PROP_STR}")
            elif not (_is_num(value) or isinstance(value, bool)):
                r.error("ELEMENT_PROPS", where, f"{key}: нужна строка, число или логическое")

    # --- разрезы и прочее -----------------------------------------------------------------

    def _footprints(self) -> None:
        r = self.report
        for path in self._paths("footprint"):
            file = self.root / path
            if not file.is_file():
                continue
            data = _load_json(file, path, r)
            if not _fields(data, "footprint", path, r):
                continue
            if data.get("storey_key") != self.parts[path].get("storey_key"):
                r.error("FOOTPRINT", path, "storey_key не совпал с частью")
            if not _is_num(data.get("z_cut_mm")):
                r.error("FOOTPRINT", path, "z_cut_mm - число")
            polygons = data.get("polygons")
            if not isinstance(polygons, dict):
                r.error("FOOTPRINT", path, "polygons - объект")
                continue
            for group, rings in polygons.items():
                self._rings(path, group, rings)

    def _rings(self, path: str, group: str, rings: Any) -> None:
        r = self.report
        if group not in FOOTPRINT_GROUPS:
            r.warning("FOOTPRINT", path, f"неизвестная группа {group!r}")
        if not isinstance(rings, list):
            r.error("FOOTPRINT", path, f"{group}: нужен список контуров")
            return
        if not rings:
            r.warning("FOOTPRINT", path, f"{group}: пустая группа (ключ должен отсутствовать)")
        for ring in rings:
            if not (
                isinstance(ring, list) and len(ring) >= 3 and all(_num_list(p, 2) for p in ring)
            ):
                r.error("FOOTPRINT", path, f"{group}: контур - список из ≥ 3 точек [x, y]")
                return
            if ring[0] == ring[-1]:
                r.warning("FOOTPRINT", path, f"{group}: первая точка контура повторена в конце")
                return

    def _unlisted(self) -> None:
        listed = set(self.parts) | {"manifest.json"}
        for file in sorted(self.root.rglob("*")):
            if file.is_file() and (rel := file.relative_to(self.root).as_posix()) not in listed:
                self.report.warning("UNLISTED", rel, "файл в каталоге не объявлен в манифесте")

    def _previous(self, previous: Iterable[Path]) -> None:
        mine = _source_hashes(self.manifest)
        for path in previous:
            try:
                other = json.loads(Path(path).read_bytes().decode("utf-8"))
            except (OSError, ValueError, UnicodeDecodeError) as exc:
                self.report.warning("PREVIOUS", str(path), f"манифест не читается: {exc}")
                continue
            if mine and mine == _source_hashes(other):
                self.report.warning(
                    "DUPLICATE_SOURCE", str(path), "те же source.files[].sha256 - возможный повтор"
                )


def _source_hashes(manifest: Any) -> frozenset[str]:
    try:
        return frozenset(f["sha256"] for f in manifest["source"]["files"])
    except (KeyError, TypeError):
        return frozenset()


def check_package(root: Path | str, previous: Iterable[Path] = ()) -> Report:
    """Проверка каталога пакета; отчёт с ошибками, предупреждениями и счётчиками."""
    return Checker(Path(root)).run(previous)


def format_report(report: Report, limit: int = 200) -> str:
    """Текст отчёта: сначала ошибки, потом предупреждения, в конце итог."""
    lines = [str(i) for i in report.errors[:limit]] + [str(i) for i in report.warnings[:limit]]
    hidden = max(0, len(report.errors) - limit) + max(0, len(report.warnings) - limit)
    if hidden:
        lines.append(f"... и ещё {hidden} записей")
    stats = ", ".join(f"{k}={v}" for k, v in sorted(report.stats.items()))
    lines.append(
        f"Итого: ошибок {len(report.errors)}, предупреждений {len(report.warnings)}; {stats}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Самопроверка пакета QMP v1 (раздел 9)")
    parser.add_argument("package", type=Path, help="каталог пакета с manifest.json")
    parser.add_argument(
        "--previous",
        type=Path,
        action="append",
        default=[],
        help="манифест прежней версии: предупредить о тех же исходных файлах",
    )
    args = parser.parse_args(argv)
    report = check_package(args.package, args.previous)
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
