"""Read only CAD headers and workbook sheet names, never BOQ cells or BIM content."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .common import Document
from .rules import BOQ_PATTERN, DXF_VERSION_PATTERN, classify, path_sources


def describe(file_id: str, path: Path, source: str, stored: str) -> Document:
    ext = Path(source).suffix.lower()
    kind = {
        ".pdf": "pdf",
        ".dwg": "dwg_header",
        ".dxf": "dxf_header",
        ".xlsx": "spreadsheet",
        ".xls": "spreadsheet",
        ".csv": "spreadsheet",
        ".rvt": "bim_inventory_only",
        ".nwc": "bim_inventory_only",
        ".nwd": "bim_inventory_only",
        ".ifc": "bim_inventory_only",
    }.get(ext, "other")
    document = Document(file_id, [source], ext, path.stat().st_size, stored, kind)
    document.classification = classify(path_sources([source]))
    if ext in (".dwg", ".dxf"):
        with path.open("rb") as stream:
            header = stream.read(6 if ext == ".dwg" else 65536)
        if ext == ".dwg":
            version = header.decode("ascii", errors="replace")
            if re.fullmatch(r"AC\d{4}", version):
                document.header_version = version
        else:
            match = re.search(DXF_VERSION_PATTERN, header)
            if match:
                document.header_version = match.group(1).decode("ascii")
        if not document.header_version:
            document.issues.append("cad_header_unavailable")
    if ext == ".xlsx":
        try:
            with zipfile.ZipFile(path) as book:
                info = book.getinfo("xl/workbook.xml")
                if (
                    info.file_size > 2 * 1024**2
                    or info.file_size / max(info.compress_size, 1) > 200
                ):
                    raise ValueError("workbook_metadata_limit")
                data = book.read(info).decode("utf-8-sig")
                if "<!DOCTYPE" in data.upper() or "<!ENTITY" in data.upper() or "\x00" in data:
                    raise ValueError("xml_entity_declaration")
                parser: ElementTree.XMLPullParser[ElementTree.Element[str]] = (
                    ElementTree.XMLPullParser(events=("start",))
                )
                parser.feed(data)
                parser.close()
                document.workbook_sheets = [
                    event[1].attrib.get("name", "")
                    for event in parser.read_events()
                    if isinstance(event, tuple)
                    and len(event) == 2
                    and isinstance(event[1], ElementTree.Element)
                    and event[1].tag.endswith("}sheet")
                ]
        except Exception as error:
            document.issues.append("workbook_metadata_unavailable:" + type(error).__name__)
    if ext == ".xls":
        document.issues.append("xls_sheet_names_unavailable_no_binary_workbook_parser")
    if kind == "spreadsheet":
        document.boq_or_spec_candidate = bool(
            re.search(
                BOQ_PATTERN, source + "\n" + "\n".join(document.workbook_sheets), re.IGNORECASE
            )
        )
    return document


def link_cad_pdfs(documents: list[Document]) -> None:
    by_stem: dict[str, set[str]] = {}
    for document in documents:
        if document.extension == ".pdf":
            for source in document.original_paths:
                # Full source directory prevents pairing equal basenames from other albums.
                by_stem.setdefault(str(Path(source).with_suffix("")).casefold(), set()).add(
                    document.file_id
                )
    for document in documents:
        if document.extension == ".dwg":
            matches: set[str] = set()
            for source in document.original_paths:
                matches.update(by_stem.get(str(Path(source).with_suffix("")).casefold(), set()))
            document.paired_pdf_ids = sorted(matches)


def merge_aliases(document: Document, output: Path) -> Document:
    """A backup encountered first must not hide a DWG/PDF occurrence of the same bytes."""
    extensions = sorted({Path(p).suffix.lower() for p in document.original_paths})
    priority = (".pdf", ".dwg", ".dxf", ".xlsx", ".xls", ".csv", ".rvt", ".nwc", ".nwd", ".ifc")
    preferred = next((ext for ext in priority if ext in extensions), document.extension)
    if preferred != document.extension:
        source = next(p for p in document.original_paths if Path(p).suffix.lower() == preferred)
        refreshed = describe(
            document.file_id, output / document.stored_path, source, document.stored_path
        )
        refreshed.original_paths = document.original_paths
        document = refreshed
    document.extensions = extensions
    return document
