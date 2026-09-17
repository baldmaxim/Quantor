"""D0.1 refinement of an existing offline inventory, preserving its D0 snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import cast

from .archives import Archive
from .common import Document, Page, digest, outside_git, stable, write_json
from .pairing import group_projects, pair_pages, pilot_candidates, unconfirmed_candidates
from .pdf_cache import _restore
from .report import aggregate_report, private_report, summarize
from .rules import RULES_VERSION, classify, path_sources
from .run import _jsonl, bounded_pdf
from .versions import active_paths, select_versions


def records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def manual_samples(pages: list[Page], seed: int = 17092026) -> dict[str, object]:
    result: dict[str, object] = {
        "seed": seed,
        "sampling": "without_replacement;all_revisions",
        "title_scope": "text_lines_matching_title_rules;not_visual_titles",
    }
    for section in ("5.2", "5.3"):
        population = sorted(
            (
                p
                for p in pages
                if p.classification["pd_section"].value == section
                and p.classification["stage"].value == "P"
            ),
            key=lambda p: p.page_id,
        )
        chosen = sorted(population, key=lambda p: stable([seed, section, p.page_id]))[:50]
        result[section] = {
            "eligible_pages": len(population),
            "sample_size": len(chosen),
            "shortfall": max(0, 50 - len(chosen)),
            "pages": [
                {
                    "page_id": p.page_id,
                    "file_id": p.file_id,
                    "page_number": p.page_number,
                    "titles": p.titles,
                    "stamp_text": p.stamp_text,
                    "issues": p.issues,
                    "revision_status": p.revision_status,
                }
                for p in chosen
            ],
        }
    return result


def refresh_manifest(root: Path) -> None:
    inventory = root / "inventory"
    manifest = json.loads((inventory / "manifest.json").read_text(encoding="utf-8"))
    manifest["refinement_rules_version"] = RULES_VERSION
    manifest["refinement_tool_source_sha256"] = {
        p.name: digest(p) for p in Path(__file__).parent.glob("*.py")
    }
    for folder in (inventory, root / ".pdf-cache"):
        for path in folder.rglob("*"):
            if path.is_file() and path != inventory / "manifest.json":
                manifest["outputs"][path.relative_to(root).as_posix()] = digest(path)
    write_json(inventory / "manifest.json", manifest)


def refine(root: Path, workers: int = 6, reuse_text: bool = False) -> dict[str, object]:
    root = outside_git(root)
    inventory = root / "inventory"
    backup = inventory / "d0-before-refinement"
    if not backup.exists():
        backup.mkdir()
        for path in inventory.iterdir():
            if path.is_file() and path.suffix in (".json", ".jsonl", ".md"):
                shutil.copy2(path, backup / path.name)
    documents = []
    for row in records(backup / "files.jsonl"):
        doc = Document(
            file_id=str(row["file_id"]),
            original_paths=cast(list[str], row["original_paths"]),
            extension=str(row["extension"]),
            size=cast(int, row["size"]),
            stored_path=str(row["stored_path"]),
            kind=str(row["kind"]),
            header_version=cast(str | None, row["header_version"]),
            workbook_sheets=cast(list[str], row["workbook_sheets"]),
            boq_or_spec_candidate=bool(row["boq_or_spec_candidate"]),
            issues=cast(list[str], row["issues"]),
            paired_pdf_ids=cast(list[str], row["paired_pdf_ids"]),
            extensions=cast(list[str], row.get("extensions", [])),
        )
        documents.append(doc)
    select_versions(documents)
    pages: list[Page] = []
    pdfs = [d for d in documents if d.extension == ".pdf"]
    saved: dict[str, list[dict[str, object]]] = {}
    if reuse_text:
        for row in records(inventory / "pages.jsonl"):
            if "titles" not in row:
                raise ValueError("incomplete_title_cache_requires_pdf_read")
            saved.setdefault(str(row["file_id"]), []).append(row)

    def restore_document(doc: Document) -> tuple[list[Page], list[str]]:
        return (
            [_restore(row, active_paths(doc)) for row in saved.get(doc.file_id, [])],
            doc.issues,
        )

    for doc in documents:
        doc.classification = classify(path_sources(active_paths(doc)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = (
            {pool.submit(restore_document, d): d for d in pdfs}
            if reuse_text
            else {
                pool.submit(bounded_pdf, root / d.stored_path, d.file_id, active_paths(d), 600): d
                for d in pdfs
            }
        )
        for count, future in enumerate(as_completed(pending), 1):
            doc = pending[future]
            extracted, doc.issues = future.result()
            sources = path_sources(active_paths(doc))
            for page in extracted:
                page.revision_status = doc.revision_status
                sources.extend((("stamp", page.stamp_text or ""), ("title", page.titles)))
            doc.classification = classify(sources)
            pages.extend(extracted)
            if count % 10 == 0 or doc.issues:
                print(
                    json.dumps({"pdfs_complete": count, "total": len(pdfs), "issues": doc.issues}),
                    flush=True,
                )
    pages.sort(key=lambda p: (p.file_id, p.page_number))
    old_count = len(records(backup / "pages.jsonl"))
    if len(pages) < old_count:
        raise ValueError("refinement_page_count_regression;retry_completed_cache")
    archives = []
    for row in records(backup / "archives.jsonl"):
        archives.append(
            Archive(
                str(row["sha256"]),
                str(row["source"]),
                cast(int, row["depth"]),
                str(row["status"]),
                cast(list[str], row["reasons"]),
            )
        )
    projects = group_projects(documents, pages)
    pairs = pair_pages(pages)
    pilots = pilot_candidates(pages, pairs)
    unconfirmed = unconfirmed_candidates(pages)
    by_id = {d.file_id: d for d in documents}
    for prefix, candidates in (("P", pilots), ("U", unconfirmed)):
        for index, candidate in enumerate(candidates, 1):
            doc = by_id[str(candidate["file_id"])]
            candidate.update(
                candidate_id=f"{prefix}{index:02}",
                stored_path=doc.stored_path,
                original_paths=active_paths(doc),
            )
    summary = summarize(archives, documents, pages, projects, pairs)
    summary["pilot_candidates"] = len(pilots)
    summary["unconfirmed_candidates"] = len(unconfirmed)
    summary["section_unknown_reasons"] = dict(
        Counter(p.classification["section"].reason or "known" for p in pages)
    )
    samples = manual_samples(pages)
    summary["manual_sample_sizes"] = {
        s: cast(dict[str, object], samples[s])["sample_size"] for s in ("5.2", "5.3")
    }
    _jsonl(inventory / "files.jsonl", [asdict(d) for d in documents])
    _jsonl(
        inventory / "pages.jsonl",
        [
            asdict(p)
            | {
                "page_sha256": stable(
                    {"source_pdf_sha256": p.file_id, "page_number": p.page_number}
                ),
                "page_hash_basis": "source_pdf_sha256_and_one_based_page_number",
            }
            for p in pages
        ],
    )
    _jsonl(inventory / "pairs.jsonl", [asdict(p) for p in pairs])
    for name, value in (
        ("summary", summary),
        ("projects", [asdict(p) for p in projects]),
        ("pilot_candidates", pilots),
        ("pilot_candidates_unconfirmed", unconfirmed),
        ("manual_sample_pd_sections", samples),
    ):
        write_json(inventory / (name + ".json"), value)
    notes = (
        "\n## D0.1 limitations\n\n"
        "Project grouping now uses the drawing-code prefix; buildings do not define projects. "
        "The old project_key rule required an explicit Project/Object label. Section "
        "remains unknown "
        "when no explicit section label exists in the extracted text or paths; a "
        "building is not a section.\n\n"
        "Revision selection uses revision number, then date, within the same "
        "project/building/stage/discipline "
        "and normalized filename. Equal-ranked different payloads require review. "
        "Different sheet names are "
        "not assumed to be versions of the same set. Superseded payloads remain stored "
        "and counted in total "
        "inventory, but are excluded from pairs and pilots.\n\n"
        "Issue counts overlap: custom clipping means image area is an upper bound; "
        "stamp_not_located "
        "does not mean the PDF is unreadable. Extraction/inspection failures and blank "
        "pages are separate.\n\n"
        "Manual samples contain up to 50 randomly selected pages per requested PD "
        "section, with a fixed seed. "
        "They contain candidate title lines and stamp text only; null stamps remain null. "
        "Unconfirmed pilot candidates require manual verification and do not change "
        "observed classifications.\n\n"
        "R-MEP-3 additional objects: owner decision pending. STOP after D0.1.\n"
    )
    (inventory / "aggregate_report.md").write_text(
        aggregate_report(summary) + notes, encoding="utf-8"
    )
    (inventory / "report.md").write_text(
        private_report(summary, archives, documents, pilots) + notes, encoding="utf-8"
    )
    refresh_manifest(root)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--reuse-text", action="store_true")
    args = parser.parse_args()
    result = refine(args.dataset_root / "mep", args.workers, args.reuse_text)
    print(
        json.dumps(
            {
                "status": "COMPLETE_WITH_HOLDS",
                "pages": result["pdf_pages"],
                "pilots": result["pilot_candidates"],
            }
        )
    )
