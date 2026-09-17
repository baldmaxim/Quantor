"""Shared records, bounded I/O and output safety."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

FIELDS = (
    "project_key",
    "object_code",
    "stage",
    "discipline",
    "systems",
    "sheet_kind",
    "floor",
    "building",
    "section",
    "pd_section",
    "rd_marker",
    "fire_system",
)
ARCHIVES = {".zip", ".7z", ".rar"}


class DiscoveryRefusedError(ValueError):
    """A stable, non-sensitive refusal code."""


@dataclass
class Evidence:
    source: str
    line: str
    rule: str
    value: str


@dataclass
class Finding:
    value: str = "unknown"
    evidence: list[Evidence] = field(default_factory=list)
    reason: str | None = "no_evidence"


@dataclass
class Document:
    file_id: str
    original_paths: list[str]
    extension: str
    size: int
    stored_path: str
    kind: str
    classification: dict[str, Finding] = field(default_factory=dict)
    header_version: str | None = None
    workbook_sheets: list[str] = field(default_factory=list)
    boq_or_spec_candidate: bool = False
    issues: list[str] = field(default_factory=list)
    paired_pdf_ids: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    revision_status: str = "current"
    versions: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Page:
    page_id: str
    file_id: str
    page_number: int
    media_box_mm: list[float]
    crop_box_mm: list[float]
    rotation: int
    paper_format: str
    text_characters: int
    largest_image_fraction: float
    content_kind: str
    stamp_text: str | None
    classification: dict[str, Finding]
    text_sha256: str
    project_id: str | None = None
    issues: list[str] = field(default_factory=list)
    titles: str = ""
    revision_status: str = "current"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def outside_git(path: Path) -> Path:
    resolved = path.resolve()
    if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
        raise DiscoveryRefusedError("output_inside_git")
    for parent in (path.absolute(), *path.absolute().parents):
        if parent.is_symlink() or parent.is_junction():
            raise DiscoveryRefusedError("output_link_or_junction")
    return resolved


def copy_bounded(source: IO[bytes], destination: Path, limit: int) -> None:
    received = 0
    with destination.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            received += len(chunk)
            if received > limit:
                raise DiscoveryRefusedError("actual_size_exceeds_listing")
            output.write(chunk)
    if received != limit:
        raise DiscoveryRefusedError("actual_size_differs_from_listing")
