"""Сборка пакета QMP v1 из одного или нескольких IFC (весь конвейер спецификации).

Порядок: файлы с повторяющимся sha256 отбрасываются; каждый файл открывается, читаются
единицы, смещение, этажи (сводятся в общий список), оси, элементы по этажам и их
геометрия; затем пишутся storeys.json, grids.json, по этажу - elements, geometry (по
дисциплинам, с делением на части), footprints, и последним manifest.json.
Повторная сборка тех же файлов даёт те же байты частей и тот же `manifest_sha256`.
"""

from __future__ import annotations

import json
import shutil
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import GENERATOR_NAME, __version__
from .categories import CATEGORY_TABLE_VERSION, category_of
from .disciplines import discipline_name, resolve_discipline
from .footprint import build_footprint
from .glb import make_node, plan_parts, write_glb
from .grids import merge_axes
from .ifc_elements import collect_by_storey, element_props, type_name, type_of
from .ifc_source import (
    QmpError,
    RawAxis,
    authoring,
    length_unit_mm,
    open_ifc,
    read_frame,
    read_grids,
    read_storeys,
)
from .qmp_check import ELEMENT_ID_RE, SCHEMA, file_digest, manifest_digest
from .storeys import StoreyIndex, storey_rows
from .tessellate import Mesh, bbox6, tessellate

DEFAULT_PART_LIMIT = 60 * 1024 * 1024  # запас к пределу 64 МиБ на неточность оценки
FRAME_AXES = "X на восток, Y на север, Z вверх"
OWN_ENTRIES = frozenset(
    {"manifest.json", "storeys.json", "grids.json", "elements", "geometry", "footprints"}
)
OFFSET_TOLERANCE_MM = 1.0

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class IfcInput:
    path: Path
    discipline: str | None = None


@dataclass(slots=True)
class Record:
    row: dict[str, Any]
    category: str
    mesh: Mesh | None

    @property
    def triangles(self) -> int:
        return 0 if self.mesh is None else len(self.mesh.faces)


@dataclass(slots=True)
class BuildState:
    storeys: StoreyIndex = field(default_factory=StoreyIndex)
    axes: list[RawAxis] = field(default_factory=list)
    records: dict[str, list[Record]] = field(default_factory=lambda: defaultdict(list))
    ids: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    authoring: list[str] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)
    disciplines: list[str] = field(default_factory=list)
    offset: tuple[float, float, float] | None = None
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class BuildResult:
    out_dir: Path
    manifest: dict[str, Any]
    warnings: list[str]
    storeys: list[dict[str, Any]]
    timings: dict[str, float]


def _quiet(_: str) -> None:
    return None


def _jsonl_line(row: dict[str, Any]) -> str:
    text = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # str.splitlines() (так читает портал) режет строку и по этим знакам - экранируем.
    for ch in (" ", " ", "\x85"):
        text = text.replace(ch, f"\\u{ord(ch):04x}")
    return text


def _json_bytes(value: Any, indent: int | None = None) -> bytes:
    seps = (",", ":") if indent is None else (",", ": ")
    text = json.dumps(value, ensure_ascii=False, indent=indent, separators=seps, allow_nan=False)
    return (text + "\n").encode("utf-8")


def prepare_out_dir(out_dir: Path) -> None:
    """Каталог пакета: новый или с прежней выгрузкой (её части удаляются), посторонних нет."""
    if out_dir.exists() and not out_dir.is_dir():
        raise QmpError(f"{out_dir} - не каталог")
    out_dir.mkdir(parents=True, exist_ok=True)
    foreign = sorted(p.name for p in out_dir.iterdir() if p.name not in OWN_ENTRIES)
    if foreign:
        raise QmpError(
            f"в {out_dir} есть посторонние файлы ({', '.join(foreign[:5])}); нужен пустой каталог"
        )
    for name in sorted(OWN_ENTRIES):
        path = out_dir / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _sources(inputs: Sequence[IfcInput], state: BuildState) -> list[tuple[IfcInput, str]]:
    """Входы без повторов по sha256; для каждого - дисциплина."""
    seen: dict[str, str] = {}
    out: list[tuple[IfcInput, str]] = []
    for item in inputs:
        if not item.path.is_file():
            raise QmpError(f"нет файла {item.path}")
        size, digest = file_digest(item.path)
        if digest in seen:
            state.warnings.append(
                f"{item.path.name}: тот же sha256, что у {seen[digest]} - файл пропущен"
            )
            continue
        seen[digest] = item.path.name
        code, warns = resolve_discipline(item.path.name, item.discipline)
        state.warnings.extend(warns)
        state.files.append(
            {"name": item.path.name, "bytes": size, "sha256": digest, "discipline": code}
        )
        if code not in state.disciplines:
            state.disciplines.append(code)
        out.append((item, code))
    if not out:
        raise QmpError("нет ни одного IFC для выгрузки")
    return out


def _check_offset(state: BuildState, offset: tuple[float, float, float], name: str) -> None:
    if state.offset is None:
        state.offset = offset
        return
    gap = max(abs(a - b) for a, b in zip(offset, state.offset, strict=True))
    if gap > OFFSET_TOLERANCE_MM:
        state.warnings.append(
            f"{name}: смещение начала {list(offset)} отличается от первого файла "
            f"{list(state.offset)}; координаты файла взяты относительно его собственного"
        )


def _storey_match(only: str | None, *names: str) -> bool:
    return only is None or any(only.casefold() in n.casefold() for n in names)


def _process_file(
    item: IfcInput, discipline: str, state: BuildState, only: str | None, threads: int, log: Log
) -> None:
    name = item.path.name
    t0 = time.perf_counter()
    model = open_ifc(item.path)
    log(f"{name}: открыт за {time.perf_counter() - t0:.1f} с, схема {model.schema}")
    unit = length_unit_mm(model, name)
    frame = read_frame(model, unit, state.warnings, name)
    _check_offset(state, frame.offset_mm, name)
    state.authoring.append(authoring(model))
    state.schemas.append(model.schema)
    keys: dict[int, tuple[str, str]] = {}
    for rs in read_storeys(model, frame, state.warnings, name):
        key, warns = state.storeys.register(
            rs.global_id, rs.name, rs.elevation_mm, rs.elevation_source, name
        )
        state.warnings.extend(warns)
        keys[rs.step_id] = (key, rs.name)
    state.axes.extend(read_grids(model, frame, state.warnings, name))
    selected = _select(model, keys, state, only, name)
    t1 = time.perf_counter()
    meshes, heavy = tessellate(model, [e for e, _ in selected], frame.offset_mm, threads)
    if heavy:
        ids = ", ".join(str(e.GlobalId) for e in heavy[:10])
        state.warnings.append(
            f"{name}: у {len(heavy)} элементов проёмы заданы тяжёлыми сетками - геометрия без "
            f"вычитания проёмов: {ids}"
        )
    t2 = time.perf_counter()
    for element, key in selected:
        state.records[key].append(_record(element, key, discipline, meshes.get(element.id())))
    t3 = time.perf_counter()
    log(
        f"{name}: элементов {len(selected)}, с геометрией {len(meshes)}, "
        f"триангуляция {t2 - t1:.1f} с, свойства {t3 - t2:.1f} с"
    )
    state.timings[f"open+read {name}"] = round(t1 - t0, 1)
    state.timings[f"tessellate {name}"] = round(t2 - t1, 1)
    state.timings[f"props {name}"] = round(t3 - t2, 1)
    del model


def _select(
    model: Any, keys: dict[int, tuple[str, str]], state: BuildState, only: str | None, name: str
) -> list[tuple[Any, str]]:
    groups, orphans = collect_by_storey(model)
    if orphans:
        state.warnings.append(f"{name}: элементы вне этажей пропущены: {dict(orphans)}")
    names = {st.key: st.name for st in state.storeys.storeys}
    selected: list[tuple[Any, str]] = []
    bad_ids = 0
    for group in groups:
        if group.storey_step_id not in keys:
            continue
        key, own_name = keys[group.storey_step_id]
        if not _storey_match(only, own_name, names.get(key, "")):
            continue
        for element in group.elements:
            gid = str(element.GlobalId)
            if not ELEMENT_ID_RE.match(gid):
                bad_ids += 1
            elif gid in state.ids:
                state.warnings.append(f"{name}: id {gid} уже есть в пакете - элемент пропущен")
            else:
                state.ids.add(gid)
                selected.append((element, key))
    if bad_ids:
        state.warnings.append(f"{name}: {bad_ids} элементов с недопустимым GlobalId пропущено")
    return selected


def _record(element: Any, key: str, discipline: str, mesh: Mesh | None) -> Record:
    type_obj = type_of(element)
    category = category_of(element, type_obj.is_a() if type_obj is not None else None)
    name = getattr(element, "Name", None)
    row: dict[str, Any] = {
        "id": str(element.GlobalId),
        "category": category,
        "ifc_class": element.is_a(),
        "name": str(name)[:300] if name else None,
        "type": type_name(element, type_obj),
        "discipline": discipline,
        "storey_key": key,
        "bbox_mm": bbox6(mesh.vertices) if mesh is not None else None,
        "part": None,
        "props": element_props(element),
    }
    return Record(row, category, mesh)


class _Writer:
    """Запись частей в каталог пакета; запоминает размер и sha256 каждой."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.parts: list[dict[str, Any]] = []

    def write(self, rel: str, data: bytes, kind: str, **extra: str) -> dict[str, Any]:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        size, digest = file_digest(path)
        part = {"path": rel, "kind": kind, **extra, "bytes": size, "sha256": digest}
        self.parts.append(part)
        return part


def _storey_bbox(records: list[Record]) -> list[float] | None:
    boxes = [r.row["bbox_mm"] for r in records if r.row["bbox_mm"] is not None]
    if not boxes:
        return None
    arr = np.asarray(boxes)
    return [
        float(arr[:, 0].min()),
        float(arr[:, 1].min()),
        float(arr[:, 3].max()),
        float(arr[:, 4].max()),
    ]


def _write_geometry(
    writer: _Writer, key: str, records: list[Record], part_limit: int, generator: str
) -> int:
    """GLB этажа по дисциплинам; заполняет `part` у элементов; возвращает байты GLB."""
    total = 0
    by_disc: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        if rec.mesh is not None:
            by_disc[rec.row["discipline"]].append(rec)
    for disc in sorted(by_disc):
        recs = by_disc[disc]
        nodes = [
            make_node(r.row["id"], r.category, r.mesh.vertices, r.mesh.faces)
            for r in recs
            if r.mesh is not None
        ]
        index = {r.row["id"]: r for r in recs}
        planned = plan_parts(nodes, part_limit)
        for i, chunk in enumerate(planned, start=1):
            suffix = f".{i}" if len(planned) > 1 else ""
            rel = f"geometry/{key}__{disc}{suffix}.glb"
            part = writer.write(
                rel, write_glb(chunk, generator), "geometry", storey_key=key, discipline=disc
            )
            total += part["bytes"]
            for node in chunk:
                index[node.name].row["part"] = rel
    return total


def _write_storey(
    writer: _Writer, storey: dict[str, Any], records: list[Record], part_limit: int, gen: str
) -> dict[str, Any]:
    key = storey["storey_key"]
    records.sort(key=lambda r: r.row["id"])
    glb_bytes = _write_geometry(writer, key, records, part_limit, gen)
    lines = "".join(_jsonl_line(r.row) + "\n" for r in records)
    jsonl = writer.write(f"elements/{key}.jsonl", lines.encode("utf-8"), "elements", storey_key=key)
    fp = build_footprint(
        key,
        float(storey["elevation_mm"]),
        ((r.category, r.mesh.vertices, r.mesh.faces) for r in records if r.mesh is not None),
    )
    fpart = writer.write(f"footprints/{key}.json", _json_bytes(fp), "footprint", storey_key=key)
    polys: dict[str, list[Any]] = fp["polygons"]
    return {
        "storey_key": key,
        "name": storey["name"],
        "elevation_mm": storey["elevation_mm"],
        "elements": len(records),
        "with_geometry": sum(1 for r in records if r.mesh is not None),
        "triangles": sum(r.triangles for r in records),
        "glb_bytes": glb_bytes,
        "elements_bytes": jsonl["bytes"],
        "footprint_bytes": fpart["bytes"],
        "footprint_rings": {g: len(v) for g, v in polys.items()},
    }


def _manifest(
    state: BuildState, writer: _Writer, n_storeys: int, stats: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    per_disc: Counter[str] = Counter(
        rec.row["discipline"] for recs in state.records.values() for rec in recs
    )
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {
            "name": GENERATOR_NAME,
            "version": __version__,
            "category_table": CATEGORY_TABLE_VERSION,
        },
        "source": {
            "kind": "ifc",
            "authoring": "; ".join(dict.fromkeys(a for a in state.authoring if a))[:300],
            "ifc_schema": "; ".join(dict.fromkeys(state.schemas))[:32],
            "files": state.files,
        },
        "units": {"length": "mm"},
        "frame": {"axes": FRAME_AXES, "origin_offset_mm": list(state.offset or (0.0, 0.0, 0.0))},
        "disciplines": [
            {"code": c, "name": discipline_name(c), "elements": per_disc[c]}
            for c in state.disciplines
        ],
        "parts": sorted(writer.parts, key=lambda p: p["path"]),
        "counts": {
            "storeys": n_storeys,
            "elements": sum(per_disc.values()),
            "triangles": sum(s["triangles"] for s in stats),
            "parts": len(writer.parts),
        },
    }
    manifest["manifest_sha256"] = manifest_digest(manifest)
    return manifest


def build_package(
    inputs: Sequence[IfcInput],
    out_dir: Path,
    *,
    only_storey: str | None = None,
    part_limit: int = DEFAULT_PART_LIMIT,
    threads: int = 1,
    log: Log = _quiet,
    now: datetime | None = None,
) -> BuildResult:
    """Собрать пакет QMP v1 в `out_dir` из IFC-файлов."""
    t0 = time.perf_counter()
    state = BuildState()
    for item, discipline in _sources(inputs, state):
        _process_file(item, discipline, state, only_storey, threads, log)
    keep = set(state.records) if only_storey is not None else None
    if only_storey is not None and not keep:
        raise QmpError(f"этаж с подстрокой {only_storey!r} в имени не найден")
    prepare_out_dir(out_dir)
    writer = _Writer(out_dir)
    bboxes = {k: _storey_bbox(v) for k, v in state.records.items()}
    rows = storey_rows(state.storeys.storeys, bboxes, keep)
    writer.write("storeys.json", _json_bytes(rows, indent=1), "storeys")
    axes, warns = merge_axes(state.axes)
    state.warnings.extend(warns)
    if axes:
        writer.write(
            "grids.json", _json_bytes({"source": "IfcGrid", "axes": axes}, indent=1), "grids"
        )
    else:
        state.warnings.append("осей (IfcGrid) нет - grids.json не записан")
    gen = f"{GENERATOR_NAME} {__version__}"
    t1 = time.perf_counter()
    stats = [
        _write_storey(writer, row, state.records[row["storey_key"]], part_limit, gen)
        for row in rows
        if state.records.get(row["storey_key"])
    ]
    for s in stats:
        log(
            f"этаж {s['name']}: элементов {s['elements']}, треугольников {s['triangles']}, "
            f"GLB {s['glb_bytes'] / 1e6:.2f} МБ"
        )
    manifest = _manifest(state, writer, len(rows), stats, now or datetime.now(UTC))
    (out_dir / "manifest.json").write_bytes(_json_bytes(manifest, indent=1))
    state.timings["write"] = round(time.perf_counter() - t1, 1)
    state.timings["total"] = round(time.perf_counter() - t0, 1)
    return BuildResult(out_dir, manifest, state.warnings, stats, state.timings)
