"""D0 runner. All private artifacts stay under a new mep/ outside every git worktree."""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast

from quantor_vision.runrecord import source_state

from . import VERSION
from .archives import (
    Archive,
    Limits,
    extract_members,
    safe_name,
    seven_listing,
    validate,
    zip_listing,
)
from .common import (
    ARCHIVES,
    DiscoveryRefusedError,
    Document,
    Page,
    digest,
    outside_git,
    stable,
    write_json,
)
from .files import describe, link_cad_pdfs, merge_aliases
from .pairing import group_projects, pair_pages, pilot_candidates, unconfirmed_candidates
from .report import aggregate_report, private_report, summarize
from .rules import RULES_VERSION, classify, path_sources
from .versions import select_versions


def _pdf_worker(connection: Connection, path: Path, file_id: str, sources: list[str]) -> None:
    from .pdf_cache import cached_pdf

    try:
        connection.send(cached_pdf(path, file_id, sources))
    finally:
        connection.close()


def bounded_pdf(
    path: Path, file_id: str, sources: list[str], timeout: int
) -> tuple[list[Page], list[str]]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_pdf_worker, args=(sender, path, file_id, sources))
    process.start()
    sender.close()
    try:
        if receiver.poll(timeout):
            try:
                return cast(tuple[list[Page], list[str]], receiver.recv())
            except EOFError:
                return [], ["pdf_worker_failed"]
        return [], ["pdf_timeout"]
    finally:
        receiver.close()
        process.join(1)
        if process.is_alive():
            process.terminate()
            process.join()


class Discovery:
    def __init__(self, root: Path, output: Path, limits: Limits, encoding: str) -> None:
        self.root = root
        self.output = output
        self.limits = limits
        self.encoding = encoding
        self.archives: list[Archive] = []
        self.documents: dict[str, Document] = {}
        self.total_bytes = 0
        self.links: list[dict[str, str]] = []
        self.cache: dict[str, list[tuple[str, str, str]]] = {}

    def add(self, path: Path, source: str, destination: Path) -> str:
        sha = digest(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if sha in self.documents:
            document = self.documents[sha]
            if source not in document.original_paths:
                document.original_paths.append(source)
            if not destination.exists():
                os.link(self.output / document.stored_path, destination)
        else:
            if destination.exists():
                raise DiscoveryRefusedError("raw_path_collision")
            path.replace(destination)
            self.documents[sha] = describe(
                sha, destination, source, destination.relative_to(self.output).as_posix()
            )
        self.links.append(
            {
                "source": source,
                "file_id": sha,
                "raw_path": destination.relative_to(self.output).as_posix(),
            }
        )
        return sha

    def archive(self, path: Path, source: str, depth: int = 0) -> None:
        sha = digest(path)
        record = Archive(sha, source, depth)
        self.archives.append(record)
        try:
            record.members = (
                zip_listing(path, self.encoding)
                if path.suffix.lower() == ".zip"
                else seven_listing(path)
            )
            validate(record.members, path.stat().st_size, self.limits)
            if depth > self.limits.max_depth:
                raise DiscoveryRefusedError("nested_depth_limit")
            if sha in self.cache:
                for relative, stored, file_id in self.cache[sha]:
                    origin = source + "!/" + relative
                    document = self.documents[file_id]
                    if origin not in document.original_paths:
                        document.original_paths.append(origin)
                    self.links.append({"source": origin, "file_id": file_id, "raw_path": stored})
                record.status = "DEDUPLICATED"
            else:
                size = sum(m.size for m in record.members)
                if self.total_bytes + size > self.limits.max_total_bytes:
                    raise DiscoveryRefusedError("run_total_size_limit")
                self.total_bytes += size
                raw = self.output / "raw" / sha[:12]
                if raw.exists():
                    raise DiscoveryRefusedError("archive_hash_prefix_collision")
                entries: list[tuple[str, str, str]] = []
                with tempfile.TemporaryDirectory(dir=self.output / ".staging") as temporary:
                    staging = Path(temporary)
                    # Verify every payload/CRC before publishing any member of this archive.
                    extract_members(path, record.members, staging)
                    for i, member in enumerate(record.members):
                        relative = safe_name(member.path)
                        if member.directory:
                            (raw / relative).mkdir(parents=True, exist_ok=True)
                            continue
                        destination = raw / relative
                        file_id = self.add(staging / str(i), source + "!/" + relative, destination)
                        entries.append(
                            (relative, destination.relative_to(self.output).as_posix(), file_id)
                        )
                self.cache[sha] = entries
                record.status = "EXTRACTED"
            for relative, stored, _ in self.cache[sha]:
                if Path(relative).suffix.lower() in ARCHIVES:
                    self.archive(self.output / stored, source + "!/" + relative, depth + 1)
        except (
            DiscoveryRefusedError,
            OSError,
            ValueError,
            RuntimeError,
            zipfile.BadZipFile,
            NotImplementedError,
            TimeoutError,
        ) as error:
            record.status = "HOLD"
            record.reasons.append(
                str(error) if isinstance(error, DiscoveryRefusedError) else type(error).__name__
            )


def _jsonl(path: Path, records: list[object]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def discover(
    root: Path,
    dataset_root: Path,
    *,
    encoding: str = "cp866",
    limits: Limits | None = None,
    pdf_timeout: int = 600,
) -> dict[str, object]:
    limits = limits or Limits()
    root = root.resolve()
    output = outside_git(dataset_root / "mep")
    if not root.is_dir():
        raise DiscoveryRefusedError("archive_root_missing")
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise DiscoveryRefusedError("source_output_overlap")
    if output.exists():
        raise DiscoveryRefusedError("mep_output_already_exists_use_new_dataset_root")
    if encoding not in ("cp866", "cp1251"):
        raise DiscoveryRefusedError("unsupported_legacy_encoding")
    inputs: list[Path] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            entry = Path(directory) / name
            if entry.is_symlink() or entry.is_junction():
                raise DiscoveryRefusedError("source_link_or_junction")
        inputs.extend(Path(directory) / name for name in files)
    inputs.sort()
    snapshot = [
        {"path": p.relative_to(root).as_posix(), "sha256": digest(p), "size": p.stat().st_size}
        for p in inputs
    ]
    output.mkdir(parents=True)
    (output / ".staging").mkdir()
    inventory = output / "inventory"
    inventory.mkdir()
    write_json(inventory / "source_snapshot.json", snapshot)
    run = Discovery(root, output, limits, encoding)
    for index, path in enumerate(inputs, 1):
        source = path.relative_to(root).as_posix()
        if path.suffix.lower() in ARCHIVES:
            run.archive(path, source)
        else:
            # Loose input files are allowed, copied off-source before deduplication.
            from .common import copy_bounded

            with tempfile.TemporaryDirectory(dir=output / ".staging") as temporary:
                staged = Path(temporary) / "input"
                with path.open("rb") as stream:
                    copy_bounded(stream, staged, path.stat().st_size)
                run.add(staged, source, output / "raw" / "loose" / source)
        print(json.dumps({"phase": "archives", "done": index, "total": len(inputs)}), flush=True)
    documents = [merge_aliases(d, output) for d in run.documents.values()]
    pages: list[Page] = []
    pdfs = [d for d in documents if d.extension == ".pdf"]
    for index, document in enumerate(documents, 1):
        document.classification = classify(path_sources(document.original_paths))
        if document.extension == ".pdf":
            extracted, errors = bounded_pdf(
                output / document.stored_path,
                document.file_id,
                document.original_paths,
                pdf_timeout,
            )
            document.issues.extend(errors)
            pages.extend(extracted)
            # Document classification combines page evidence; conflicts stay unknown.
            sources = path_sources(document.original_paths)
            sources.extend(
                (e.source, e.line)
                for p in extracted
                for finding in p.classification.values()
                for e in finding.evidence
                if e.source in ("stamp", "title")
            )
            document.classification = classify(list(dict.fromkeys(sources)))
            print(
                json.dumps(
                    {
                        "phase": "pdf",
                        "done": sum(d.extension == ".pdf" for d in documents[:index]),
                        "total": len(pdfs),
                        "pages": len(pages),
                    }
                ),
                flush=True,
            )
    link_cad_pdfs(documents)
    select_versions(documents)
    by_id = {d.file_id: d for d in documents}
    for page in pages:
        page.revision_status = by_id[page.file_id].revision_status
    projects = group_projects(documents, pages)
    pairs = pair_pages(pages)
    pilots = pilot_candidates(pages, pairs)
    summary = summarize(run.archives, documents, pages, projects, pairs)
    _jsonl(inventory / "archives.jsonl", [asdict(a) for a in run.archives])
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
    _jsonl(inventory / "source_links.jsonl", list(run.links))
    write_json(inventory / "projects.json", [asdict(p) for p in projects])
    write_json(inventory / "pilot_candidates.json", pilots)
    write_json(inventory / "pilot_candidates_unconfirmed.json", unconfirmed_candidates(pages))
    write_json(inventory / "summary.json", summary)
    (inventory / "report.md").write_text(
        private_report(summary, run.archives, documents, pilots), encoding="utf-8"
    )
    (inventory / "aggregate_report.md").write_text(aggregate_report(summary), encoding="utf-8")
    after = [
        {"path": p.relative_to(root).as_posix(), "sha256": digest(p), "size": p.stat().st_size}
        for p in inputs
    ]
    if snapshot != after:
        raise DiscoveryRefusedError("source_changed_during_run")
    (output / ".staging").rmdir()
    # Hash each physical file once: hardlinks reference the same content digest.
    hashes = {link["raw_path"]: link["file_id"] for link in run.links}
    for path in inventory.iterdir():
        hashes[path.relative_to(output).as_posix()] = digest(path)
    for path in (output / ".pdf-cache").glob("*"):
        if path.is_file():
            hashes[path.relative_to(output).as_posix()] = digest(path)
    git_state = source_state(Path(__file__).resolve().parents[4])
    code_hashes = {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")}
    write_json(
        inventory / "manifest.json",
        {
            "tool_version": VERSION,
            "rules_version": RULES_VERSION,
            "pypdf_version": "6.18.0",
            "source_state": git_state,
            "tool_source_sha256": code_hashes,
            "source_root": str(root),
            "source_fingerprint": stable(snapshot),
            "source_unchanged": True,
            "created_at": datetime.now(UTC).isoformat(),
            "config": {
                "limits": asdict(limits),
                "legacy_encoding": encoding,
                "pdf_timeout": pdf_timeout,
            },
            "outputs": hashes,
            "manifest_self_hash": "excluded_to_avoid_self_reference",
            "status": "COMPLETE_WITH_HOLDS"
            if any(a.status == "HOLD" for a in run.archives)
            or any(d.extension == ".pdf" and d.issues for d in documents)
            else "COMPLETE",
        },
    )
    return summary
