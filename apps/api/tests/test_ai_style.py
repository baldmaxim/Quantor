"""Роль «оформление»: подписи пакета, проверка ответа, подсказки движку, пакет CLI."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import ai_style, ai_style_cli
from app.cad_worker.ai_style import execute_ai_style, read_signatures, sanitize_report
from app.cad_worker.handler import CadError, _hatch_applied
from app.contracts.cad_ai_review import AiPromptRole, AiReviewStart
from app.contracts.cad_ai_style import AiStyleReport
from app.contracts.cad_convert_hints import CadConvertHints, CadHatchClass
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import ErrorCode, http_error
from app.models import AiPromptVersion, Job
from app.services import ai_loop, cad_views, cad_walls_zones, jobs
from app.services import cad as cad_service
from tests.conftest import FakeObjectStorage, clean_settings
from tests.test_ai_loop import DXF, DXF_NAME, SIGNATURES_NAME, _context
from tests.test_ai_loop import _settings as _loop_settings

HATCH = {
    "id": "ae2b34038041",
    "kind": "hatch",
    "color": [0.145, 0.0, 0.29],
    "pen_pt": 0.28,
    "angle_deg": 135.0,
    "pitch_pt": 4.5,
    "regions": 12,
    "area_mm2": 2986851.9,
    "examples_bbox_pt": [[40.0, 40.0, 100.0, 80.0]],
}
FILL = {
    "id": "f89fd5dc5bab",
    "kind": "fill",
    "color": [0.8, 0.8, 0.8],
    "regions": 3,
    "area_mm2": 4480277.8,
    "examples_bbox_pt": [[300.0, 100.0, 360.0, 160.0]],
}


def _document(*rows: dict[str, Any]) -> bytes:
    return json.dumps(
        {"schema": "quantor.cad_hatch_signatures.v1", "pdf_page": 82, "signatures": list(rows)}
    ).encode()


def _item(signature_id: str, class_: str = "monolith", confidence: str = "high") -> dict[str, Any]:
    return {
        "signature_id": signature_id,
        "class": class_,
        "confidence": confidence,
        "evidence": "легенда листа",
    }


def _report(*items: dict[str, Any]) -> AiStyleReport:
    return AiStyleReport.model_validate({"classes": list(items), "limitations": []})


# ------------------------------------------------------------------ контракты и подписи


def test_report_schema_names_the_class_field_and_bounds_the_answer() -> None:
    schema = AiStyleReport.model_json_schema()
    item = schema["$defs"]["AiStyleClass"]
    assert set(item["properties"]) == {"signature_id", "class", "confidence", "evidence"}
    assert schema["properties"]["classes"]["maxItems"] == 20
    with pytest.raises(ValidationError):
        _report(_item("a", "wall"))
    with pytest.raises(ValidationError):
        _report(*[_item(str(n)) for n in range(21)])
    with pytest.raises(ValidationError):
        AiStyleReport.model_validate(
            {"classes": [{**_item("a"), "area_mm2": 5.0}], "limitations": []}
        )


def test_style_is_a_prompt_and_job_role_but_not_a_manual_review_start() -> None:
    assert get_args(AiPromptRole) == ("corrector", "verifier", "vor_mapper", "style")
    with pytest.raises(ValidationError):
        AiReviewStart.model_validate({"role": "style"})


def test_read_signatures_checks_schema_and_ids() -> None:
    found = read_signatures(_document(HATCH, FILL, {**HATCH, "pen_pt": 9.0}))
    assert set(found) == {HATCH["id"], FILL["id"]} and found[HATCH["id"]]["pen_pt"] == 0.28
    with pytest.raises(ValueError, match="схема"):
        read_signatures(json.dumps({"schema": "other", "signatures": []}).encode())
    with pytest.raises(ValueError, match="больше допустимого"):
        read_signatures(b" " * (1024 * 1024 + 1))


# ------------------------------------------------------------------ проверка ответа модели


def test_sanitize_takes_numbers_from_the_package_not_from_the_model() -> None:
    signatures = read_signatures(_document(HATCH, FILL))
    report = _report(_item(HATCH["id"], "masonry", "medium"))
    [resolved], dropped = sanitize_report(report, signatures)
    assert dropped == []
    assert resolved.class_name == "masonry" and resolved.confidence == "medium"
    assert (resolved.color, resolved.pen_pt, resolved.angle_deg, resolved.pitch_pt) == (
        (0.145, 0.0, 0.29),
        0.28,
        135.0,
        4.5,
    )
    # Те же числа уходят движку подсказкой преобразования.
    hatch = CadHatchClass.model_validate(
        {
            "signature_id": resolved.signature_id,
            "color": list(resolved.color),
            "pen_pt": resolved.pen_pt,
            "angle_deg": resolved.angle_deg,
            "pitch_pt": resolved.pitch_pt,
            "class": resolved.class_name,
        }
    )
    params = CadConvertHints(page=82, hatch_classes=[hatch]).to_params()
    assert params == {
        "schema": "quantor.cad_convert_hints.v1",
        "page": 82,
        "hints": [],
        "hatch_classes": [
            {
                "signature_id": "ae2b34038041",
                "color": [0.145, 0.0, 0.29],
                "pen_pt": 0.28,
                "angle_deg": 135.0,
                "pitch_pt": 4.5,
                "class": "masonry",
            }
        ],
    }


def test_sanitize_drops_foreign_ids_fills_repeats_and_broken_numbers() -> None:
    broken = {**HATCH, "id": "bad", "angle_deg": 190.0}
    signatures = read_signatures(_document(HATCH, FILL, broken))
    report = _report(
        _item("ghost"),
        _item(FILL["id"]),
        _item(HATCH["id"]),
        _item(HATCH["id"], "ignore"),
        _item("bad"),
    )
    resolved, dropped = sanitize_report(report, signatures)
    assert [(row.signature_id, row.class_name) for row in resolved] == [(HATCH["id"], "monolith")]
    assert len(dropped) == 4
    assert any("вне пакета" in line for line in dropped)
    assert any("заливок" in line for line in dropped)
    assert any("повторов" in line for line in dropped)
    assert any("неполными числами" in line for line in dropped)


def test_hatch_classes_params_keep_old_hashes_when_empty() -> None:
    from app.contracts.cad_convert_hints import CadConvertHint

    hint = CadConvertHint(id="a", type="missing_wall", bbox_pt=(1, 2, 3, 4))
    plain = CadConvertHints(page=1, hints=[hint]).to_params()
    assert set(plain) == {"schema", "page", "hints"}
    with pytest.raises(ValidationError):
        CadConvertHints(page=1)
    with pytest.raises(ValidationError):
        CadHatchClass.model_validate(
            {"color": [0, 0, 2], "pen_pt": 1, "angle_deg": 1, "pitch_pt": 1, "class": "ignore"}
        )
    with pytest.raises(ValidationError):
        CadHatchClass.model_validate(
            {"color": [0, 0, 1], "pen_pt": 1, "angle_deg": 180, "pitch_pt": 1, "class": "ignore"}
        )
    too_many = [
        CadHatchClass.model_validate(
            {"color": [0, 0, 1], "pen_pt": 1, "angle_deg": 1, "pitch_pt": n + 1, "class": "ignore"}
        )
        for n in range(21)
    ]
    with pytest.raises(ValidationError):
        CadConvertHints(page=1, hatch_classes=too_many)


def test_hint_applied_row_reads_the_hatch_class_report() -> None:
    rows = cad_views._hints_applied(
        [
            {"id": "r1", "type": "missing_wall", "status": "applied", "added": 1},
            {
                "id": "hatch_class:1",
                "type": "hatch_class",
                "class": "monolith",
                "signature_id": "ae2b34038041",
                "status": "applied",
                "added": 12,
                "area_mm2": 2986851.9,
                "reason": "",
            },
        ]
    )
    assert rows is not None and rows[0].class_name is None
    assert (rows[1].class_name, rows[1].signature_id, rows[1].added) == (
        "monolith",
        "ae2b34038041",
        12,
    )
    assert rows[1].area_mm2 == 2986851.9


def test_runner_hatch_report_is_read_from_local_view_files(tmp_path: Path) -> None:
    folder = tmp_path / "views" / "p082_v01"
    folder.mkdir(parents=True)
    (folder / "checks.json").write_text(
        json.dumps(
            {
                "hints_applied": [
                    {"id": "a", "type": "missing_wall", "status": "applied", "added": 1},
                    {
                        "id": "hatch_class:1",
                        "type": "hatch_class",
                        "class": "masonry",
                        "signature_id": "s1",
                        "status": "applied",
                        "added": 7,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    other = tmp_path / "views" / "p082_v02"
    other.mkdir()
    (other / "checks.json").write_text("{}", encoding="utf-8")
    assert _hatch_applied(tmp_path) == [
        {
            "page_index": 81,
            "view": 1,
            "classes": [
                {"signature_id": "s1", "class_name": "masonry", "status": "applied", "added": 7}
            ],
        }
    ]


# ------------------------------------------------------------------ пакет CLI


def test_cli_package_has_style_files_and_no_walls_overlay() -> None:
    block = re.search(r"names = \{(.*?)\}", ai_style_cli.REMOTE, re.S)
    assert block is not None
    names = set(re.findall(r'"([^"]+)"', block.group(1)))
    assert set(ai_style_cli.PACKAGE_FILES) == names
    assert "hatch_signatures.json" in names and "plan.png" in names
    assert "walls.json" not in names and "overlay.png" not in names


def test_remote_command_is_stable_and_depends_on_timeout() -> None:
    first = ai_style_cli.remote_command(900)
    assert first == ai_style_cli.remote_command(900) and first.endswith(" 900")
    assert first.startswith("python3 -c ")
    assert (
        hashlib.sha256(first.encode()).hexdigest()
        != hashlib.sha256(ai_style_cli.remote_command(600).encode()).hexdigest()
    )


# ------------------------------------------------------------------ исполнитель


def _response(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": {"vor": {"filename": "vor.md", "sha256": "a" * 64}},
        "report": {"classes": list(items), "limitations": ["без легенды"]},
        "usage": {"cost_usd": 0.4, "duration_ms": 900, "input_tokens": 10, "output_tokens": 5},
        "model": "claude-opus-5-5",
        "prompt_sha256": "b" * 64,
        "bundle_sha256": "c" * 64,
    }


async def _run_execute(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any], exit_code: int = 0
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.RUNNING,
        job_type=JobType.CAD_AI_REVIEW,
        worker_id="w",
        attempt=1,
        payload={},
    )
    manifest = {
        "cad_job_id": str(uuid.uuid4()),
        "cad_attempt": 1,
        "revision_id": str(uuid.uuid4()),
        "page_index": 81,
        "view": 1,
        "model": "claude-opus-5-5",
        "input_sha256": "e" * 64,
        "signatures_sha256": "f" * 64,
        "sources": {"vor": "/pilot/vor.md"},
        "prompt_version_id": str(uuid.uuid4()),
        "prompt_version": 1,
    }
    signatures = read_signatures(_document(HATCH, FILL))

    async def prepare(*args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return manifest, signatures

    async def run(session: Any, job_: Job, owner: Any, attempt: Any, command: list[str], **kw: Any):
        (Path(command[3]) / "style.json").write_text(json.dumps(response), encoding="utf-8")
        return exit_code, ""

    monkeypatch.setattr(ai_style, "_prepare", prepare)
    monkeypatch.setattr(ai_style, "_run_while_owned", run)
    monkeypatch.setattr(ai_style, "_still_owned", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "start", AsyncMock())
    succeed = AsyncMock(side_effect=lambda session, job, payload: job)
    monkeypatch.setattr(jobs, "succeed", succeed)
    fail = AsyncMock(side_effect=lambda session, job, **kw: job)
    monkeypatch.setattr(jobs, "fail", fail)
    after = AsyncMock()
    monkeypatch.setattr(ai_loop, "after_style", after)
    settings = Settings(cad_review_ssh_config="/ssh/config", cad_engine_python="/engine/python")
    await execute_ai_style(AsyncMock(), job, AsyncMock(), settings)
    return succeed, fail, after


async def test_execute_stores_classes_with_package_numbers_and_continues_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    succeed, fail, after = await _run_execute(
        monkeypatch, _response(_item("ghost"), _item(FILL["id"]), _item(HATCH["id"], "masonry"))
    )
    fail.assert_not_awaited()
    stored = succeed.call_args.kwargs["payload"]["ai_style"]
    assert [(row["signature_id"], row["class_name"]) for row in stored["classes"]] == [
        (HATCH["id"], "masonry")
    ]
    assert stored["classes"][0]["pen_pt"] == 0.28 and stored["classes"][0]["color"] == [
        0.145,
        0.0,
        0.29,
    ]
    assert len(stored["dropped"]) == 2 and stored["limitations"] == ["без легенды"]
    assert stored["usage"]["cost_usd"] == 0.4 and stored["prompt_version"] == 1
    after.assert_awaited_once()


@pytest.mark.parametrize(
    "response",
    [
        {**_response(), "report": {"classes": "x", "limitations": []}},
        # Числа подписи от модели не принимаются: лишние поля отклоняют весь отчёт.
        _response({**_item(HATCH["id"]), "pen_pt": 99}),
        {k: v for k, v in _response().items() if k != "report"},
    ],
)
async def test_execute_rejects_bad_response_without_continuing(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    succeed, fail, after = await _run_execute(monkeypatch, response)
    succeed.assert_not_awaited()
    fail.assert_awaited_once()
    after.assert_not_awaited()


@pytest.mark.parametrize(
    ("code", "error"),
    [(124, "JOB_TIMEOUT"), (255, "CAD_ENGINE_UNAVAILABLE"), (3, "CAD_ENGINE_FAILED")],
)
async def test_execute_maps_exit_codes_to_failure_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch, code: int, error: str
) -> None:
    succeed, fail, after = await _run_execute(monkeypatch, _response(), exit_code=code)
    succeed.assert_not_awaited()
    after.assert_not_awaited()
    assert fail.call_args.kwargs["error_code"] == error


# ------------------------------------------------------------------ подготовка пакета


def _pilot(project_id: uuid.UUID | None) -> Settings:
    assert project_id is not None
    return _loop_settings(project_id)


async def _prepared(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    *,
    signatures: bool = True,
    prompt: bool = True,
) -> tuple[Job, Job]:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    document = _document(HATCH, FILL)
    # `add_pdf` считает sha иначе, чем хранилище: исполнитель сверяет по байтам объекта.
    ctx.revision.source_sha256 = hashlib.sha256(
        fake_storage.objects[ctx.revision.storage_key]
    ).hexdigest()
    artifacts = [{"name": DXF_NAME, "sha256": DXF, "key": "k"}]
    if signatures:
        key = cad_service.artifact_storage_key(ctx.revision.id, ctx.convert.id, 1, SIGNATURES_NAME)
        fake_storage.objects[key] = document
        artifacts.append(
            {"name": SIGNATURES_NAME, "sha256": hashlib.sha256(document).hexdigest(), "key": key}
        )
    ctx.convert.payload = {
        **ctx.convert.payload,
        "cad_result": {**ctx.convert.payload["cad_result"], "artifacts": artifacts},
    }
    if prompt:
        db_session.add(
            AiPromptVersion(role="style", version=1, text="Промт оформления\n", status="active")
        )
    await db_session.commit()
    job = Job(
        id=uuid.uuid4(),
        project_id=ctx.project_id,
        workspace_id=ctx.workspace_id,
        job_type=JobType.CAD_AI_REVIEW,
        status=JobStatus.RUNNING,
        attempt=1,
        payload={
            "role": "style",
            "cad_job_id": str(ctx.convert.id),
            "cad_attempt": 1,
            "revision_id": str(ctx.revision.id),
            "page_index": 0,
            "pdf_page": 1,
            "view": 1,
            "iteration": 1,
            "model": "claude-opus-5-5",
            "sources": {"vor": "/pilot/vor.md"},
        },
    )
    return job, ctx.convert


async def test_prepare_writes_the_package_with_prompt_signatures_and_manifest(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    job, convert = await _prepared(db_session, build_api, fake_storage, workspace_id)
    settings = _pilot(job.project_id)
    manifest, signatures = await ai_style._prepare(
        db_session, job, fake_storage, settings, tmp_path
    )
    assert set(signatures) == {HATCH["id"], FILL["id"]}
    assert (tmp_path / "prompt.txt").read_bytes() == "Промт оформления\n".encode()
    assert (tmp_path / "input.pdf").is_file() and (tmp_path / "hatch_signatures.json").is_file()
    schema = json.loads((tmp_path / "schema.json").read_text(encoding="utf-8"))
    assert set(schema["$defs"]["AiStyleClass"]["properties"]) == {
        "signature_id",
        "class",
        "confidence",
        "evidence",
    }
    written = json.loads((tmp_path / "manifest.json").read_bytes())
    assert written == manifest
    assert (
        manifest["sources"] == {"vor": "/pilot/vor.md"} and manifest["model"] == "claude-opus-5-5"
    )
    assert manifest["pdf_page"] == 1 and manifest["view"] == 1
    assert manifest["signatures_sha256"] == hashlib.sha256(_document(HATCH, FILL)).hexdigest()
    assert manifest["view_zone"] is None  # кадр вида не подтверждён: вся страница
    assert manifest["prompt_version"] == 1 and job.payload["prompt_version"] == 1
    assert convert.id == uuid.UUID(manifest["cad_job_id"])


async def test_prepare_refuses_outside_the_pilot_and_without_signatures_or_prompt(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    job, _ = await _prepared(db_session, build_api, fake_storage, workspace_id)
    with pytest.raises(CadError, match="недоступно для этого проекта"):
        await ai_style._prepare(db_session, job, fake_storage, clean_settings(), tmp_path)
    with pytest.raises(CadError, match="недоступно для этого проекта"):
        await ai_style._prepare(db_session, job, fake_storage, _pilot(uuid.uuid4()), tmp_path)
    assert not (tmp_path / "manifest.json").exists()

    missing, _ = await _prepared(
        db_session, build_api, fake_storage, workspace_id, signatures=False, prompt=False
    )
    with pytest.raises(CadError, match=r"hatch_signatures\.json"):
        await ai_style._prepare(
            db_session, missing, fake_storage, _pilot(missing.project_id), tmp_path
        )


async def test_prepare_refuses_without_an_active_prompt(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    job, _ = await _prepared(db_session, build_api, fake_storage, workspace_id, prompt=False)
    with pytest.raises(CadError, match="Нет активного промта"):
        await ai_style._prepare(db_session, job, fake_storage, _pilot(job.project_id), tmp_path)


async def test_prepare_maps_unavailable_storage_to_a_cad_error(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, _ = await _prepared(db_session, build_api, fake_storage, workspace_id)
    monkeypatch.setattr(
        cad_walls_zones,
        "_artifact_json",
        AsyncMock(side_effect=http_error(ErrorCode.STORAGE_UNAVAILABLE)),
    )
    with pytest.raises(CadError) as raised:
        await ai_style._prepare(db_session, job, fake_storage, _pilot(job.project_id), tmp_path)
    assert raised.value.code is ErrorCode.STORAGE_UNAVAILABLE
