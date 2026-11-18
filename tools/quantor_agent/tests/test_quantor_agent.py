"""Клиент агента против местного сервера-заглушки портала: команды, токен, проверки, коды выхода."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quantor_agent as qa

TOKEN = "qtk_" + "b" * 40
PROJECT = "11732c7f-f80c-4a2f-9314-9a39a149cdd3"
NAME = "341. Капельский (СОЮЗ)"


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class Stub:
    def __init__(self) -> None:
        manifest = json.dumps({"schema": "quantor.object_base.v1"}).encode()
        self.package = _zip(
            {"manifest.json": manifest, "coordination.ifc": b"ISO-10303-21;\n"}
        )
        self.releases = [
            {
                "id": "r2",
                "number": 2,
                "revoked_at": "2026-11-18T10:00:00Z",
                "package_sha256": "x",
                "manifest_sha256": "x",
            },
            {
                "id": "r1",
                "number": 1,
                "revoked_at": None,
                "package_sha256": hashlib.sha256(self.package).hexdigest(),
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            },
        ]
        self.projects = [
            {"id": PROJECT, "name": NAME},
            {"id": "other", "name": "328 Остров"},
        ]
        self.documents: list[dict[str, Any]] = [
            {"id": "doc-arch", "document_kind": "ifc", "display_name": "ARCH.ifc"}
        ]
        self.latest = [
            {"job_id": "job-1", "status": "queued"},
            {"job_id": "job-1", "status": "running", "stage": "model_ifc_import"},
            {"job_id": "job-1", "status": "succeeded", "version_id": "ver-2"},
        ]
        self.coordination: bytes | None = b"ISO-10303-21;\nDATA;\n"
        self.requests: list[tuple[str, str, str | None]] = []


def make_handler(stub: Stub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            return

        def _reply(
            self, status: int, body: Any, ctype: str = "application/json", headers=None
        ) -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            stub.requests.append(
                (self.command, self.path, self.headers.get("Authorization"))
            )
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._reply(
                    401, {"detail": {"code": "CREDENTIAL_INVALID", "message": "нет"}}
                )
                return False
            return True

        def do_GET(self) -> None:
            if not self._authorized():
                return
            url = urlsplit(self.path)
            path, query = url.path, parse_qs(url.query)
            base = f"/api/v1/projects/{PROJECT}"
            if path == "/api/v1/projects":
                search = (query.get("search") or [""])[0].casefold()
                items = [p for p in stub.projects if search in p["name"].casefold()]
                return self._reply(200, {"items": items, "total": len(items)})
            if path == f"{base}/tender/base/releases":
                return self._reply(200, stub.releases)
            if path == f"{base}/tender/base/releases/r1/download":
                return self._reply(200, stub.package, "application/zip")
            if path.startswith(f"{base}/tender/base/coordination."):
                if stub.coordination is None:
                    return self._reply(
                        404, {"detail": {"code": "NOT_FOUND", "message": "нет выпуска"}}
                    )
                return self._reply(
                    200,
                    stub.coordination,
                    "application/x-step",
                    {"X-Quantor-Base-Release": "1"},
                )
            if path == f"{base}/documents":
                return self._reply(
                    200, {"items": stub.documents, "total": len(stub.documents)}
                )
            if path == f"{base}/model/imports/latest":
                return self._reply(
                    200, stub.latest.pop(0) if len(stub.latest) > 1 else stub.latest[0]
                )
            if path == f"{base}/model/versions":
                return self._reply(
                    200,
                    {"items": [{"id": "ver-2", "number": 2, "status": "candidate"}]},
                )
            if path == "/api/v1/jobs/job-9":
                return self._reply(200, {"id": "job-9", "status": "succeeded"})
            if path == "/api/v1/meta/openapi.json":
                return self._reply(
                    200, {"openapi": "3.1.0", "paths": {"/api/v1/projects": {}}}
                )
            return self._reply(404, {"detail": {"code": "NOT_FOUND", "message": path}})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            if self.path == f"/api/v1/projects/{PROJECT}/uploads":
                revision = b'name="document_id"' in body
                return self._reply(
                    201,
                    {
                        "document": {"id": "doc-arch" if revision else "doc-new"},
                        "is_duplicate": False,
                    },
                )
            if self.path == f"/api/v1/projects/{PROJECT}/model/imports":
                return self._reply(
                    202, {"job_id": "job-1", "status": "queued", "inputs": 1}
                )
            return self._reply(
                404, {"detail": {"code": "NOT_FOUND", "message": self.path}}
            )

    return Handler


@pytest.fixture()
def stub() -> Iterator[Stub]:
    yield Stub()


@pytest.fixture()
def server(stub: Stub) -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stub))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTOR_TOKEN", TOKEN)
    monkeypatch.setattr(qa, "POLL_SECONDS", 0.0)


def run(server: str, *args: str) -> int:
    return qa.main(["--url", server, *args])


def test_projects_and_exact_name_resolution(server: str, stub: Stub, capsys) -> None:
    assert run(server, "projects") == 0
    out = capsys.readouterr().out
    assert NAME in out and "328 Остров" in out
    portal = qa.Portal(server, TOKEN)
    assert qa.resolve_project(portal, NAME) == (PROJECT, NAME)
    stub.projects.append({"id": "dup", "name": NAME})
    with pytest.raises(qa.UsageError, match="Несколько проектов"):
        qa.resolve_project(portal, NAME)
    with pytest.raises(qa.UsageError, match="не найден"):
        qa.resolve_project(portal, "Нет такого")


def test_coordination_saved_with_release_number(
    server: str, tmp_path: Path, capsys
) -> None:
    target = tmp_path / "c.ifc"
    assert (
        run(server, "--json", "coordination", "--project", NAME, "-o", str(target)) == 0
    )
    assert target.read_bytes().startswith(b"ISO-10303-21;")
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["release"] == "1" and summary["file"] == str(target)


def test_coordination_missing_is_exit_1(
    server: str, stub: Stub, tmp_path: Path
) -> None:
    stub.coordination = None
    assert (
        run(server, "coordination", "--project", PROJECT, "-o", str(tmp_path / "c.ifc"))
        == 1
    )


def test_base_takes_newest_live_release_checks_sha_and_skips_repeat(
    server: str, stub: Stub, tmp_path: Path, capsys
) -> None:
    out = tmp_path / "Базы"
    assert run(server, "base", "--project", PROJECT, "--out", str(out)) == 0
    assert (out / "выпуск-1" / "coordination.ifc").is_file()  # отозванный №2 пропущен
    stub.requests.clear()
    assert run(server, "base", "--project", PROJECT, "--out", str(out)) == 0
    assert "уже был" in capsys.readouterr().out
    assert not any(path.endswith("/download") for _, path, _ in stub.requests)


def test_base_package_sha_mismatch_is_refused(
    server: str, stub: Stub, tmp_path: Path
) -> None:
    stub.releases[1]["package_sha256"] = "0" * 64
    assert run(server, "base", "--project", PROJECT, "--out", str(tmp_path)) == 3
    assert not (tmp_path / "выпуск-1").exists()


def test_push_revision_then_build_waits_for_version(
    server: str, tmp_path: Path, capsys
) -> None:
    ifc = tmp_path / "ARCH.ifc"
    ifc.write_bytes(b"ISO-10303-21;\n")
    assert run(server, "--json", "push", "--project", NAME, str(ifc)) == 0
    out = capsys.readouterr().out
    assert "новая ревизия документа: doc-arch" in out
    assert json.loads(out.strip().splitlines()[-1])["version_id"] == "ver-2"


def test_push_refuses_non_ifc_and_oversize(server: str, tmp_path: Path) -> None:
    other = tmp_path / "a.pdf"
    other.write_bytes(b"%PDF")
    assert run(server, "push", "--project", PROJECT, str(other)) == 2
    big = tmp_path / "B.ifc"
    big.write_bytes(b"x" * (2 * 1024 * 1024))
    assert run(server, "push", "--project", PROJECT, "--max-mb", "1", str(big)) == 2


def test_status_job_and_openapi(server: str, tmp_path: Path, capsys) -> None:
    assert run(server, "status", "--project", PROJECT) == 0
    assert run(server, "job", "job-9") == 0
    spec = tmp_path / "spec.json"
    assert run(server, "openapi", "-o", str(spec)) == 0
    assert json.loads(spec.read_text(encoding="utf-8"))["openapi"] == "3.1.0"
    assert "Новейшая версия модели: №2" in capsys.readouterr().out


def test_token_never_printed_and_bad_token_is_portal_refusal(
    server: str, stub: Stub, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    assert run(server, "projects") == 0
    monkeypatch.setenv("QUANTOR_TOKEN", "qtk_wrong")
    assert run(server, "projects") == 3
    captured = capsys.readouterr()
    assert (
        TOKEN not in captured.out + captured.err
        and "qtk_wrong" not in captured.out + captured.err
    )
    assert "Проверьте токен" in captured.err


def test_token_file_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTOR_TOKEN")
    with pytest.raises(qa.UsageError, match="Нет токена"):
        qa.read_token(str(tmp_path / "нет"))
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n")
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(qa.UsageError, match="chmod 600"):
            qa.read_token(str(path))
        path.chmod(0o600)
    assert qa.read_token(str(path)) == TOKEN


def test_plain_http_only_to_localhost() -> None:
    with pytest.raises(qa.UsageError, match="https"):
        qa.Portal("http://portal.example", TOKEN)
    qa.Portal("https://portal.example", TOKEN)
    qa.Portal("http://localhost:8000", TOKEN)
