import importlib
import json
import re
import sys
import types
from pathlib import Path

import pytest

from building_model.cli import main
from building_model.parse_pdf import parse_pages, parse_pdf
from building_model.reader import load_document
from tests.synth import make_sheet, wall

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "building_model"


class _Calls:
    def __init__(self) -> None:
        self.args: dict[str, object] = {}


def _fake_plangeom(monkeypatch: pytest.MonkeyPatch, calls: _Calls) -> None:

    def parse_document(
        path: Path,
        pages: list[int] | None = None,
        sections: list[str] | None = None,
        workers: int = 2,
        timeout_s: float = 300.0,
    ) -> dict[str, object]:
        calls.args = {"path": path, "pages": pages, "workers": workers}
        sheet = make_sheet(page=5, walls=[wall("W0", (0, 0), (4000, 0))])
        return {"sheets": [sheet], "buildings": [{"sheets": [5]}]}

    monkeypatch.setitem(
        sys.modules, "plangeom", types.SimpleNamespace(parse_document=parse_document)
    )


def test_parse_pdf_writes_json_that_the_normalizer_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _Calls()
    _fake_plangeom(monkeypatch, calls)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "sub" / "set.json"
    summary = parse_pdf(pdf, out, pages=[5], workers=1)
    assert summary.sheets == 1
    assert summary.verdicts == {"needs_review": 1}
    assert calls.args == {"path": pdf, "pages": [5], "workers": 1}
    assert json.loads(out.read_text(encoding="utf-8"))["sheets"][0]["page"] == 5
    assert load_document(out).pages() == [5]


def test_parse_command_prints_only_aggregates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_plangeom(monkeypatch, _Calls())
    pdf = tmp_path / "secret_name.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pointer = tmp_path / "pdfpath.txt"
    pointer.write_text(str(pdf), encoding="utf-8")
    out = tmp_path / "set.json"
    code = main(["parse", "--pdf", f"@{pointer}", "--out", str(out), "--pages", "5"])
    printed = capsys.readouterr().out
    assert code == 0
    assert "листов 1" in printed
    assert "secret_name" not in printed


def test_missing_module_gives_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "plangeom", None)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError, match=r"setup_reader_env\.sh"):
        parse_pdf(pdf, tmp_path / "set.json")
    assert not (tmp_path / "set.json").exists()


def test_library_error_text_with_path_is_not_propagated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def parse_document(path: Path, **_: object) -> dict[str, object]:
        raise RuntimeError(f"не открыть {path}")

    monkeypatch.setitem(
        sys.modules, "plangeom", types.SimpleNamespace(parse_document=parse_document)
    )
    pdf = tmp_path / "private_dir_name.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError, match="завершилась ошибкой: RuntimeError") as info:
        parse_pdf(pdf, tmp_path / "set.json")
    assert "private_dir_name" not in str(info.value)


def test_missing_pdf_is_an_error_without_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as info:
        parse_pdf(tmp_path / "nope_secret.pdf", tmp_path / "set.json")
    assert "nope_secret" not in str(info.value)


def test_parse_pages() -> None:
    assert parse_pages("51,33") == [51, 33]
    for bad in ("", "a", "1,1", "-2"):
        with pytest.raises(ValueError):
            parse_pages(bad)


def test_plangeom_is_imported_only_in_parse_pdf() -> None:
    pattern = re.compile(
        r"""^\s*(import\s+plangeom|from\s+plangeom)|import_module\(\s*["']plangeom["']"""
    )
    named = re.compile(r"""import_module\(""")
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        has_direct = any(pattern.search(line) for line in text.splitlines())
        has_dynamic = bool(named.search(text)) and path.name != "parse_pdf.py"
        if has_direct or has_dynamic:
            offenders.append(path.name)
    assert offenders == []
    assert "import_module" in (PACKAGE_DIR / "parse_pdf.py").read_text(encoding="utf-8")


def test_normalizer_imports_without_plangeom(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все модули нормализатора импортируются заново при заблокированной plangeom."""
    saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] == "building_model"}
    for name in saved:
        del sys.modules[name]
    monkeypatch.setitem(sys.modules, "plangeom", None)
    try:
        for path in sorted(PACKAGE_DIR.glob("*.py")):
            if path.stem in ("__main__", "parse_pdf"):
                continue
            # binding и overlay импортируют pypdfium2/Pillow только внутри функций.
            importlib.import_module(f"building_model.{path.stem}")
    finally:
        for name in [k for k in sys.modules if k.split(".")[0] == "building_model"]:
            del sys.modules[name]
        sys.modules.update(saved)
