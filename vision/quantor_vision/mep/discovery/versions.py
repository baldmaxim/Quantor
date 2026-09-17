"""Conservative occurrence-level revision selection; never deletes old payloads."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import PurePosixPath

from .common import Document, stable
from .rules import classify, normalize, path_sources

REVISION = r"(?i)изм[.\s_-]*(\d+)"
DATE = r"(?<!\d)(\d{4}[._-]\d{2}[._-]\d{2}|\d{2}[._-]\d{2}[._-]\d{4})(?!\d)"


def version_date(text: str) -> str:
    dates = []
    for match in re.finditer(DATE, text):
        parts = re.split(r"[._-]", match.group())
        if len(parts[0]) != 4:
            parts.reverse()
        try:
            dates.append(date(*map(int, parts)).isoformat())
        except ValueError:
            continue
    return max(dates, default="")


def select_versions(documents: list[Document]) -> None:
    groups: dict[str, list[tuple[Document, dict[str, object], tuple[int, str]]]] = defaultdict(list)
    for doc in documents:
        doc.versions = []
        for path in doc.original_paths:
            c = classify(path_sources([path]))
            normalized = path.replace("\\", "/").replace("!", "/")
            basename = PurePosixPath(normalized).name
            name = normalize(re.sub(DATE, "", re.sub(REVISION, "", basename)))
            name = re.sub(r"[ _]+", " ", name).strip(" _-.")
            # Distinct sheet basenames stay distinct. Unknown project identities cannot merge.
            project = c["project_key"].value
            if project == "unknown":
                project = c["object_code"].value
            identity = [project, c["building"].value, c["stage"].value, c["discipline"].value, name]
            if project == "unknown":
                identity.append(normalized)
            set_id = stable(identity)
            revisions = [int(m.group(1)) for m in re.finditer(REVISION, normalized)]
            revision = max(revisions, default=0)
            dated = version_date(normalized)
            row: dict[str, object] = {
                "path": path,
                "set_id": set_id,
                "revision": revision,
                "date": dated,
                "status": "current",
                "evidence": normalized,
            }
            doc.versions.append(row)
            groups[set_id].append((doc, row, (revision, dated)))
    for members in groups.values():
        latest = max(rank for _, _, rank in members)
        winners = {d.file_id for d, _, rank in members if rank == latest}
        for _, row, rank in members:
            row["status"] = (
                "superseded" if rank < latest else ("review" if len(winners) > 1 else "current")
            )
            row["reason"] = "revision_then_date;equal_rank_distinct_payloads_require_review"
    for doc in documents:
        statuses = {str(v["status"]) for v in doc.versions}
        doc.revision_status = (
            "current"
            if "current" in statuses
            else ("review" if "review" in statuses else "superseded")
        )


def active_paths(document: Document) -> list[str]:
    return [
        str(v["path"]) for v in document.versions if v["status"] != "superseded"
    ] or document.original_paths
