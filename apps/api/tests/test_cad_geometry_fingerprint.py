"""Отпечаток геометрии DXF: метаданные не влияют, геометрия влияет."""

from __future__ import annotations

from app.services.cad_geometry_fingerprint import dxf_geometry_sha256


def _section(name: str, body: list[tuple[str, str]]) -> str:
    pairs = [("0", "SECTION"), ("2", name), *body, ("0", "ENDSEC")]
    return "".join(f"{code}\n{value}\n" for code, value in pairs)


def _dxf(
    *,
    created: str = "2461000.1",
    classes: list[tuple[str, str]] | None = None,
    objects_writer: str = "ezdxf 1.0",
    x: str = "100.0",
    blocks: str = "BLK",
    tables: str = "WALLS",
) -> bytes:
    header = _section("HEADER", [("9", "$TDCREATE"), ("40", created)])
    cls = _section("CLASSES", classes if classes is not None else [("1", "A"), ("1", "B")])
    tbl = _section("TABLES", [("0", "LAYER"), ("2", tables)])
    blk = _section("BLOCKS", [("0", "BLOCK"), ("2", blocks)])
    ent = _section("ENTITIES", [("0", "LINE"), ("10", x), ("20", "5.0"), ("1", "ENDSEC text")])
    obj = _section("OBJECTS", [("1", objects_writer)])
    return (header + cls + tbl + blk + ent + obj + "0\nEOF\n").encode()


def test_metadata_does_not_change_fingerprint() -> None:
    first = _dxf()
    second = _dxf(created="2461999.9", classes=[("1", "B"), ("1", "A")], objects_writer="ezdxf 2.0")
    assert first != second
    assert dxf_geometry_sha256(first) == dxf_geometry_sha256(second)


def test_entity_coordinate_changes_fingerprint() -> None:
    assert dxf_geometry_sha256(_dxf(x="100.0")) != dxf_geometry_sha256(_dxf(x="100.1"))


def test_tables_and_blocks_change_fingerprint() -> None:
    base = dxf_geometry_sha256(_dxf())
    assert base != dxf_geometry_sha256(_dxf(tables="OTHER"))
    assert base != dxf_geometry_sha256(_dxf(blocks="OTHER"))


def test_crlf_is_tolerated() -> None:
    data = _dxf()
    assert dxf_geometry_sha256(data) == dxf_geometry_sha256(data.replace(b"\n", b"\r\n"))


def test_missing_sections_give_no_fingerprint() -> None:
    assert dxf_geometry_sha256(b"") is None
    assert dxf_geometry_sha256(_section("HEADER", [("9", "$X")]).encode()) is None
    # Нет одной из трёх секций.
    no_blocks = (
        _section("TABLES", [("0", "LAYER")]) + _section("ENTITIES", [("0", "LINE")])
    ).encode()
    assert dxf_geometry_sha256(no_blocks) is None


def test_empty_entities_give_no_fingerprint() -> None:
    data = (
        _section("TABLES", [("0", "LAYER")]) + _section("BLOCKS", []) + _section("ENTITIES", [])
    ).encode()
    assert dxf_geometry_sha256(data) is None


def test_truncated_file_without_endsec_gives_no_fingerprint() -> None:
    data = _dxf()
    cut = data[: data.index(b"ENDSEC", data.index(b"LINE")) + len(b"ENDSEC")]
    # Обрезка внутри ENTITIES: секция не закрыта.
    unclosed = cut[: cut.rindex(b"0\nENDSEC")]
    assert dxf_geometry_sha256(unclosed) is None


def test_binary_data_gives_no_fingerprint() -> None:
    assert dxf_geometry_sha256(b"AutoCAD Binary DXF\r\n\x1a\x00\xff\xfe\x80") is None


def test_bom_is_ignored() -> None:
    data = _dxf()
    assert dxf_geometry_sha256(data) is not None
    assert dxf_geometry_sha256(b"\xef\xbb\xbf" + data) == dxf_geometry_sha256(data)
