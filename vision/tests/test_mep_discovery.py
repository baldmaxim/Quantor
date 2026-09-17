"""D0 security and provenance tests: all inputs are synthetic, generated in tmp_path."""

from __future__ import annotations

import io
import json
import re
import stat
import struct
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    RectangleObject,
)

from quantor_vision.mep.discovery.archives import (
    Limits,
    Member,
    decode_name,
    extract_member,
    safe_name,
    validate,
    zip_listing,
)
from quantor_vision.mep.discovery.common import (
    DiscoveryRefusedError,
    Document,
    Finding,
    Page,
    digest,
)
from quantor_vision.mep.discovery.files import describe, merge_aliases
from quantor_vision.mep.discovery.pairing import group_projects, pair_pages, unconfirmed_candidates
from quantor_vision.mep.discovery.pdf import _fraction, inspect_pdf
from quantor_vision.mep.discovery.rules import RULES, Rule, classify, normalize, path_sources
from quantor_vision.mep.discovery.run import discover
from quantor_vision.mep.discovery.versions import select_versions


def pdf_bytes(*, text: bool = False, image: bool = False, form: bool = False) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=595.276, height=841.89)
    resources = DictionaryObject()
    content = b""
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
        content += b"BT /F1 12 Tf 20 40 Td (Synthetic hello) Tj ET\n"
    if image:
        raster = DecodedStreamObject()
        raster.set_data(b"\x00")
        raster.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Im"): raster})
        content += b"q 595.276 0 0 841.89 0 0 cm /Im Do Q\n"
    stream = DecodedStreamObject()
    stream.set_data(content)
    if form:
        stream.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): RectangleObject([0, 0, 596, 842]),
                NameObject("/Resources"): resources,
            }
        )
        resources = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Fm"): stream})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"/Fm Do")
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_id)
def test_rule_example(rule: Rule) -> None:
    match = re.search(rule.pattern, rule.example, re.IGNORECASE)
    assert match is not None
    value = rule.value if rule.value is not None else normalize(match.group(1))
    assert value == rule.expected


@pytest.mark.parametrize(
    "name",
    [
        "../bad",
        "/bad",
        "C:/bad",
        "C:bad",
        "\\\\host\\bad",
        "a/../../bad",
        "a:stream",
        "NUL.txt",
        "a. ",
        "x/./y",
        "a\x00bad",
        "a//b",
    ],
)
def test_unsafe_names(name: str) -> None:
    with pytest.raises(DiscoveryRefusedError):
        safe_name(name)


@pytest.mark.parametrize("encoding", ["cp866", "cp1251"])
def test_legacy_bytes_preserved(encoding: str) -> None:
    original = "Синтетический план.pdf"
    raw = original.encode(encoding)
    info = zipfile.ZipInfo(raw.decode("cp437"))
    name, byte_hex, codec = decode_name(info, encoding)
    assert (name, byte_hex, codec) == (original, raw.hex(), encoding)


def test_unicode_extra_does_not_break_member_lookup(tmp_path: Path) -> None:
    import zlib

    path = tmp_path / "unicode-extra.zip"
    info = zipfile.ZipInfo("synthetic.txt")
    unicode_data = struct.pack("<BL", 1, zlib.crc32(b"synthetic.txt")) + "План.txt".encode()
    info.extra = struct.pack("<HH", 0x7075, len(unicode_data)) + unicode_data
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, b"synthetic payload")
    members = zip_listing(path, "cp866")
    assert members[0].path == "План.txt"
    assert members[0].encoding == "zip_unicode_extra"
    destination = tmp_path / "extracted"
    extract_member(path, members[0], destination)
    assert destination.read_bytes() == b"synthetic payload"


def test_conflicts_and_missing() -> None:
    c = classify([("stamp", "Стадия Р"), ("directory", "PD")])
    assert c["stage"].value == "unknown"
    assert c["stage"].reason == "conflicting_evidence"
    assert {e.value for e in c["stage"].evidence} == {"P", "RD"}
    assert c["floor"].reason == "no_evidence"
    assert classify([("title", "В1 К1")])["systems"].value == "В1,К1"
    # A filename's building token is not a system observation.
    assert classify([("title", "В1"), ("filename", "К1")])["systems"].value == "В1"


def test_archive_link_encryption_ratio_and_collisions(tmp_path: Path) -> None:
    path = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, "../outside")
    with pytest.raises(DiscoveryRefusedError, match="link_or_special"):
        validate(zip_listing(path, "cp866"), path.stat().st_size, Limits())
    member = Member("a", 10, 10, None, False, False, False, None, "ascii", "a")
    for changed, reason in (
        (replace(member, encrypted=True), "encrypted"),
        (replace(member, size=10000, compressed_size=1), "ratio"),
    ):
        with pytest.raises(DiscoveryRefusedError, match=reason):
            validate([changed], 10000, Limits())
    with pytest.raises(DiscoveryRefusedError, match="colliding"):
        validate([member, replace(member, path="A")], 100, Limits())
    with pytest.raises(DiscoveryRefusedError, match="directory_collision"):
        validate([member, replace(member, path="a/b")], 100, Limits())


@pytest.mark.parametrize(
    ("text", "image", "form", "kind"),
    [
        (True, False, False, "vector"),
        (False, True, False, "raster_scan"),
        (True, True, False, "mixed"),
        (False, True, True, "raster_scan"),
        (False, False, False, "vector"),
    ],
)
def test_pdf_channels(tmp_path: Path, text: bool, image: bool, form: bool, kind: str) -> None:
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(pdf_bytes(text=text, image=image, form=form))
    pages, errors = inspect_pdf(path, digest(path), ["PD/ВК/План 3 этажа.pdf"])
    assert not errors
    page = pages[0]
    assert page.content_kind == kind
    assert page.paper_format == "A4"
    assert bool(page.text_characters) is text
    assert page.stamp_text is None
    assert page.classification["stage"].value == "P"
    assert page.classification["floor"].value == "3"
    assert page.largest_image_fraction == (1 if image else 0)


def test_image_is_clipped_to_page() -> None:
    assert _fraction((100, 0, 0, 100, 50, 0), RectangleObject([0, 0, 100, 100])) == 0.5


def _page(identifier: str, project: str, stage: str) -> Page:
    c = classify(
        [("stamp", f"Код объекта: {project}\n{stage}\nВК\nВ1\nПлан 3 этажа\nКорпус 2\nСекция 1")]
    )
    return Page(
        identifier,
        identifier,
        1,
        [0, 0, 210, 297],
        [0, 0, 210, 297],
        0,
        "A4",
        30,
        0,
        "vector",
        "synthetic",
        c,
        "0" * 64,
    )


def test_pairing_project_isolation_and_ambiguity() -> None:
    p, rd, other = (
        _page("p", "SYN-001", "П"),
        _page("r", "SYN-001", "РД"),
        _page("o", "SYN-002", "РД"),
    )
    group_projects([], [p, rd, other])
    pairs = pair_pages([p, rd, other])
    assert len(pairs) == 1 and pairs[0].pair_status == "AUTO_OK"
    duplicate = _page("r2", "SYN-001", "РД")
    group_projects([], [duplicate])
    assert all(p.pair_status == "HOLD" for p in pair_pages([p, rd, duplicate]))


@pytest.mark.parametrize(
    "section,discipline",
    [("5.1", "EOM"), ("5.2", "VK"), ("5.3", "VK"), ("5.4", "OV"), ("5.5", "SS")],
)
def test_pd_section_mapping(section: str, discipline: str) -> None:
    c = classify(path_sources([f"input.zip!PD/{section}/album.pdf"]))
    assert c["stage"].value == "P"
    assert c["discipline"].value == discipline
    assert c["pd_section"].value == section
    assert any(e.rule == "stage.archive_p" for e in c["stage"].evidence)
    assert classify(path_sources([f"RD/{section}/album.pdf"]))["pd_section"].value == "unknown"


def test_cipher_project_building_and_fire_are_separate() -> None:
    assert classify([("stamp", "Код объекта: 42АБ")])["project_key"].value == "42АБ"
    c = classify(path_sources(["RD/42АБ-К3-РД-АПТ.pdf"]))
    assert (c["project_key"].value, c["building"].value) == ("42АБ", "К3")
    assert c["rd_marker"].value == "АПТ" and c["fire_system"].value == "yes"
    assert c["discipline"].value == "FIRE"
    assert c["systems"].value == "unknown"
    assert c["section"].value == "unknown"
    assert classify(path_sources(["RD/42АБ-К3-РД-ППТ/plan.pdf"]))["fire_system"].value == "yes"
    c = classify([("stamp", "42АБ-К3-РД-ВК\nВ1")])
    assert c["systems"].value == "В1"
    page = _page("conflict", "SYN-001", "П")
    page.project_id = "stale"
    page.classification["project_key"] = Finding(reason="conflicting_evidence")
    assert group_projects([], [page]) == []
    assert page.project_id is None


def test_one_to_many_buildings_review_and_same_building_hold() -> None:
    p, a, b = _page("p", "SYN-001", "П"), _page("a", "SYN-001", "РД"), _page("b", "SYN-001", "РД")
    p.classification["building"] = Finding()
    b.classification["building"] = Finding("К3")
    group_projects([], [p, a, b])
    result = pair_pages([p, a, b])
    assert len(result) == 2 and all(r.pair_status == "REVIEW" for r in result)
    assert all("one_to_many_buildings" in r.reasons for r in result)
    assert all(r.cardinality == "1:N" and r.rd_buildings == ["К2", "К3"] for r in result)
    b.classification["building"] = a.classification["building"]
    assert all(r.pair_status == "HOLD" for r in pair_pages([p, a, b]))
    b.revision_status = "superseded"
    assert len(pair_pages([p, a, b])) == 1


def test_versions_preserve_old_content_and_ties() -> None:
    def doc(identifier: str, folder: str, name: str = "42АБ-К3-РД-ВК.pdf") -> Document:
        return Document(identifier, [f"RD/{folder}/{name}"], ".pdf", 1, identifier, "pdf")

    old, new, tie, other = (
        doc("old", "Изм.1/2024-01-01"),
        doc("new", "Изм.2/2024-02-01"),
        doc("tie", "Изм.2/2024-02-01"),
        doc("other", "Изм.1", "42АБ-К4-РД-ВК.pdf"),
    )
    select_versions([old, new, tie, other])
    assert old.revision_status == "superseded" and old.original_paths
    assert new.revision_status == tie.revision_status == "review"
    assert other.revision_status == "current"


def test_unconfirmed_does_not_promote_unknown_and_samples_are_reproducible() -> None:
    from quantor_vision.mep.discovery.refine import manual_samples

    p = _page("p", "SYN-001", "П")
    p.classification["sheet_kind"] = Finding()
    p.classification["pd_section"] = Finding("5.2")
    candidates = unconfirmed_candidates([p])
    assert candidates[0]["status"] == "unconfirmed"
    assert p.classification["sheet_kind"].value == "unknown"
    pages = [replace(p, page_id=str(n)) for n in range(70)]
    sample = manual_samples(pages)
    assert sample == manual_samples(list(reversed(pages)))
    assert isinstance(sample["5.2"], dict) and sample["5.2"]["sample_size"] == 50
    assert isinstance(sample["5.3"], dict) and sample["5.3"]["shortfall"] == 50


def test_headers_and_workbook_metadata(tmp_path: Path) -> None:
    dwg = tmp_path / "header.dwg"
    dwg.write_bytes(b"AC1032")
    doc = describe(digest(dwg), dwg, dwg.name, dwg.name)
    assert doc.header_version == "AC1032"
    dxf = tmp_path / "header.dxf"
    dxf.write_bytes(b"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1027\n")
    assert describe(digest(dxf), dxf, dxf.name, dxf.name).header_version == "AC1027"
    book = tmp_path / "book.xlsx"
    with zipfile.ZipFile(book, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="urn:synthetic"><sheets><sheet name="ВОР"/></sheets></workbook>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", "NOT XML: MUST NOT BE READ")
    doc = describe(digest(book), book, book.name, book.name)
    assert doc.workbook_sheets == ["ВОР"] and doc.boq_or_spec_candidate


def test_backup_alias_does_not_hide_dwg(tmp_path: Path) -> None:
    path = tmp_path / "first.bak"
    path.write_bytes(b"AC1032")
    document = describe(digest(path), path, "first.bak", "first.bak")
    document.original_paths.append("second.dwg")
    document = merge_aliases(document, tmp_path)
    assert document.extensions == [".bak", ".dwg"]
    assert document.extension == ".dwg" and document.header_version == "AC1032"


def test_end_to_end_nested_dedup_manifest_and_source_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("copy.dwg", b"AC1032")
    with zipfile.ZipFile(root / "small.zip", "w") as archive:
        archive.writestr("PD/ВК/План 3 этажа.pdf", pdf_bytes(text=True))
        archive.writestr("same.dwg", b"AC1032")
        archive.writestr("nested.zip", nested.getvalue())
    before = digest(root / "small.zip")
    result = discover(root, tmp_path / "dataset")
    assert result["unique_files"] == 3
    assert result["file_occurrences"] == 4
    assert digest(root / "small.zip") == before
    output = tmp_path / "dataset" / "mep"
    manifest = json.loads((output / "inventory/manifest.json").read_text(encoding="utf-8"))
    for name, sha in manifest["outputs"].items():
        assert digest(output / name) == sha
    with pytest.raises(DiscoveryRefusedError, match="already_exists"):
        discover(root, tmp_path / "dataset")


def test_hostile_archive_holds_without_extracting(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    with zipfile.ZipFile(root / "bad.zip", "w") as archive:
        archive.writestr("../escape", "bad")
        archive.writestr("good", "must not extract")
    result = discover(root, tmp_path / "dataset")
    assert result["archives_status"] == {"HOLD": 1}
    assert result["unique_files"] == 0
    assert not (tmp_path / "escape").exists()


def test_output_git_and_overlap_refused(tmp_path: Path) -> None:
    source, repo = tmp_path / "source", tmp_path / "repo"
    source.mkdir()
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /synthetic", encoding="utf-8")
    with pytest.raises(DiscoveryRefusedError, match="inside_git"):
        discover(source, repo / "dataset")
    with pytest.raises(DiscoveryRefusedError, match="overlap"):
        discover(source, source / "dataset")


def test_depth_limit_and_missing_seven_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "source"
    root.mkdir()
    payload = b"synthetic"
    for depth in range(4):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("next.zip" if depth else "leaf.txt", payload)
        payload = output.getvalue()
    (root / "nested.zip").write_bytes(payload)
    (root / "unavailable.7z").write_bytes(b"synthetic")
    monkeypatch.setattr("quantor_vision.mep.discovery.archives.shutil.which", lambda _: None)
    result = discover(root, tmp_path / "dataset")
    assert result["archives_hold_reasons"] == {
        "nested_depth_limit": 1,
        "seven_zip_unavailable": 1,
    }
    assert not list((tmp_path / "dataset").rglob("leaf.txt"))


def test_crc_failure_publishes_no_partial_archive(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("first.txt", b"good")
        archive.writestr("second.txt", b"ORIGINAL")
    (root / "crc.zip").write_bytes(output.getvalue().replace(b"ORIGINAL", b"CORRUPT!"))
    result = discover(root, tmp_path / "dataset")
    assert result["archives_status"] == {"HOLD": 1}
    assert result["unique_files"] == 0
    assert not list((tmp_path / "dataset").rglob("first.txt"))


def test_pdf_crop_rotation_user_unit_and_encryption(tmp_path: Path) -> None:
    from pypdf import PdfReader

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_bytes(text=True))))
    page = writer.pages[0]
    page.cropbox = RectangleObject([10, 20, 500, 800])
    page[NameObject("/UserUnit")] = NumberObject(2)
    page.rotate(90)
    path = tmp_path / "geometry.pdf"
    writer.write(path)
    pages, errors = inspect_pdf(path, digest(path), [])
    assert not errors and pages[0].rotation == 90
    assert pages[0].crop_box_mm[0] == pytest.approx(10 * 2 * 25.4 / 72, abs=0.001)
    writer.encrypt("synthetic-only")
    writer.write(path)
    assert inspect_pdf(path, digest(path), [])[1] == ["encrypted_pdf"]


def test_xml_entities_are_not_read(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///secret">]>'
            '<workbook><sheet name="&x;"/></workbook>',
        )
    document = describe(digest(path), path, path.name, path.name)
    assert not document.workbook_sheets
    assert document.issues == ["workbook_metadata_unavailable:ValueError"]


def test_cache_reclassifies_occurrence_paths(tmp_path: Path) -> None:
    from quantor_vision.mep.discovery.pdf_cache import cached_pdf

    output = tmp_path / "mep"
    (output / "inventory").mkdir(parents=True)
    (output / "inventory/source_snapshot.json").write_text("[]", encoding="utf-8")
    (output / "raw/hash").mkdir(parents=True)
    path = output / "raw/hash/synthetic.pdf"
    path.write_bytes(pdf_bytes(text=True))
    first, errors = cached_pdf(path, digest(path), ["PD/ВК/План 3 этажа.pdf"])
    assert not errors and first[0].classification["stage"].value == "P"
    second, errors = cached_pdf(path, digest(path), ["RD/ВК/План 3 этажа.pdf"])
    assert not errors and second[0].classification["stage"].value == "RD"
    assert second[0].text_sha256 == first[0].text_sha256


def test_interrupted_pdf_resumes_after_finished_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pypdf import PdfReader

    from quantor_vision.mep.discovery import pdf_cache

    output = tmp_path / "mep"
    (output / "inventory").mkdir(parents=True)
    (output / "inventory/source_snapshot.json").write_text("[]", encoding="utf-8")
    (output / "raw/hash").mkdir(parents=True)
    path = output / "raw/hash/synthetic.pdf"
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_bytes(text=True))))
    writer.append(PdfReader(io.BytesIO(pdf_bytes(image=True))))
    writer.write(path)

    def interrupted(
        path: Path,
        file_id: str,
        paths: list[str],
        *,
        start_page: int = 1,
        on_page: Callable[[Page], None] | None = None,
    ) -> tuple[list[Page], list[str]]:
        def save_and_interrupt(page: Page) -> None:
            if on_page:
                on_page(page)
            raise KeyboardInterrupt

        return inspect_pdf(path, file_id, paths, start_page=start_page, on_page=save_and_interrupt)

    monkeypatch.setattr(pdf_cache, "inspect_pdf", interrupted)
    with pytest.raises(KeyboardInterrupt):
        pdf_cache.cached_pdf(path, digest(path), [])
    monkeypatch.setattr(pdf_cache, "inspect_pdf", inspect_pdf)
    pages, errors = pdf_cache.cached_pdf(path, digest(path), [])
    assert not errors and [p.page_number for p in pages] == [1, 2]
    assert pages[0].text_characters > 0 and pages[1].content_kind == "raster_scan"


def test_path_filter_preserves_pdf_strings_and_falls_back() -> None:
    from quantor_vision.mep.discovery.content import without_path_coordinates

    source = b"1 2 m 3 4 l S BT (1 2 m (nested) \\(escaped\\)) Tj ET <312032206d>\n% 1 2 m\n"
    filtered = without_path_coordinates(source)
    assert filtered == b"  S BT (1 2 m (nested) \\(escaped\\)) Tj ET <312032206d>\n% 1 2 m\n"
    for source in (b"1 2 m BI /W 1 ID pixels EI", b"1 2 m << /A 1 >>", b"1 2 m (broken"):
        assert without_path_coordinates(source) == source


def test_path_filter_keeps_text_and_image_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pypdf import PdfReader

    from quantor_vision.mep.discovery import pdf

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_bytes(text=True, image=True))))
    page = writer.pages[0]
    original = page.get_contents()
    assert original is not None
    stream = DecodedStreamObject()
    stream.set_data(b"1 2 m 3 4 l 5 6 7 8 9 10 c S\n" * 1000 + original.get_data())
    page[NameObject("/Contents")] = stream
    path = tmp_path / "vectors.pdf"
    writer.write(path)
    optimized = inspect_pdf(path, digest(path), [])
    monkeypatch.setattr(pdf, "without_path_coordinates", lambda data: data)
    baseline = inspect_pdf(path, digest(path), [])
    assert optimized == baseline
