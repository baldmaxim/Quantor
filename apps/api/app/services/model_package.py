"""Пакет модели QMP v1 (ADR-0053): разбор манифеста и проверка частей.

Чистая логика без базы и хранилища. Сервис приёма отдаёт сюда читателя частей (`PackageReader`),
тесты - словарь в памяти. Правила - раздел 9 docs/building-model/07-model-package-qmp-v1.md:
ошибка отклоняет пакет, предупреждение сохраняется в версии модели.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCHEMA = "quantor.model_package.v1"

MAX_PARTS = 2_000
MAX_ELEMENTS = 500_000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_PATH = 160
MAX_GLB_JSON_BYTES = 32 * 1024 * 1024
STOREY_HEIGHT_MM = (1_500.0, 12_000.0)
STOREY_EXTENT_MM = (5_000.0, 2_000_000.0)
GRID_TOLERANCE_MM = 10.0
MAX_REPORTED_MISSING = 5

PartKind = Literal["storeys", "grids", "elements", "geometry", "footprint"]
IssueLevel = Literal["error", "warning"]

_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ELEMENT_ID = re.compile(r"^[A-Za-z0-9_$.:-]{1,64}$")
_DISCIPLINE = re.compile(r"^[A-Z0-9]{1,16}$")
_GLB_MAGIC = 0x46546C67
_GLB_JSON = 0x4E4F534A
_GLB_EXTENSIONS = frozenset({"KHR_materials_unlit", "KHR_mesh_quantization"})
_GLB_FORBIDDEN = ("images", "textures", "animations", "cameras")
_PART_PATTERN: dict[str, re.Pattern[str]] = {
    "storeys": re.compile(r"^storeys\.json$"),
    "grids": re.compile(r"^grids\.json$"),
    "elements": re.compile(r"^elements/[A-Za-z0-9_-]{1,64}\.jsonl$"),
    "geometry": re.compile(r"^geometry/[A-Za-z0-9_-]{1,64}__[A-Z0-9]{1,16}(?:\.[0-9]{1,3})?\.glb$"),
    "footprint": re.compile(r"^footprints/[A-Za-z0-9_-]{1,64}\.json$"),
}
_NEEDS_STOREY = frozenset({"elements", "geometry", "footprint"})


@dataclass(frozen=True, slots=True)
class Issue:
    level: IssueLevel
    code: str
    where: str
    message: str


@dataclass(slots=True)
class Report:
    issues: list[Issue] = field(default_factory=list)

    def error(self, code: str, where: str, message: str) -> None:
        self.issues.append(Issue("error", code, where, message))

    def warning(self, code: str, where: str, message: str) -> None:
        self.issues.append(Issue("warning", code, where, message))

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


_Sha = Annotated[str, Field(pattern=_SHA256.pattern)]


class SourceFile(_Model):
    name: Annotated[str, Field(min_length=1, max_length=260)]
    bytes: Annotated[int, Field(ge=0)]
    sha256: _Sha
    discipline: Annotated[str, Field(max_length=16)] | None = None


class Source(_Model):
    kind: Literal["ifc", "navisworks", "revit", "other"]
    authoring: Annotated[str, Field(max_length=300)] | None = None
    ifc_schema: Annotated[str, Field(max_length=32)] | None = None
    files: Annotated[list[SourceFile], Field(max_length=100)] = Field(default_factory=list)


class Part(_Model):
    path: Annotated[str, Field(min_length=1, max_length=MAX_PATH)]
    kind: PartKind
    bytes: Annotated[int, Field(ge=0)]
    sha256: _Sha
    storey_key: str | None = None
    discipline: str | None = None


class Discipline(_Model):
    code: str
    name: Annotated[str, Field(max_length=120)] | None = None
    elements: Annotated[int, Field(ge=0)] | None = None


class Frame(_Model):
    axes: Annotated[str, Field(max_length=200)] | None = None
    origin_offset_mm: Annotated[list[float], Field(min_length=3, max_length=3)] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0]
    )


class Counts(_Model):
    storeys: Annotated[int, Field(ge=0)]
    elements: Annotated[int, Field(ge=0)]
    triangles: Annotated[int, Field(ge=0)] = 0
    parts: Annotated[int, Field(ge=0)]


class Manifest(_Model):
    schema_: Literal["quantor.model_package.v1"] = Field(alias="schema")
    generated_at: str | None = None
    generator: dict[str, Any] = Field(default_factory=dict)
    source: Source
    units: dict[str, str]
    frame: Frame = Field(default_factory=Frame)
    disciplines: Annotated[list[Discipline], Field(max_length=200)]
    parts: Annotated[list[Part], Field(max_length=MAX_PARTS)]
    counts: Counts
    manifest_sha256: _Sha

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Storey(_Model):
    storey_key: str
    name: Annotated[str, Field(max_length=200)]
    elevation_mm: float
    height_mm: float | None = None
    elevation_source: str | None = None
    bbox_mm: Annotated[list[float], Field(min_length=4, max_length=4)] | None = None
    # Здание этажа (раздел 4): в модели с несколькими зданиями, оба поля вместе.
    building_key: str | None = None
    building_name: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class Element(_Model):
    id: str
    category: Annotated[str, Field(min_length=1, max_length=32)]
    ifc_class: Annotated[str, Field(max_length=64)] | None = None
    name: Annotated[str, Field(max_length=300)] | None = None
    type: Annotated[str, Field(max_length=300)] | None = None
    discipline: str
    storey_key: str
    bbox_mm: Annotated[list[float], Field(min_length=6, max_length=6)] | None = None
    part: str | None = None
    props: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PartStat(Protocol):
    @property
    def bytes(self) -> int: ...

    @property
    def sha256(self) -> str: ...


class PackageReader(Protocol):
    """Доступ к частям загруженного пакета: хранилище в сервисе, словарь в тестах."""

    def stat(self, path: str) -> PartStat | None: ...

    def head(self, path: str, size: int) -> bytes: ...

    def read(self, path: str) -> bytes: ...

    def lines(self, path: str) -> Iterable[str]: ...


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def manifest_digest(raw: dict[str, Any]) -> str:
    """sha256 канонического манифеста без `manifest_sha256` и `generated_at` (раздел 2)."""
    body = {k: v for k, v in raw.items() if k not in ("manifest_sha256", "generated_at")}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def part_path_ok(path: str) -> bool:
    return (
        len(path) <= MAX_PATH
        and _PATH.match(path) is not None
        and ".." not in path.split("/")
        and not path.startswith(".")
    )


def parse_manifest(data: bytes, report: Report) -> tuple[Manifest | None, dict[str, Any]]:
    """Разбор манифеста по схеме; при ошибке - `None` и записи в отчёте."""
    try:
        raw = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        report.error("MANIFEST_JSON", "manifest.json", "Манифест не читается как JSON")
        return None, {}
    if not isinstance(raw, dict):
        report.error("MANIFEST_JSON", "manifest.json", "Манифест должен быть объектом JSON")
        return None, {}
    try:
        return Manifest.model_validate(raw), raw
    except ValidationError as error:
        for item in error.errors()[:10]:
            where = ".".join(str(x) for x in item["loc"]) or "manifest.json"
            report.error("MANIFEST_SCHEMA", where, f"Поле не соответствует схеме: {item['type']}")
        return None, raw


def check_manifest(manifest: Manifest, raw: dict[str, Any], report: Report) -> None:
    """Перекрёстные проверки манифеста без чтения частей."""
    if manifest.units.get("length") != "mm":
        report.error("UNITS", "units.length", "Единицы длины в пакете - только миллиметры")
    if manifest_digest(raw) != manifest.manifest_sha256:
        report.error("MANIFEST_HASH", "manifest_sha256", "manifest_sha256 не совпал с содержимым")
    if len(manifest.parts) != manifest.counts.parts:
        report.error("COUNT_PARTS", "counts.parts", "Число частей не совпало с counts.parts")
    codes = [d.code for d in manifest.disciplines]
    for code in codes:
        if _DISCIPLINE.match(code) is None:
            report.error("DISCIPLINE", "disciplines", f"Код дисциплины {code!r} недопустим")
    if len(set(codes)) != len(codes):
        report.error("DISCIPLINE", "disciplines", "Коды дисциплин повторяются")
    seen: set[str] = set()
    total = 0
    kinds: dict[str, int] = {}
    for part in manifest.parts:
        _check_part(part, set(codes), seen, report)
        total += part.bytes
        kinds[part.kind] = kinds.get(part.kind, 0) + 1
    if total > MAX_TOTAL_BYTES:
        report.error("TOTAL_SIZE", "parts", "Пакет больше 1 ГиБ")
    if kinds.get("storeys", 0) != 1:
        report.error("STOREYS_PART", "parts", "В пакете должна быть ровно одна часть storeys.json")
    if kinds.get("grids", 0) > 1:
        report.error("GRIDS_PART", "parts", "Часть grids.json повторяется")
    if manifest.counts.elements > MAX_ELEMENTS:
        report.error("COUNT_ELEMENTS", "counts.elements", "Элементов больше 500 000")
    if kinds.get("grids", 0) == 0:
        report.warning(
            "NO_GRIDS", "grids.json", "Сетки осей нет: привязка чертежей по осям невозможна"
        )
    if kinds.get("footprint", 0) == 0:
        report.warning("NO_FOOTPRINTS", "footprints", "Разрезов этажей нет")


def _check_part(part: Part, disciplines: set[str], seen: set[str], report: Report) -> None:
    where = part.path
    if not part_path_ok(part.path):
        report.error("PART_PATH", where, "Недопустимый путь части")
        return
    if part.path in seen:
        report.error("PART_DUPLICATE", where, "Путь части повторяется")
    seen.add(part.path)
    if _PART_PATTERN[part.kind].match(part.path) is None:
        report.error("PART_KIND_PATH", where, f"Путь не подходит для части вида {part.kind}")
    if part.bytes > MAX_PART_BYTES:
        report.error("PART_SIZE", where, "Часть больше 64 МБ")
    if part.kind in _NEEDS_STOREY and (
        part.storey_key is None or _KEY.match(part.storey_key) is None
    ):
        report.error("PART_STOREY", where, "У части нет допустимого storey_key")
    if part.kind == "geometry":
        if part.discipline is None or part.discipline not in disciplines:
            report.error(
                "PART_DISCIPLINE", where, "У геометрии нет дисциплины из списка disciplines"
            )
        elif f"__{part.discipline}" not in part.path:
            report.error("PART_DISCIPLINE", where, "Дисциплина части не совпала с её путём")
    if (
        part.kind in _NEEDS_STOREY
        and part.storey_key is not None
        and f"/{part.storey_key}" not in part.path
    ):
        report.error("PART_STOREY", where, "storey_key части не совпал с её путём")


def check_stats(manifest: Manifest, reader: PackageReader, report: Report) -> None:
    """Каждая объявленная часть загружена, размер и sha256 совпали с манифестом."""
    for part in manifest.parts:
        stat = reader.stat(part.path)
        if stat is None:
            report.error("PART_MISSING", part.path, "Часть объявлена в манифесте, но не загружена")
        elif stat.bytes != part.bytes or stat.sha256 != part.sha256:
            report.error("PART_HASH", part.path, "Размер или sha256 части не совпали с манифестом")


def check_storeys(data: bytes, report: Report) -> list[Storey]:
    try:
        raw = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        report.error("STOREYS_JSON", "storeys.json", "storeys.json не читается как JSON")
        return []
    if not isinstance(raw, list) or not raw:
        report.error("STOREYS_JSON", "storeys.json", "storeys.json должен быть непустым списком")
        return []
    storeys: list[Storey] = []
    for index, item in enumerate(raw):
        try:
            storey = Storey.model_validate(item)
        except ValidationError:
            report.error("STOREY_SCHEMA", f"storeys.json[{index}]", "Этаж не соответствует схеме")
            continue
        if _KEY.match(storey.storey_key) is None:
            report.error("STOREY_KEY", f"storeys.json[{index}]", "Недопустимый storey_key")
        _check_building(storey, f"storeys.json[{index}]", report)
        storeys.append(storey)
    keys = [s.storey_key for s in storeys]
    if len(set(keys)) != len(keys):
        report.error("STOREY_KEY", "storeys.json", "storey_key повторяется")
    names: dict[str, str] = {}
    elevations: dict[str | None, list[float]] = {}
    for storey in storeys:
        elevations.setdefault(storey.building_key, []).append(storey.elevation_mm)
        if (
            storey.building_key is not None
            and storey.building_name is not None
            and names.setdefault(storey.building_key, storey.building_name) != storey.building_name
        ):
            report.error("STOREY_BUILDING", "storeys.json", "У здания разные имена")
    if any(b <= a for group in elevations.values() for a, b in pairwise(group)):
        report.error("STOREY_ORDER", "storeys.json", "Отметки этажей здания должны возрастать")
    for storey in storeys:
        _storey_plausibility(storey, report)
    return storeys


def _check_building(storey: Storey, where: str, report: Report) -> None:
    """`building_key` и `building_name` - вместе или ни одного; ключ из алфавита storey_key."""
    if storey.building_key is None and storey.building_name is None:
        return
    if storey.building_key is None or storey.building_name is None:
        report.error("STOREY_BUILDING", where, "Здание этажа: нужны building_key и building_name")
    elif _KEY.match(storey.building_key) is None:
        report.error("STOREY_BUILDING", where, "Недопустимый building_key")


def _storey_plausibility(storey: Storey, report: Report) -> None:
    if storey.height_mm is not None and not (
        STOREY_HEIGHT_MM[0] <= storey.height_mm <= STOREY_HEIGHT_MM[1]
    ):
        report.warning(
            "STOREY_HEIGHT",
            storey.storey_key,
            f"Высота этажа {storey.height_mm:.0f} мм вне 1,5-12 м",
        )
    if storey.bbox_mm is not None:
        width = max(storey.bbox_mm[2] - storey.bbox_mm[0], storey.bbox_mm[3] - storey.bbox_mm[1])
        if not (STOREY_EXTENT_MM[0] <= width <= STOREY_EXTENT_MM[1]):
            report.warning("STOREY_EXTENT", storey.storey_key, "Габарит этажа вне 5 м - 2 км")


def check_grids(data: bytes, report: Report) -> None:
    try:
        raw = json.loads(data)
        axes = raw["axes"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        report.error("GRIDS_JSON", "grids.json", "grids.json не читается или без списка axes")
        return
    if not isinstance(axes, list) or not axes:
        report.warning("NO_GRIDS", "grids.json", "Сетка осей пуста")
        return
    seen: set[tuple[str, str]] = set()
    for index, axis in enumerate(axes):
        ok = (
            isinstance(axis, dict)
            and isinstance(axis.get("tag"), str)
            and axis.get("dir") in ("U", "V")
            and _point_ok(axis.get("p0"))
            and _point_ok(axis.get("p1"))
        )
        if not ok:
            report.error("GRIDS_AXIS", f"grids.json[{index}]", "Ось не соответствует схеме")
            continue
        pair = (axis["tag"], axis["dir"])
        if pair in seen:
            report.error("GRIDS_AXIS", f"grids.json[{index}]", "Пара (tag, dir) повторяется")
        seen.add(pair)


def _point_ok(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    )


def read_glb_nodes(head: bytes, report: Report, where: str) -> set[str] | None:
    """Имена узлов GLB по заголовку и JSON-блоку (двоичный блок не читается)."""
    if len(head) < 20:
        report.error("GLB_HEADER", where, "GLB короче заголовка")
        return None
    magic, version, _length = struct.unpack_from("<III", head, 0)
    if magic != _GLB_MAGIC or version != 2:
        report.error("GLB_HEADER", where, "Нет заголовка glTF 2.0 binary")
        return None
    json_len, json_type = struct.unpack_from("<II", head, 12)
    if json_type != _GLB_JSON or json_len > MAX_GLB_JSON_BYTES or len(head) < 20 + json_len:
        report.error("GLB_JSON", where, "JSON-блок GLB не найден или слишком велик")
        return None
    try:
        doc = json.loads(head[20 : 20 + json_len].rstrip(b" \x00"))
    except (ValueError, UnicodeDecodeError):
        report.error("GLB_JSON", where, "JSON-блок GLB не читается")
        return None
    for key in _GLB_FORBIDDEN:
        if doc.get(key):
            report.error("GLB_CONTENT", where, f"В GLB запрещён раздел {key}")
    for ext in doc.get("extensionsUsed", []):
        if ext not in _GLB_EXTENSIONS:
            report.error("GLB_CONTENT", where, f"Расширение glTF {ext} не разрешено")
    names = {n["name"] for n in doc.get("nodes", []) if isinstance(n, dict) and n.get("name")}
    if not names:
        report.error("GLB_NODES", where, "В GLB нет именованных узлов")
        return None
    return names


def glb_head(reader: PackageReader, path: str) -> bytes:
    """Заголовок и JSON-блок: сначала 20 байт, затем ровно столько, сколько объявлено."""
    start = reader.head(path, 20)
    if len(start) < 20:
        return start
    json_len = struct.unpack_from("<I", start, 12)[0]
    return reader.head(path, 20 + min(json_len, MAX_GLB_JSON_BYTES))


def check_elements(
    lines: Iterable[str],
    *,
    storey_key: str,
    where: str,
    disciplines: set[str],
    geometry: dict[str, set[str] | None],
    seen_ids: set[str],
    report: Report,
) -> int:
    """Строки `elements/<этаж>.jsonl`; число элементов. `geometry` - имена узлов по части."""
    count = 0
    uncategorised = 0
    missing = 0
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            element = Element.model_validate_json(line)
        except ValidationError:
            report.error("ELEMENT_SCHEMA", f"{where}:{number}", "Элемент не соответствует схеме")
            continue
        count += 1
        if _ELEMENT_ID.match(element.id) is None:
            report.error("ELEMENT_ID", f"{where}:{number}", "Недопустимый id элемента")
        elif element.id in seen_ids:
            report.error("ELEMENT_ID", f"{where}:{number}", "id элемента повторяется в пакете")
        seen_ids.add(element.id)
        if element.storey_key != storey_key:
            report.error(
                "ELEMENT_STOREY", f"{where}:{number}", "Элемент лежит в файле чужого этажа"
            )
        if element.discipline not in disciplines:
            report.error("ELEMENT_DISCIPLINE", f"{where}:{number}", "Дисциплина не из disciplines")
        if len(element.props) > 24:
            report.error("ELEMENT_PROPS", f"{where}:{number}", "Больше 24 свойств")
        if element.category == "other":
            uncategorised += 1
        if element.part is not None:
            if element.part not in geometry:
                report.error("ELEMENT_PART", f"{where}:{number}", "Часть геометрии не объявлена")
            elif (names := geometry[element.part]) is not None and element.id not in names:
                missing += 1
                if missing <= MAX_REPORTED_MISSING:
                    report.error(
                        "ELEMENT_NODE", f"{where}:{number}", "В части GLB нет узла элемента"
                    )
    if count and uncategorised * 2 > count:
        report.warning("CATEGORIES", where, "Больше половины элементов без категории")
    return count


def validate_package(
    manifest_bytes: bytes, reader: PackageReader
) -> tuple[Report, Manifest | None]:
    """Полная проверка пакета: манифест, части, этажи, оси, элементы, GLB."""
    report = Report()
    manifest, raw = parse_manifest(manifest_bytes, report)
    if manifest is None:
        return report, None
    check_manifest(manifest, raw, report)
    check_stats(manifest, reader, report)
    if not report.ok:
        return report, manifest
    storeys = _storeys_of(manifest, reader, report)
    keys = {s.storey_key for s in storeys}
    for part in manifest.parts:
        if part.kind in _NEEDS_STOREY and part.storey_key not in keys:
            report.error("PART_STOREY", part.path, "Этаж части не найден в storeys.json")
    for part in manifest.parts:
        if part.kind == "grids":
            check_grids(reader.read(part.path), report)
    _check_content(manifest, reader, report)
    return report, manifest


def _storeys_of(manifest: Manifest, reader: PackageReader, report: Report) -> list[Storey]:
    path = next(p.path for p in manifest.parts if p.kind == "storeys")
    storeys = check_storeys(reader.read(path), report)
    if len(storeys) != manifest.counts.storeys:
        report.error("COUNT_STOREYS", "counts.storeys", "Число этажей не совпало с counts.storeys")
    return storeys


def _check_content(manifest: Manifest, reader: PackageReader, report: Report) -> None:
    codes = {d.code for d in manifest.disciplines}
    nodes: dict[str, set[str] | None] = {}
    for part in manifest.parts:
        if part.kind == "geometry":
            nodes[part.path] = read_glb_nodes(glb_head(reader, part.path), report, part.path)
    seen: set[str] = set()
    total = 0
    for part in manifest.parts:
        if part.kind == "elements" and part.storey_key is not None:
            total += check_elements(
                reader.lines(part.path),
                storey_key=part.storey_key,
                where=part.path,
                disciplines=codes,
                geometry=nodes,
                seen_ids=seen,
                report=report,
            )
    if total != manifest.counts.elements:
        report.error("COUNT_ELEMENTS", "counts.elements", "Число элементов не совпало со счётчиком")


@dataclass(frozen=True, slots=True)
class FileStat:
    bytes: int
    sha256: str


class DirectoryReader:
    """Части пакета в каталоге: результат генератора до загрузки в хранилище."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._stats: dict[str, FileStat] = {}

    def _file(self, path: str) -> Path | None:
        if not part_path_ok(path):
            return None
        found = (self._root / path).resolve()
        return found if found.is_file() and found.is_relative_to(self._root) else None

    def stat(self, path: str) -> FileStat | None:
        if path in self._stats:
            return self._stats[path]
        found = self._file(path)
        if found is None:
            return None
        digest = hashlib.sha256()
        with found.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        self._stats[path] = FileStat(found.stat().st_size, digest.hexdigest())
        return self._stats[path]

    def head(self, path: str, size: int) -> bytes:
        found = self._file(path)
        if found is None:
            return b""
        with found.open("rb") as handle:
            return handle.read(size)

    def read(self, path: str) -> bytes:
        found = self._file(path)
        return b"" if found is None else found.read_bytes()

    def lines(self, path: str) -> Iterator[str]:
        found = self._file(path)
        if found is None:
            return
        with found.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                yield line.rstrip("\n")
