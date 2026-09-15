"""Разбор распакованного проекта PlanSwift.

Проект PlanSwift на диске — дерево каталогов, в каждом `Data.xml` с одним элементом `Item`:

```text
<проект>/Data.xml                         Item Type=Job
<проект>/Pages/<лист>/Data.xml            Class=Page, лист {Image GUID}.tiff или .pdf рядом
<проект>/Takeoff/…/<позиция>/Data.xml     Class=Area | Linear | Count — позиция с именем
            …/<позиция>/<секция>/Data.xml Class=Area Section | Linear Section | Count Section
                     …/<секция>/<выч.>/   Class=Area Subtract Section — без собственного PageGUID
```

Геометрия секции — свойство `DigitizerData`: вложенный XML `<Points><Point X Y PointType/>`,
координаты в пикселях растра листа. Дуги уже развёрнуты: `ArcChild` — точки кривой, `Arc` — точка
на ней же; порядок сохраняется как есть.

Правила (контракт `PLANSWIFT_GROUND_TRUTH_CONTRACT.md`):

- семантическое имя берётся из XML, а не из имени каталога — каталоги усечены;
- вычитаемая секция наследует лист родительской секции площади, и это отмечается;
- секция счёта с несколькими точками — несколько объектов, а не один;
- заглушки `(-1, -1)` и прочие негодные секции отвергаются с причиной, геометрия не чинится;
- `ScaleX`/`ScaleY` — только свидетельство, в калибровку Quantor не превращаются;
- ожидаемые числа проекта в разборе не заданы: их сверяет `stats` с внешним файлом ожиданий.
"""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from planswift_gt.images import (
    PAGE_IMAGE_SUFFIXES,
    ImageInfo,
    ImageRejectedError,
    inspect_image,
)
from planswift_gt.xmlio import XmlRejectedError, decode, parse_text

DATA_FILE = "Data.xml"

KIND_BY_SECTION: dict[str, str] = {
    "Linear Section": "polyline",
    "Area Section": "polygon",
    "Area Subtract Section": "polygon_hole",
    "Count Section": "count",
}
MIN_POINTS_BY_KIND: dict[str, int] = {"polyline": 2, "polygon": 3, "polygon_hole": 3, "count": 1}
HOLE_PARENT_CLASS = "Area Section"


class ProjectRejectedError(ValueError):
    """Каталог не похож на распакованный проект PlanSwift."""


@dataclass(frozen=True, slots=True)
class Node:
    """Один `Data.xml`: элемент дерева PlanSwift."""

    directory: PurePosixPath
    source_path: str
    xml_sha256: str
    item_class: str
    guid: str
    name: str
    properties: dict[str, ET.Element]

    def text(self, name: str) -> str | None:
        element = self.properties.get(name)
        if element is None:
            return None
        value = (element.text or "").strip()
        return value or None


@dataclass(frozen=True, slots=True)
class Page:
    page_guid: str
    name: str
    order_index: str | None
    image_path: str | None
    image: ImageInfo | None
    image_rejection: str | None
    scale_x: str | None
    scale_y: str | None
    scale_units: str | None
    source_path: str
    source_xml_sha256: str


@dataclass(frozen=True, slots=True)
class Annotation:
    id: str
    kind: str
    section_class: str
    label_raw: str | None
    label_path: list[str]
    page_guid: str
    page_guid_inherited: bool
    points_source_px: list[list[float]]
    points_normalized: list[list[float]]
    point_types: list[str]
    object_count: int
    parent_annotation_id: str | None
    source_path: str
    source_xml_sha256: str


@dataclass(frozen=True, slots=True)
class Rejection:
    source_path: str
    source_xml_sha256: str | None
    section_class: str | None
    guid: str | None
    reason: str
    detail: str


@dataclass(slots=True)
class ParseResult:
    project_name: str
    pages: list[Page] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    counters: Counter[str] = field(default_factory=Counter)
    # Каждый прочитанный XML: путь и SHA-256 — основа отпечатка источника.
    sources: list[tuple[str, str]] = field(default_factory=list)


def resolve_project_root(source: Path) -> Path:
    """Корень проекта: сам каталог или единственный подкаталог с `Data.xml` (распаковка 7z)."""
    if (source / DATA_FILE).is_file():
        return source
    candidates = [child for child in source.iterdir() if (child / DATA_FILE).is_file()]
    if len(candidates) == 1:
        return candidates[0]
    raise ProjectRejectedError(
        f"{source}: ожидается проект PlanSwift (Data.xml в корне или в единственном подкаталоге),"
        f" найдено кандидатов: {len(candidates)}"
    )


def _data_files(root: Path) -> list[Path]:
    resolved_root = root.resolve()
    files: list[Path] = []
    for path in root.rglob(DATA_FILE):
        # Ссылка наружу из недоверенного архива не читается.
        if not path.resolve().is_relative_to(resolved_root):
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _read_node(root: Path, path: Path, result: ParseResult) -> Node | Rejection:
    relative = path.relative_to(root).as_posix()
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    result.counters["xml_files"] += 1
    result.sources.append((relative, digest))
    try:
        decoded = decode(raw)
        element = parse_text(decoded.text)
    except XmlRejectedError as error:
        result.counters["xml_rejected"] += 1
        return Rejection(relative, digest, None, None, error.reason, error.detail)

    result.counters[f"xml_encoding_{decoded.encoding}"] += 1
    if decoded.fallback:
        result.counters["xml_cp1251_fallback"] += 1

    properties: dict[str, ET.Element] = {}
    for prop in element.iter("Property"):
        name = prop.get("Name")
        if name is not None and name not in properties:
            properties[name] = prop

    name_property = properties.get("Name")
    semantic_name = (name_property.text or "").strip() if name_property is not None else ""
    return Node(
        directory=PurePosixPath(path.parent.relative_to(root).as_posix()),
        source_path=relative,
        xml_sha256=digest,
        item_class=element.get("Class") or "",
        guid=element.get("GUID") or "",
        name=semantic_name or (element.get("Name") or ""),
        properties=properties,
    )


def _page(root: Path, node: Node, result: ParseResult) -> Page:
    image_element = node.properties.get("Image")
    image_guid = image_element.get("GUID") if image_element is not None else None
    image_path: str | None = None
    image: ImageInfo | None = None
    rejection: str | None = None

    if not image_guid:
        rejection = "image_property_missing"
    else:
        directory = root / Path(node.directory)
        found = sorted(
            candidate
            for candidate in directory.iterdir()
            if candidate.is_file()
            and candidate.stem.upper() == image_guid.upper()
            and candidate.suffix.lower() in PAGE_IMAGE_SUFFIXES
        )
        if not found:
            rejection = "image_file_missing"
        else:
            image_path = found[0].relative_to(root).as_posix()
            try:
                image = inspect_image(found[0])
            except (ImageRejectedError, OSError) as error:
                rejection = getattr(error, "reason", "image_unreadable")

    if rejection is not None:
        result.counters[f"page_{rejection}"] += 1

    return Page(
        page_guid=node.guid,
        name=node.name,
        order_index=node.text("OrderIndex"),
        image_path=image_path,
        image=image,
        image_rejection=rejection,
        scale_x=node.text("ScaleX"),
        scale_y=node.text("ScaleY"),
        scale_units=node.text("Scale Units"),
        source_path=node.source_path,
        source_xml_sha256=node.xml_sha256,
    )


def _coordinate(raw: str | None, result: ParseResult) -> float | None:
    if raw is None:
        return None
    text = raw.strip()
    if "," in text and "." not in text:
        # Десятичная запятая локали. Встречается в свойствах листа; в точках — считается.
        result.counters["point_comma_decimal"] += 1
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _points(node: Node, result: ParseResult) -> tuple[list[tuple[float, float, str]], str | None]:
    """Точки `DigitizerData` или код причины отказа."""
    raw = node.text("DigitizerData")
    if raw is None:
        return [], "no_digitizer_data"
    try:
        element = parse_text(raw)
    except XmlRejectedError as error:
        return [], f"digitizer_{error.reason}"

    points: list[tuple[float, float, str]] = []
    for point in element.iter("Point"):
        x = _coordinate(point.get("X"), result)
        y = _coordinate(point.get("Y"), result)
        if x is None or y is None:
            return [], "invalid_coordinate"
        points.append((x, y, point.get("PointType") or "Normal"))
    if not points:
        return [], "no_points"
    return points, None


def _labels(
    node: Node, nodes: dict[PurePosixPath, Node], project: Node
) -> tuple[str | None, list[str]]:
    """Имя позиции (ближайший предок не-секция) и путь имён от корня проекта."""
    chain: list[Node] = []
    directory = node.directory.parent
    while True:
        ancestor = nodes.get(directory)
        if ancestor is not None and ancestor is not project:
            chain.append(ancestor)
        if directory == directory.parent:
            break
        directory = directory.parent
    label = next(
        (ancestor.name for ancestor in chain if not ancestor.item_class.endswith("Section")), None
    )
    return label, [ancestor.name for ancestor in reversed(chain)]


def parse_project(source: Path) -> ParseResult:
    root = resolve_project_root(source)
    probe = ParseResult(project_name=root.name)

    nodes: dict[PurePosixPath, Node] = {}
    for path in _data_files(root):
        outcome = _read_node(root, path, probe)
        if isinstance(outcome, Rejection):
            probe.rejections.append(outcome)
        else:
            nodes[outcome.directory] = outcome

    project = nodes.get(PurePosixPath("."))
    if project is None:
        raise ProjectRejectedError(f"{root}: корневой Data.xml не разобран")
    probe.project_name = project.name or root.name

    pages: dict[str, Page] = {}
    for node in nodes.values():
        if node.item_class != "Page":
            continue
        probe.counters["pages"] += 1
        if node.guid in pages:
            probe.rejections.append(
                Rejection(
                    node.source_path, node.xml_sha256, "Page", node.guid, "duplicate_page_guid", ""
                )
            )
            continue
        pages[node.guid] = _page(root, node, probe)
    probe.pages = sorted(pages.values(), key=lambda page: page.page_guid)

    sections = [node for node in nodes.values() if node.item_class.endswith("Section")]
    # Площади раньше вычитаний: отверстие проверяет, принят ли родитель.
    sections.sort(key=lambda node: (node.item_class == "Area Subtract Section", node.source_path))

    accepted: dict[str, Annotation] = {}
    by_directory: dict[PurePosixPath, Annotation] = {}
    for node in sections:
        probe.counters[f"section:{node.item_class}"] += 1
        section = _section(node, nodes, project, pages, by_directory, accepted, probe)
        if isinstance(section, Rejection):
            probe.rejections.append(section)
            probe.counters[f"rejected:{section.reason}"] += 1
            continue
        accepted[section.id] = section
        by_directory[node.directory] = section
        probe.counters[f"accepted:{section.kind}"] += 1
        probe.counters[f"objects:{section.kind}"] += section.object_count

    probe.annotations = sorted(
        accepted.values(), key=lambda item: (item.page_guid, item.source_path)
    )
    probe.rejections.sort(key=lambda item: (item.source_path, item.reason))
    return probe


def _section(
    node: Node,
    nodes: dict[PurePosixPath, Node],
    project: Node,
    pages: dict[str, Page],
    by_directory: dict[PurePosixPath, Annotation],
    accepted: dict[str, Annotation],
    result: ParseResult,
) -> Annotation | Rejection:
    def reject(reason: str, detail: str = "") -> Rejection:
        return Rejection(
            node.source_path, node.xml_sha256, node.item_class, node.guid, reason, detail
        )

    kind = KIND_BY_SECTION.get(node.item_class)
    if kind is None:
        return reject("unsupported_section_class", node.item_class)
    if not node.guid:
        return reject("guid_missing")
    if node.guid in accepted:
        return reject("duplicate_guid")

    parent: Annotation | None = None
    page_guid = node.text("PageGUID")
    inherited = False
    if kind == "polygon_hole":
        parent_node = nodes.get(node.directory.parent)
        if parent_node is None or parent_node.item_class != HOLE_PARENT_CLASS:
            return reject("hole_parent_missing", parent_node.item_class if parent_node else "")
        parent = by_directory.get(parent_node.directory)
        if parent is None:
            return reject("hole_parent_rejected", parent_node.guid)
        if page_guid is None:
            page_guid, inherited = parent.page_guid, True
        elif page_guid != parent.page_guid:
            return reject("hole_page_differs_from_parent", f"{page_guid} ≠ {parent.page_guid}")

    if page_guid is None:
        return reject("page_guid_missing")
    page = pages.get(page_guid)
    if page is None:
        return reject("page_not_found", page_guid)
    if page.image is None:
        return reject("page_image_unavailable", page.image_rejection or "")

    points, problem = _points(node, result)
    if problem is not None:
        return reject(problem)

    placeholders = sum(1 for x, y, _ in points if x < 0 or y < 0)
    if placeholders == len(points):
        return reject("placeholder_coordinates", f"{placeholders} из {len(points)}")
    if placeholders:
        return reject("partial_placeholder_coordinates", f"{placeholders} из {len(points)}")

    width, height = page.image.width_px, page.image.height_px
    if any(x > width or y > height for x, y, _ in points):
        return reject("outside_image", f"растр {width}×{height}")
    if len(points) < MIN_POINTS_BY_KIND[kind]:
        return reject("too_few_points", f"{len(points)} < {MIN_POINTS_BY_KIND[kind]}")

    for _, _, point_type in points:
        result.counters[f"point_type:{point_type}"] += 1

    label, label_path = _labels(node, nodes, project)
    return Annotation(
        id=node.guid,
        kind=kind,
        section_class=node.item_class,
        label_raw=label,
        label_path=label_path,
        page_guid=page_guid,
        page_guid_inherited=inherited,
        points_source_px=[[x, y] for x, y, _ in points],
        points_normalized=[[x / width, y / height] for x, y, _ in points],
        point_types=[point_type for _, _, point_type in points],
        object_count=len(points) if kind == "count" else 1,
        parent_annotation_id=parent.id if parent is not None else None,
        source_path=node.source_path,
        source_xml_sha256=node.xml_sha256,
    )
