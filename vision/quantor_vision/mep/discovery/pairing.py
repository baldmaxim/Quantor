"""Project grouping and conservative P/RD candidates, with no geometry alignment."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .common import Document, Page, stable
from .rules import normalize


@dataclass
class Project:
    project_id: str
    key: str
    basis: str
    page_ids: list[str] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)


@dataclass
class Pair:
    project_id: str
    p_page_id: str
    rd_page_id: str | None
    pair_status: str
    matched: list[str]
    missing: list[str]
    reasons: list[str]
    cardinality: str = "1:1"
    rd_buildings: list[str] = field(default_factory=list)


def group_projects(documents: list[Document], pages: list[Page]) -> list[Project]:
    projects: dict[str, Project] = {}
    items: list[Document | Page] = [*documents, *pages]
    for item in items:
        if isinstance(item, Page):
            item.project_id = None
        c = item.classification
        if c["project_key"].reason == "conflicting_evidence":
            continue
        code, key = c["object_code"].value, c["project_key"].value
        if key != "unknown" and any(
            e.rule in ("project.cipher_prefix", "project.object_prefix")
            for e in c["project_key"].evidence
        ):
            basis, value = "cipher_prefix", normalize(key)
        elif code != "unknown":
            basis, value = "object_code", normalize(code)
        elif key != "unknown" and c["object_code"].reason != "conflicting_evidence":
            basis, value = "explicit_project_name", normalize(key)
        else:
            continue
        project_id = stable([basis, value])
        project = projects.setdefault(project_id, Project(project_id, value, basis))
        if isinstance(item, Page):
            item.project_id = project_id
            project.page_ids.append(item.page_id)
        if item.file_id not in project.file_ids:
            project.file_ids.append(item.file_id)
    return list(projects.values())


def pair_pages(pages: list[Page]) -> list[Pair]:
    by_project: dict[str, list[Page]] = defaultdict(list)
    for page in pages:
        if page.project_id and page.revision_status != "superseded":
            by_project[page.project_id].append(page)
    result: list[Pair] = []
    fields = ("object_code", "discipline", "systems", "floor", "building", "section", "sheet_kind")
    for project_id, group in by_project.items():
        plans = [
            p
            for p in group
            if p.classification["discipline"].value == "VK"
            and p.classification["sheet_kind"].value == "floor_plan"
        ]
        for p in plans:
            if p.classification["stage"].value != "P":
                continue
            candidates: list[Pair] = []
            for rd in plans:
                if rd.classification["stage"].value != "RD":
                    continue
                matched, missing, incompatible = [], [], False
                for name in fields:
                    a, b = p.classification[name].value, rd.classification[name].value
                    if "unknown" in (a, b):
                        missing.append(name)
                    elif a == b:
                        matched.append(name)
                    elif (
                        name == "object_code"
                        and p.classification["project_key"].value
                        == rd.classification["project_key"].value
                        != "unknown"
                    ):
                        missing.append("same_object_code")
                    else:
                        incompatible = True
                if incompatible:
                    continue
                if "review" in (p.revision_status, rd.revision_status):
                    missing.append("revision_confirmation")
                required = {"object_code", "discipline", "systems", "floor", "building", "section"}
                status = "AUTO_OK" if required <= set(matched) and not missing else "REVIEW"
                candidates.append(
                    Pair(project_id, p.page_id, rd.page_id, status, matched, missing, [])
                )
            if len(candidates) > 1:
                by_id = {page.page_id: page for page in group}
                buildings = [
                    by_id[str(pair.rd_page_id)].classification["building"].value
                    for pair in candidates
                ]
                one_to_many = "unknown" not in buildings and len(set(buildings)) == len(buildings)
                for pair in candidates:
                    pair.pair_status = "REVIEW" if one_to_many else "HOLD"
                    pair.reasons.append(
                        "one_to_many_buildings" if one_to_many else "multiple_rd_candidates"
                    )
                    if one_to_many:
                        pair.cardinality = "1:N"
                        pair.rd_buildings = sorted(set(buildings))
                        pair.reasons.extend("rd_page:" + str(c.rd_page_id) for c in candidates)
            if not candidates:
                candidates.append(
                    Pair(project_id, p.page_id, None, "HOLD", [], [], ["no_compatible_rd_page"])
                )
            result.extend(candidates)
    rd_uses: dict[str, list[Pair]] = defaultdict(list)
    for pair in result:
        if pair.rd_page_id:
            rd_uses[pair.rd_page_id].append(pair)
    for uses in rd_uses.values():
        if len(uses) > 1:
            for pair in uses:
                pair.pair_status = "HOLD"
                pair.reasons.append("multiple_p_candidates")
    return result


def pilot_candidates(pages: list[Page], pairs: list[Pair]) -> list[dict[str, object]]:
    auto = {pair.p_page_id for pair in pairs if pair.pair_status == "AUTO_OK"}
    selected = [
        p
        for p in pages
        if p.classification["stage"].value == "P"
        and p.classification["discipline"].value == "VK"
        and p.classification["sheet_kind"].value == "floor_plan"
        and p.revision_status != "superseded"
    ]
    selected.sort(
        key=lambda p: (
            -(p.content_kind == "vector" and p.text_characters > 0),
            -(p.page_id in auto),
            -(p.classification["floor"].value == "типовой"),
            -bool(p.stamp_text),
            p.page_id,
        )
    )
    result: list[dict[str, object]] = []
    for page in selected[:10]:
        reasons = ["stage_P", "discipline_VK", "floor_plan"]
        missing = [k for k, v in page.classification.items() if v.value == "unknown"]
        if page.revision_status == "review":
            missing.append("revision_confirmation")
        if page.content_kind == "vector" and page.text_characters:
            reasons.append("vector_with_text")
        if page.page_id in auto:
            reasons.append("AUTO_OK_pair")
        else:
            missing.append("confirmed_RD_pair")
        if page.classification["floor"].value == "типовой":
            reasons.append("typical_floor")
        if page.stamp_text:
            reasons.append("stamp_text_available_readability_not_verified")
        else:
            missing.append("located_stamp")
        result.append(
            {
                "page_id": page.page_id,
                "file_id": page.file_id,
                "page_number": page.page_number,
                "reasons": reasons,
                "missing": missing,
                "floor": page.classification["floor"].value,
                "systems": page.classification["systems"].value,
                "status": "confirmed_by_rules",
            }
        )
    return result


def unconfirmed_candidates(pages: list[Page]) -> list[dict[str, object]]:
    """Near matches for human inspection; never become confirmed pilot inputs."""
    eligible = [
        p
        for p in pages
        if p.revision_status != "superseded"
        and p.classification["discipline"].value == "VK"
        and p.classification["stage"].value in ("P", "unknown")
        and p.classification["sheet_kind"].value in ("floor_plan", "unknown")
        and any(p.classification[k].value == "unknown" for k in ("stage", "sheet_kind"))
    ]
    eligible.sort(
        key=lambda p: (
            -(p.classification["sheet_kind"].value == "floor_plan"),
            -(p.classification["stage"].value == "P"),
            -(p.content_kind == "vector" and p.text_characters > 0),
            -(p.classification["floor"].value != "unknown"),
            -(p.classification["systems"].value != "unknown"),
            p.page_id,
        )
    )
    return [
        {
            "status": "unconfirmed",
            "page_id": p.page_id,
            "file_id": p.file_id,
            "page_number": p.page_number,
            "floor": p.classification["floor"].value,
            "systems": p.classification["systems"].value,
            "missing": [k for k, v in p.classification.items() if v.value == "unknown"],
            "reasons": ["VK_evidence", "requires_manual_stage_or_plan_confirmation"],
        }
        for p in eligible[:10]
    ]
