"""Runner движка PDF -> CAD: параметры v2, job.json и гейты DXF на синтетических данных.

Движок не нужен: runner на уровне модуля использует только стандартную библиотеку, а
ezdxf-часть (`_dxf_summary`, `_preview`) подменяется заглушками. Интеграционные проверки с
настоящим движком — в `test_cad_qa.py` (пропускаются без QUANTOR_CAD_ENGINE_*).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.cad_worker.handler import _page_summary
from app.contracts.cad import CadPageRead

RUNNER_PATH = Path(__file__).resolve().parents[3] / "tools" / "cad_engine" / "quantor_cad_runner.py"


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quantor_cad_runner_under_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _params(**patch: Any) -> bytes:
    params: dict[str, Any] = {
        "schema": "quantor.cad_engine.params.v2",
        "mode": "architecture",
        "pages": [0, 2],
        "page_selection": "operator",
        "scales": {
            "0": {"mm_per_pt": 70.5556, "calibration_id": "cal-0"},
            "2": {"mm_per_pt": 35.2778, "calibration_id": "cal-2"},
        },
        "finishes": False,
        "schedules": False,
        "limits": {"max_pages": 50, "total_timeout_s": 900, "max_memory_mb": 6144},
    }
    params.update(patch)
    return json.dumps(params).encode()


def test_parse_params_v2_accepts_operator_pages_and_scales(runner: ModuleType) -> None:
    parsed = runner.parse_params(_params())
    assert parsed["pages"] == [0, 2]
    assert parsed["scales"]["2"] == {"mm_per_pt": 35.2778, "calibration_id": "cal-2"}
    assert parsed["limits"]["max_memory_mb"] == 6144


@pytest.mark.parametrize(
    "patch",
    [
        {"schema": "quantor.cad_engine.params.v1"},
        {"pages": None},
        {"pages": []},
        {"pages": [0, 0], "scales": {"0": {"mm_per_pt": 1.0, "calibration_id": "a"}}},
        {"page_selection": "auto"},
        {"scales": None},
        {"scales": {"0": {"mm_per_pt": 70.0, "calibration_id": "a"}}},  # нет страницы 2
        {
            "scales": {
                "0": {"mm_per_pt": 70.0, "calibration_id": "a"},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
                "5": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {
            "scales": {
                "0": {"mm_per_pt": 0, "calibration_id": "a"},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {
            "scales": {
                "0": {"mm_per_pt": -1.0, "calibration_id": "a"},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {
            "scales": {
                "0": {"mm_per_pt": True, "calibration_id": "a"},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {
            "scales": {
                "0": {"mm_per_pt": "70", "calibration_id": "a"},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {
            "scales": {
                "0": {"mm_per_pt": 70.0},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {
            "scales": {
                "0": {"mm_per_pt": 70.0, "calibration_id": ""},
                "2": {"mm_per_pt": 70.0, "calibration_id": "a"},
            }
        },
        {"finishes": True},
        {"extra": 1},
    ],
)
def test_parse_params_v2_rejects_bad_input(runner: ModuleType, patch: dict[str, Any]) -> None:
    with pytest.raises(runner.RunnerError) as error:
        runner.parse_params(_params(**patch))
    assert error.value.exit_code == runner.EXIT_PARAMS


def test_parse_params_rejects_non_finite_scale(runner: ModuleType) -> None:
    raw = _params().replace(b"70.5556", b"Infinity")
    with pytest.raises(runner.RunnerError):
        runner.parse_params(raw)
    raw = _params().replace(b"70.5556", b"NaN")
    with pytest.raises(runner.RunnerError):
        runner.parse_params(raw)


def test_job_json_carries_operator_scales_with_legacy_page_numbers(runner: ModuleType) -> None:
    params = runner.parse_params(_params())
    pages = [runner.legacy_page(index) for index in params["pages"]]
    job = runner.job_document(pages, params)
    assert job["pages"] == [1, 3]
    assert job["operator_pages"] is True
    assert job["operator_scales"] == {
        "1": {"mm_per_pt": 70.5556, "calibration_id": "cal-0"},
        "3": {"mm_per_pt": 35.2778, "calibration_id": "cal-2"},
    }


def _style_profile(**patch: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "schema": "cad_engine.style_profile.v1",
        "id": "tom-ar1.1",
        "version": 1,
        "profile": {"monolith_fill_gray": [0.42]},
    }
    profile.update(patch)
    return profile


def test_style_profile_goes_to_job_json_as_is(runner: ModuleType) -> None:
    profile = _style_profile()
    params = runner.parse_params(_params(style_profile=profile))
    job = runner.job_document([1, 3], params)
    assert job["operator_style_profile"] == profile


def test_job_json_has_no_style_profile_without_it(runner: ModuleType) -> None:
    params = runner.parse_params(_params())
    assert "operator_style_profile" not in runner.job_document([1, 3], params)


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "profile",
        _style_profile(schema="other"),
        _style_profile(id=""),
        _style_profile(id=5),
        _style_profile(version="1"),
        _style_profile(version=True),
        _style_profile(profile=[]),
    ],
)
def test_parse_params_rejects_bad_style_profile_shape(runner: ModuleType, bad: Any) -> None:
    with pytest.raises(runner.RunnerError) as error:
        runner.parse_params(_params(style_profile=bad))
    assert error.value.exit_code == runner.EXIT_PARAMS
    assert error.value.code == "params_invalid"


def test_parse_params_accepts_auto_pages_and_job_json_skips_them(runner: ModuleType) -> None:
    """Лист без калибровки (ADR-0045): `{"auto": true}`, движку масштаб оператора не передаётся."""
    scales = {"0": {"auto": True}, "2": {"mm_per_pt": 35.2778, "calibration_id": "cal-2"}}
    params = runner.parse_params(_params(scales=scales))
    assert params["scales"] == scales
    job = runner.job_document([1, 3], params)
    assert job["operator_pages"] is True
    assert job["operator_scales"] == {"3": {"mm_per_pt": 35.2778, "calibration_id": "cal-2"}}
    everything = runner.parse_params(_params(scales={"0": {"auto": True}, "2": {"auto": True}}))
    assert runner.job_document([1, 3], everything)["operator_scales"] == {}


@pytest.mark.parametrize(
    "entry",
    [
        {"auto": False},
        {"auto": 1},
        {"auto": "true"},
        {"auto": True, "mm_per_pt": 70.0},
        {"auto": True, "calibration_id": "a"},
        {},
    ],
)
def test_parse_params_rejects_bad_auto_entry(runner: ModuleType, entry: dict[str, Any]) -> None:
    scales = {"0": entry, "2": {"mm_per_pt": 70.0, "calibration_id": "a"}}
    with pytest.raises(runner.RunnerError) as error:
        runner.parse_params(_params(scales=scales))
    assert error.value.exit_code == runner.EXIT_PARAMS


# ------------------------------------------------------------------ гейт DXF


def _attempt(
    tmp_path: Path, scale: dict[str, Any], *, dxf: bool = True, intake_selected: bool = False
) -> tuple[Path, Path, dict[str, Any]]:
    attempt = tmp_path / "attempt"
    out = tmp_path / "out"
    view_dir = attempt / "PDF_001_Вид_01"
    view_dir.mkdir(parents=True)
    out.mkdir()
    published = ["Масштаб.json"]
    (view_dir / "Масштаб.json").write_text(json.dumps(scale), encoding="utf-8")
    if dxf:
        published += ["План_кандидаты.dxf", "Контроль_CAD.json"]
        (view_dir / "План_кандидаты.dxf").write_text("0\nEOF\n", encoding="utf-8")
        (view_dir / "Контроль_CAD.json").write_text("{}", encoding="utf-8")
        (view_dir / "Контроль.json").write_text(
            json.dumps(
                {
                    "native_cad_read_during_recognition": False,
                    "pilot_geometry_read_during_recognition": False,
                    "finish_detector_called": False,
                    "quantity_release_allowed": False,
                }
            ),
            encoding="utf-8",
        )
    (attempt / "events.json").write_text(
        json.dumps(
            {
                "status": "needs_review",
                "views": [{"page": 1, "view": 1, "status": "needs_review", "stage": "export"}],
                "artifacts": [{"path": f"PDF_001_Вид_01/{name}"} for name in published],
            }
        ),
        encoding="utf-8",
    )
    inventory = {"pages": [{"pdf_page": 1, "selected": intake_selected}]}
    return attempt, out, inventory


@pytest.fixture
def embedded() -> list[list[tuple[str, str]]]:
    return []


@pytest.fixture
def stubbed(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, embedded: list[list[tuple[str, str]]]
) -> ModuleType:
    monkeypatch.setattr(
        runner, "_dxf_summary", lambda path: {"dxf_version": "AC1032", "entities": 3}
    )
    monkeypatch.setattr(runner, "_preview", lambda dxf, rel: {"schema": runner.PREVIEW_SCHEMA})
    monkeypatch.setattr(runner, "embed_dxf_properties", lambda path, props: embedded.append(props))
    return runner


def _collect(
    runner: ModuleType, tmp_path: Path, scale: dict[str, Any], **kwargs: Any
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], Path]:
    attempt, out, inventory = _attempt(tmp_path, scale, **kwargs)
    status, error, pages = runner.collect(attempt, out, inventory, 0, "")
    return status, error, pages, out


def test_gate_passed_scale_releases_dxf(stubbed: ModuleType, tmp_path: Path) -> None:
    status, error, pages, out = _collect(
        stubbed, tmp_path, {"status": "passed", "source": "dimension_chains"}
    )
    assert (status, error) == ("completed_requires_review", None)
    [page] = pages
    assert page["intake_selected"] is False and "selected" not in page
    [view] = page["views"]
    assert view["scale_status"] == "passed" and view["dxf"]["entities"] == 3
    assert (out / "views/p001_v01/plan_candidates.dxf").is_file()


def test_gate_needs_review_with_operator_calibration_releases_dxf(
    stubbed: ModuleType, tmp_path: Path
) -> None:
    scale = {
        "status": "needs_review",
        "source": "operator_calibration",
        "operator_mm_per_pt": 70.5556,
        "dimension_mm_per_pt": 68.9,
        "deviation": 0.023,
        "reason": "отклонение выше допуска",
    }
    status, _, pages, out = _collect(stubbed, tmp_path, scale, intake_selected=True)
    assert status == "completed_requires_review"
    [page] = pages
    assert page["intake_selected"] is True
    [view] = page["views"]
    assert view["scale_status"] == "needs_review"
    assert view["scale_source"] == "operator_calibration" and view["scale_deviation"] == 0.023
    assert (out / "views/p001_v01/plan_candidates.dxf").is_file()
    assert (out / "views/p001_v01/scale.json").is_file()


def test_gate_chains_passed_without_operator_releases_dxf(
    stubbed: ModuleType, tmp_path: Path
) -> None:
    """Лист без калибровки: `dimension_checks_passed` по цепочкам даёт DXF (ADR-0045)."""
    scale = {"status": "dimension_checks_passed", "source": "dimension_chains"}
    status, error, pages, out = _collect(stubbed, tmp_path, scale)
    assert (status, error) == ("completed_requires_review", None)
    [view] = pages[0]["views"]
    assert view["scale_status"] == "dimension_checks_passed"
    assert view["scale_source"] == "dimension_chains" and view["dxf"]["entities"] == 3
    assert (out / "views/p001_v01/plan_candidates.dxf").is_file()


def test_gate_needs_review_by_dimension_chains_is_a_violation(
    stubbed: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(stubbed.RunnerError) as error:
        _collect(stubbed, tmp_path, {"status": "needs_review", "source": "dimension_chains"})
    assert error.value.code == "gate_violation"


@pytest.mark.parametrize("status", ["dimension_checks_passed", "unknown", None])
def test_gate_other_statuses_with_dxf_are_violations(
    stubbed: ModuleType, tmp_path: Path, status: str | None
) -> None:
    with pytest.raises(stubbed.RunnerError) as error:
        _collect(stubbed, tmp_path, {"status": status, "source": "operator_calibration"})
    assert error.value.code == "gate_violation"


def test_gate_failed_scale_has_no_dxf_and_reports_calibration_mismatch(
    stubbed: ModuleType, tmp_path: Path
) -> None:
    scale = {
        "status": "failed",
        "source": "operator_calibration",
        "operator_mm_per_pt": 70.5556,
        "dimension_mm_per_pt": 52.0,
        "deviation": 0.26,
        "reason": "Проверьте калибровку: расхождение с размерными цепочками 26%",
    }
    status, error, pages, out = _collect(stubbed, tmp_path, scale, dxf=False)
    assert (status, error) == ("no_cad_review_required", None)
    [view] = pages[0]["views"]
    assert view["dxf"] is None
    assert view["failure_code"] == "calibration_mismatch"
    assert view["failure_reason"].startswith("Проверьте калибровку")
    assert view["scale_deviation"] == 0.26
    assert not list(out.rglob("*.dxf"))


def test_view_error_without_dxf_is_a_failure_with_known_limitation(
    stubbed: ModuleType, tmp_path: Path
) -> None:
    """Движок публикует масштаб.json даже при падении вида и выходит с кодом 0 — это отказ."""
    attempt, out, inventory = _attempt(
        tmp_path, {"status": "passed", "source": "operator_calibration"}, dxf=False
    )
    events = json.loads((attempt / "events.json").read_text(encoding="utf-8"))
    events["views"][0].update(status="error", stage="Ошибка")
    (attempt / "events.json").write_text(json.dumps(events), encoding="utf-8")
    log = "ValueError: zero-size array to reduction operation minimum"
    status, error, pages = stubbed.collect(attempt, out, inventory, 0, log)
    assert status == "failed"
    assert error == {
        "code": "engine_failed",
        "message": "движок не выдал пригодных результатов",
        "known_limitation": "pdfcontext_empty_black_stroke_index",
    }
    assert pages[0]["views"][0]["status"] == "error"


def test_gate_failed_scale_with_dxf_is_a_violation(stubbed: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(stubbed.RunnerError) as error:
        _collect(stubbed, tmp_path, {"status": "failed", "source": "operator_calibration"})
    assert error.value.code == "gate_violation"


def test_failure_and_intake_hint_reach_the_job_result() -> None:
    summary = _page_summary(
        {
            "pages": [
                {
                    "index": 0,
                    "legacy_pdf_page": 1,
                    "intake_selected": False,
                    "views": [
                        {
                            "view": 1,
                            "status": "needs_review",
                            "scale_status": "failed",
                            "scale_source": "operator_calibration",
                            "scale_deviation": 0.26,
                            "failure_code": "calibration_mismatch",
                            "failure_reason": "Проверьте калибровку",
                        }
                    ],
                }
            ]
        }
    )
    page = CadPageRead.model_validate(summary[0])
    assert page.intake_selected is False
    assert page.views[0].failure_code == "calibration_mismatch"
    assert page.views[0].scale_source == "operator_calibration"
    # Результаты прежних заданий (без новых полей) читаются как раньше.
    legacy = CadPageRead.model_validate(
        {
            "index": 0,
            "legacy_pdf_page": 1,
            "views": [
                {
                    "view": 1,
                    "status": "needs_review",
                    "scale_status": "dimension_checks_passed",
                    "dxf": "views/p001_v01/plan_candidates.dxf",
                    "dxf_entities": 8,
                }
            ],
        }
    )
    assert legacy.intake_selected is None and legacy.views[0].failure_code is None


# ------------------------------------------------------------------ свойства чертежа в DXF

SCALE_RAW: dict[str, Any] = {
    "status": "needs_review",
    "source": "operator_calibration",
    "method": "dimension_chain_fit",
    "operator_mm_per_pt": 70.5556,
    "dimension_mm_per_pt": 68.9,
    "mm_per_pdf_point_fitted": 68.9,
    "scale_denominator_fitted": 195.3,
    "deviation": 0.023,
    "printed_scale_labels": [200, 100],
    "printed_scale_consistent": True,
    "fit_controls": 4,
    "heldout_controls": 2,
    "fit_chains": 3,
    "heldout_chains": 1,
    "independent_axes": True,
    "anchored_conflicts": [{"a": 1}],
    "unassociated_numeric_labels": [],
    "release_allowed": False,
}
SHA = "ab" * 32
CONTEXT = {
    "job_id": "5f1c0f1e-0000-4000-8000-000000000001",
    "source_sha256": SHA,
    "engine_version": "2026.11.12+19579f0cd4c5",
    "engine_commit": "c10110fea15f95fb9e4ce7bed44e298dca2cadbf",
    "runner_version": "0.1.0",
}
CHECKS_RAW = {"units": "mm", "origin_pdf_display_pt": [12.5, 40.0]}


def test_dxf_properties_cover_scale_and_origin(runner: ModuleType) -> None:
    moment = datetime(2026, 11, 10, 12, 30, tzinfo=UTC)
    props = dict(
        runner.build_dxf_properties(
            page=3,
            view=1,
            scale=SCALE_RAW,
            cad_checks=CHECKS_RAW,
            context=CONTEXT,
            generated_at=moment,
        )
    )
    assert props["QUANTOR_JOB_ID"] == CONTEXT["job_id"]
    assert (props["QUANTOR_PAGE_INDEX"], props["QUANTOR_PAGE_NUMBER"]) == ("2", "3")
    assert props["QUANTOR_SOURCE_PDF_SHA256"] == SHA
    assert props["QUANTOR_SCALE"] == "1:200"  # масштаб оператора 70.5556 мм/pt
    assert props["QUANTOR_MM_PER_PDF_POINT"] == "70.5556"
    assert props["QUANTOR_SCALE_FITTED"] == "1:195.3"
    assert props["QUANTOR_PRINTED_SCALE"] == "1:200, 1:100"
    assert props["QUANTOR_SCALE_STATUS"] == "needs_review"
    assert props["QUANTOR_SCALE_DEVIATION"] == "0.023"
    assert (props["QUANTOR_FIT_CONTROLS"], props["QUANTOR_CHECK_CONTROLS"]) == ("4", "2")
    assert (props["QUANTOR_FIT_CHAINS"], props["QUANTOR_CHECK_CHAINS"]) == ("3", "1")
    assert props["QUANTOR_INDEPENDENT_AXES"] == "true"
    assert (props["QUANTOR_BINDING_CONFLICTS"], props["QUANTOR_UNBOUND_LABELS"]) == ("1", "0")
    assert props["QUANTOR_RELEASE_ALLOWED"] == "false"
    assert props["QUANTOR_DXF_UNITS"] == "mm" and props["QUANTOR_ORIGIN_PDF_PT"] == "12.5, 40"
    assert props["QUANTOR_ENGINE_COMMIT"] == CONTEXT["engine_commit"]
    assert props["QUANTOR_GENERATED_AT"] == "2026-11-10T12:30:00Z"
    assert all(len(v) <= 255 and "\n" not in v for v in props.values())


def test_dxf_properties_skip_absent_fields_and_bad_values(runner: ModuleType) -> None:
    props = dict(
        runner.build_dxf_properties(
            page=1,
            view=1,
            scale={"status": "passed", "deviation": float("nan")},
            cad_checks={},
            context={"job_id": "../etc/passwd", "source_sha256": "zz"},
        )
    )
    assert set(props) == {
        "QUANTOR_PAGE_INDEX",
        "QUANTOR_PAGE_NUMBER",
        "QUANTOR_VIEW",
        "QUANTOR_SCALE_STATUS",
        "QUANTOR_GENERATED_AT",
    }


def test_collect_passes_properties_before_dxf_summary(
    stubbed: ModuleType, embedded: list[list[tuple[str, str]]], tmp_path: Path
) -> None:
    attempt, out, inventory = _attempt(tmp_path, {"status": "passed", "source": "dimension_chains"})
    (attempt / "PDF_001_Вид_01" / "Контроль_CAD.json").write_text(
        json.dumps(CHECKS_RAW), encoding="utf-8"
    )
    stubbed.collect(attempt, out, inventory, 0, "", CONTEXT)
    [props] = embedded
    assert dict(props)["QUANTOR_DXF_UNITS"] == "mm"
    assert dict(props)["QUANTOR_JOB_ID"] == CONTEXT["job_id"]


def test_embed_dxf_properties_roundtrip_keeps_version_and_geometry(
    runner: ModuleType, tmp_path: Path
) -> None:
    ezdxf = pytest.importorskip("ezdxf")
    path = tmp_path / "plan.dxf"
    document = ezdxf.new("R2018")
    document.header.custom_vars.append("QUANTOR_OLD", "stale")
    document.header.custom_vars.append("OTHER", "keep")
    document.modelspace().add_line((0, 0), (1000, 0))
    document.modelspace().add_lwpolyline([(0, 0), (1000, 0), (1000, 500)], close=True)
    document.saveas(path)
    props = runner.build_dxf_properties(
        page=1, view=1, scale=SCALE_RAW, cad_checks=CHECKS_RAW, context=CONTEXT
    )
    for _ in range(2):  # повторная запись заменяет, а не дублирует
        runner.embed_dxf_properties(path, props)
    reread = ezdxf.readfile(path)
    assert reread.dxfversion == "AC1032"
    stored = dict(reread.header.custom_vars)
    assert stored["QUANTOR_SCALE"] == "1:200" and stored["QUANTOR_JOB_ID"] == CONTEXT["job_id"]
    assert stored["OTHER"] == "keep" and "QUANTOR_OLD" not in stored
    assert len(reread.header.custom_vars) == len(props) + 1
    assert [e.dxftype() for e in reread.modelspace()] == ["LINE", "LWPOLYLINE"]
    assert len(reread.audit().errors) == 0
    assert runner.sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ подкоманда style (ADR-0049)

ENGINE_INFO = {"name": "engine", "version": "2026.11.16+x", "archive_sha256": "a" * 64}


def _style_args(runner: ModuleType, tmp_path: Path) -> Any:
    for name in ("work", "out"):
        (tmp_path / name).mkdir()
    return runner.argparse.Namespace(
        archive=tmp_path / "engine.zip",
        expect_archive_sha256=None,
        input=tmp_path / "sheet.pdf",
        samples=tmp_path / "samples.json",
        work=tmp_path / "work",
        out=tmp_path / "out",
        base_profile=None,
        max_memory_mb=3072,
    )


@pytest.fixture
def style_runner(runner: ModuleType, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(runner, "load_pins", lambda: {"engine": {}})
    monkeypatch.setattr(runner, "check_environment", lambda pins: {})
    monkeypatch.setattr(runner, "verify_archive", lambda archive, pins, sha=None: ENGINE_INFO)
    monkeypatch.setattr(runner, "extract_archive", lambda archive, target, pins: target.mkdir())
    return runner


def _fake_script(
    runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    *,
    profile: bool,
    log_text: str = "",
    preview: bool = True,
) -> None:
    def fake(
        engine_root: Path,
        pdf: Path,
        samples: Path,
        out_dir: Path,
        base_profile: Path | None,
        log_path: Path,
        max_memory_mb: int,
    ) -> int:
        log_path.write_text(log_text, encoding="utf-8")
        if preview:
            (out_dir / "preview.json").write_text('{"p": 1}', encoding="utf-8")
        if profile:
            (out_dir / "style_profile.json").write_text('{"schema": "s"}', encoding="utf-8")
        return code

    monkeypatch.setattr(runner, "run_style_script", fake)


def test_style_command_arguments_become_absolute_and_reach_the_handler(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def capture(args: Any) -> int:
        seen.append(args)
        return 0

    monkeypatch.setattr(runner, "style", capture)
    code = runner.main(
        [
            "style",
            "--archive",
            "a.zip",
            "--input",
            "s.pdf",
            "--samples",
            "s.json",
            "--work",
            "w",
            "--out",
            "o",
            "--base-profile",
            "b.json",
            "--expect-archive-sha256",
            "f" * 64,
        ]
    )
    assert code == 0
    [args] = seen
    assert args.command == "style" and args.expect_archive_sha256 == "f" * 64
    for name in ("archive", "input", "samples", "work", "out", "base_profile"):
        assert getattr(args, name).is_absolute(), name


def test_style_command_requires_its_own_arguments(runner: ModuleType) -> None:
    with pytest.raises(SystemExit):
        runner.main(["style", "--archive", "a.zip"])


def test_style_profile_exit_copies_files_and_writes_result(
    style_runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _style_args(style_runner, tmp_path)
    _fake_script(style_runner, monkeypatch, 0, profile=True)
    assert style_runner.style(args) == 0
    assert (args.out / "preview.json").read_text(encoding="utf-8") == '{"p": 1}'
    assert (args.out / "style_profile.json").is_file()
    result = json.loads((args.out / "result.json").read_text(encoding="utf-8"))
    assert result == {
        "status": "profile",
        "engine_version": ENGINE_INFO["version"],
        "archive_sha256": ENGINE_INFO["archive_sha256"],
    }


def test_style_no_signature_exit_keeps_only_the_preview(
    style_runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _style_args(style_runner, tmp_path)
    _fake_script(style_runner, monkeypatch, 2, profile=False)
    assert style_runner.style(args) == 0
    assert (args.out / "preview.json").is_file()
    assert not (args.out / "style_profile.json").exists()
    result = json.loads((args.out / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "no_signature"


def test_style_script_input_error_is_input_invalid(
    style_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _style_args(style_runner, tmp_path)
    _fake_script(
        style_runner,
        monkeypatch,
        1,
        profile=False,
        preview=False,
        log_text="Ошибка: Образцы: страницы 9 нет в PDF\n",
    )
    assert style_runner.style(args) == style_runner.EXIT_INPUT
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "input_invalid" and "страницы 9" in error["message"]
    assert not any(args.out.iterdir())


def test_style_script_crash_with_code_one_is_a_retryable_engine_failure(
    style_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Код 1 дают и необработанное исключение, и MemoryError: отказом входа это не считается."""
    args = _style_args(style_runner, tmp_path)
    _fake_script(
        style_runner,
        monkeypatch,
        1,
        profile=False,
        preview=False,
        log_text=(
            "Traceback (most recent call last):\n"
            '  File "/work/engine/style_samples.py", line 9, in <module>\n'
            "MemoryError\n"
        ),
    )
    assert style_runner.style(args) == style_runner.EXIT_ENGINE
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "engine_failed"
    assert "Traceback" not in error["message"] and "/work" not in error["message"]


def test_style_memory_limit_comes_from_the_arguments(
    style_runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _style_args(style_runner, tmp_path)
    args.max_memory_mb = 4096
    seen: list[int] = []

    def fake(*call: Any) -> int:
        seen.append(call[-1])
        (call[3] / "preview.json").write_text("{}", encoding="utf-8")
        return 2

    monkeypatch.setattr(style_runner, "run_style_script", fake)
    assert style_runner.style(args) == 0 and seen == [4096]


def test_style_memory_limit_outside_the_range_is_rejected(
    style_runner: ModuleType, tmp_path: Path
) -> None:
    args = _style_args(style_runner, tmp_path)
    args.max_memory_mb = 64
    assert style_runner.style(args) == style_runner.EXIT_PARAMS


@pytest.mark.parametrize(
    ("code", "profile", "preview"),
    [
        (7, False, True),  # неизвестный код скрипта
        (0, False, True),  # профиль обещан, файла нет
        (2, True, True),  # подписи нет, а файл профиля есть
        (0, True, False),  # нет предпросмотра
    ],
)
def test_style_script_outside_the_contract_is_an_engine_failure(
    style_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    code: int,
    profile: bool,
    preview: bool,
) -> None:
    args = _style_args(style_runner, tmp_path)
    _fake_script(style_runner, monkeypatch, code, profile=profile, preview=preview)
    assert style_runner.style(args) == style_runner.EXIT_ENGINE
    assert not any(args.out.iterdir())


def test_style_requires_empty_work_and_out(style_runner: ModuleType, tmp_path: Path) -> None:
    args = _style_args(style_runner, tmp_path)
    (args.out / "stale.txt").write_text("x")
    assert style_runner.style(args) == style_runner.EXIT_PARAMS


def _stub_run(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, base: Path | None
) -> dict[str, Any]:
    script = tmp_path / "engine" / runner.STYLE_SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("")
    seen: dict[str, Any] = {"script": script}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        seen.update(kwargs, command=command)
        return runner.subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    seen["code"] = runner.run_style_script(
        tmp_path / "engine",
        tmp_path / "a.pdf",
        tmp_path / "s.json",
        tmp_path / "produced",
        base,
        tmp_path / "log",
    )
    return seen


def test_run_style_script_command_with_and_without_base_profile(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "base.json"
    seen = _stub_run(runner, monkeypatch, tmp_path, base)
    command: list[str] = seen["command"]
    assert seen["code"] == 2
    assert command[:3] == [sys.executable, "-B", "-s"] and command[3] == str(seen["script"])
    assert command[command.index("--base-profile") + 1] == str(base)
    assert seen["cwd"] == seen["script"].parent and seen["timeout"] == runner.STYLE_TIMEOUT_S
    assert set(seen["env"]) >= {"PATH", "LANG", "HOME", "TMPDIR"}
    assert "--base-profile" not in _stub_run(runner, monkeypatch, tmp_path, None)["command"]


def test_run_style_script_timeout_is_a_limit_failure(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "engine" / runner.STYLE_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text("")

    def hang(command: list[str], **kwargs: Any) -> Any:
        raise runner.subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(runner.subprocess, "run", hang)
    with pytest.raises(runner.RunnerError) as error:
        runner.run_style_script(
            tmp_path / "engine",
            tmp_path / "a.pdf",
            tmp_path / "s.json",
            tmp_path / "produced",
            None,
            tmp_path / "log",
        )
    assert error.value.exit_code == runner.EXIT_LIMIT and error.value.code == "timeout"


def test_run_style_script_without_the_script_in_the_archive_is_an_integrity_failure(
    runner: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(runner.RunnerError) as error:
        runner.run_style_script(
            tmp_path, tmp_path / "a.pdf", tmp_path / "s.json", tmp_path / "o", None, tmp_path / "l"
        )
    assert error.value.exit_code == runner.EXIT_INTEGRITY


def _convert_hints(**patch: Any) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "schema": "quantor.cad_convert_hints.v1",
        "page": 1,
        "hints": [
            {"id": "r1", "type": "missing_wall", "bbox_pt": [10, 20, 30, 40], "comment": "стена"}
        ],
    }
    hints.update(patch)
    return hints


def test_convert_hints_go_to_job_json_as_is(runner: ModuleType) -> None:
    hints = _convert_hints()
    params = runner.parse_params(_params(convert_hints=hints))
    assert runner.job_document([1, 3], params)["operator_convert_hints"] == hints
    plain = runner.parse_params(_params())
    assert "operator_convert_hints" not in runner.job_document([1, 3], plain)


@pytest.mark.parametrize(
    "bad",
    [
        [],
        _convert_hints(schema="other"),
        _convert_hints(page=0),
        _convert_hints(page=True),
        _convert_hints(page=2),
        _convert_hints(hints=[]),
        _convert_hints(extra=1),
        _convert_hints(hints=[{"id": "a", "type": "false_wall", "bbox_pt": [0, 0, 1, 1]}]),
        _convert_hints(hints=[{"id": "a", "type": "missing_door", "bbox_pt": [1, 0, 0, 1]}]),
        _convert_hints(hints=[{"id": "a", "type": "missing_door", "bbox_pt": [0, 0, 1]}]),
        _convert_hints(hints=[{"id": "a" * 65, "type": "missing_door", "bbox_pt": [0, 0, 1, 1]}]),
        _convert_hints(
            hints=[
                {"id": "a", "type": "missing_door", "bbox_pt": [0, 0, 1, 1]},
                {"id": "a", "type": "missing_door", "bbox_pt": [0, 0, 1, 1]},
            ]
        ),
        _convert_hints(
            hints=[
                {"id": str(n), "type": "missing_door", "bbox_pt": [0, 0, 1, 1]} for n in range(251)
            ]
        ),
    ],
)
def test_parse_params_rejects_bad_convert_hints(runner: ModuleType, bad: Any) -> None:
    with pytest.raises(runner.RunnerError) as error:
        runner.parse_params(_params(convert_hints=bad))
    assert error.value.exit_code == runner.EXIT_PARAMS
    assert error.value.code == "params_invalid"


def _hatch_class(**patch: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "signature_id": "ae2b34038041",
        "color": [0.145, 0.0, 0.29],
        "pen_pt": 0.28,
        "angle_deg": 135.0,
        "pitch_pt": 4.5,
        "class": "monolith",
    }
    item.update(patch)
    return item


def test_hatch_classes_allow_empty_or_missing_hints(runner: ModuleType) -> None:
    classes = [_hatch_class()]
    only_classes = {
        "schema": "quantor.cad_convert_hints.v1",
        "page": 1,
        "hatch_classes": classes,
    }
    params = runner.parse_params(_params(convert_hints=only_classes))
    assert runner.job_document([1, 3], params)["operator_convert_hints"] == only_classes
    with_empty = _convert_hints(hints=[], hatch_classes=classes)
    runner.parse_params(_params(convert_hints=with_empty))
    with_both = _convert_hints(hatch_classes=classes)
    runner.parse_params(_params(convert_hints=with_both))


@pytest.mark.parametrize(
    "bad_classes",
    [
        [],
        "x",
        [_hatch_class(**{"class": "wall"})],
        [_hatch_class(color=[0, 0])],
        [_hatch_class(color=[0, 0, 2])],
        [_hatch_class(pen_pt=0)],
        [_hatch_class(angle_deg=180)],
        [_hatch_class(pitch_pt=-1)],
        [_hatch_class(signature_id="")],
        [{**_hatch_class(), "extra": 1}],
        [_hatch_class() for _ in range(21)],
    ],
)
def test_parse_params_rejects_bad_hatch_classes(runner: ModuleType, bad_classes: Any) -> None:
    hints = _convert_hints(hints=[], hatch_classes=bad_classes)
    with pytest.raises(runner.RunnerError) as error:
        runner.parse_params(_params(convert_hints=hints))
    assert error.value.exit_code == runner.EXIT_PARAMS


def test_collect_copies_hatch_signatures_for_view(stubbed: ModuleType, tmp_path: Path) -> None:
    attempt, out, inventory = _attempt(tmp_path, {"status": "passed", "source": "dimension_chains"})
    document = '{"schema":"quantor.cad_hatch_signatures.v1","signatures":[]}'
    (attempt / "PDF_001_Вид_01" / "hatch_signatures.json").write_text(document, encoding="utf-8")
    _, _, pages = stubbed.collect(attempt, out, inventory, 0, "")
    [view] = pages[0]["views"]
    assert (out / "views/p001_v01/hatch_signatures.json").read_text(encoding="utf-8") == document
    assert "views/p001_v01/hatch_signatures.json" in view["files"]


def test_collect_copies_hatch_signatures_even_without_dxf(
    stubbed: ModuleType, tmp_path: Path
) -> None:
    attempt, out, inventory = _attempt(tmp_path, {"status": "failed"}, dxf=False)
    (attempt / "PDF_001_Вид_01" / "hatch_signatures.json").write_text("{}", encoding="utf-8")
    _, _, pages = stubbed.collect(attempt, out, inventory, 0, "")
    assert (out / "views/p001_v01/hatch_signatures.json").is_file()
    assert "views/p001_v01/hatch_signatures.json" in pages[0]["views"][0]["files"]


def test_collect_without_hatch_signatures_adds_nothing(stubbed: ModuleType, tmp_path: Path) -> None:
    scale = {"status": "passed", "source": "dimension_chains"}
    _, _, pages, out = _collect(stubbed, tmp_path, scale)
    assert not (out / "views/p001_v01/hatch_signatures.json").exists()
    assert not any("hatch_signatures" in name for name in pages[0]["views"][0]["files"])
