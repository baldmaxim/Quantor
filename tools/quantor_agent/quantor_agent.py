#!/usr/bin/env python3
"""Клиент API портала Quantor для агентов и скриптов: один файл, только стандартная библиотека Python 3.9+.

    quantor_agent.py projects [--search ТЕКСТ]
    quantor_agent.py coordination --project <id|название> [--format ifc|json] [-o файл]
    quantor_agent.py base --project <id|название> [--out папка]
    quantor_agent.py push --project <id|название> ARCH.ifc [ещё.ifc ...] [--no-build] [--rebuild]
    quantor_agent.py status --project <id|название>
    quantor_agent.py job <id задания> [--wait секунд]
    quantor_agent.py openapi [-o файл]

Адрес портала - `QUANTOR_URL` или `--url`. Токен (`qtk_…`, личный, создаётся человеком в профиле портала,
«Для чего токен») - из `QUANTOR_TOKEN` или файла `--token-file` (по умолчанию ~/.config/quantor/token, права
600). Аргументом токен не передаётся и не печатается. Права токена - в пределах роли владельца и его
областей: `read` (чтение: проекты, база, координационный файл, задания, модель), `upload` (+ загрузка IFC и
сборка модели), `tender` (расчёты TENDER). Новый выпуск базы делает только человек.

`--project` - id проекта или его точное название в портале. `--json` перед командой - последней строкой
сводка JSON для программы.

Коды выхода: 0 - готово; 1 - нет того, что просили, или сборка модели не удалась; 2 - неверный вызов или файл;
3 - портал отказал или недоступен; 4 - не дождались задания.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import stat
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

EXIT_OK, EXIT_MISSING, EXIT_USAGE, EXIT_PORTAL, EXIT_TIMEOUT = 0, 1, 2, 3, 4
DEFAULT_TOKEN_FILE = "~/.config/quantor/token"
DEFAULT_MAX_MB = 100
DEFAULT_WAIT_SECONDS = 1800
POLL_SECONDS = 5.0
CHUNK = 1024 * 1024
PAGE = 200
MAX_BASE_BYTES = 200 * 1024 * 1024
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class PortalError(Exception):
    """Портал ответил отказом или недоступен; `code` - машинный код причины портала."""

    def __init__(self, message: str, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class UsageError(Exception):
    """Неверный вызов: нет адреса, токена, файла."""


def read_token(token_file: str) -> str:
    """Токен из окружения или файла 600; ни в выводе, ни в аргументах его нет."""
    env = os.environ.get("QUANTOR_TOKEN", "").strip()
    if env:
        return env
    path = Path(os.path.expanduser(token_file))
    if not path.is_file():
        raise UsageError(
            f"Нет токена: задайте QUANTOR_TOKEN или положите токен в {path} (chmod 600). "
            "Токен создаёт человек в профиле портала."
        )
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise UsageError(f"Права файла токена {path} шире 600: chmod 600 {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise UsageError(f"Файл токена {path} пуст")
    return token


class Portal:
    """Минимальный клиент API портала: токен в заголовке, ответы JSON, без сторонних пакетов."""

    def __init__(self, base_url: str, token: str, timeout: float = 120.0) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise UsageError(f"Неверный адрес портала: {base_url!r}")
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise UsageError("Токен по http не отправляется: нужен https (http - только localhost)")
        self.scheme, self.netloc = parts.scheme, parts.netloc
        self.prefix = parts.path.rstrip("/")
        self._token = token
        self.timeout = timeout

    def _connect(self) -> http.client.HTTPConnection:
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.netloc, timeout=self.timeout)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "quantor-agent/1.0",
        }
        headers.update(extra or {})
        return headers

    @staticmethod
    def _fail(response: http.client.HTTPResponse, raw: bytes) -> PortalError:
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        detail = data.get("detail") if isinstance(data, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else None
        return PortalError(message or f"HTTP {response.status}", code, response.status)

    def request(self, method: str, path: str, body: Any = None, params: dict | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        headers = self._headers({"Content-Type": "application/json"} if payload else None)
        target = self.prefix + path + (("?" + urlencode(params)) if params else "")
        conn = self._connect()
        try:
            conn.request(method, target, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            if not 200 <= response.status < 300:
                raise self._fail(response, raw)
            return json.loads(raw) if raw else None
        except OSError as error:
            raise PortalError(f"Портал недоступен: {error}") from error
        finally:
            conn.close()

    def download(self, path: str, target: Path, limit: int) -> tuple[str, dict[str, str]]:
        """Ответ в файл потоком; возвращает sha256 и заголовки (в нижнем регистре)."""
        conn = self._connect()
        try:
            conn.request("GET", self.prefix + path, headers=self._headers({"Accept": "*/*"}))
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                raise self._fail(response, response.read())
            headers = {k.lower(): v for k, v in response.getheaders()}
            digest, size = hashlib.sha256(), 0
            with target.open("wb") as out:
                while chunk := response.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise PortalError(f"Ответ больше {limit // CHUNK} МБ: не принимаю")
                    digest.update(chunk)
                    out.write(chunk)
            return digest.hexdigest(), headers
        except OSError as error:
            raise PortalError(f"Портал недоступен: {error}") from error
        finally:
            conn.close()

    def upload(self, path: str, file: Path, fields: dict[str, str]) -> Any:
        """multipart/form-data с потоковой отправкой файла: память не зависит от его размера."""
        boundary = uuid.uuid4().hex
        head = b""
        for name, value in fields.items():
            head += (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode()
        filename = file.name.replace("\\", "_").replace('"', "_")
        head += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        headers = self._headers(
            {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(head) + file.stat().st_size + len(tail)),
            }
        )
        conn = self._connect()
        try:
            conn.putrequest("POST", self.prefix + path)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders()
            conn.send(head)
            with file.open("rb") as handle:
                while chunk := handle.read(CHUNK):
                    conn.send(chunk)
            conn.send(tail)
            response = conn.getresponse()
            raw = response.read()
            if not 200 <= response.status < 300:
                raise self._fail(response, raw)
            return json.loads(raw) if raw else None
        except OSError as error:
            raise PortalError(f"Портал недоступен: {error}") from error
        finally:
            conn.close()


def _say(text: str) -> None:
    print(text, flush=True)


def resolve_project(portal: Portal, value: str) -> tuple[str, str]:
    """(id, название) по id или точному названию проекта; несколько или ни одного - отказ."""
    if UUID_RE.match(value):
        return value, value
    page = portal.request("GET", "/api/v1/projects", params={"search": value, "limit": 50})
    items = page.get("items", []) if isinstance(page, dict) else []
    want = value.strip().casefold()
    exact = [p for p in items if str(p.get("name", "")).strip().casefold() == want]
    if len(exact) == 1:
        return str(exact[0]["id"]), str(exact[0]["name"])
    if len(exact) > 1:
        ids = ", ".join(str(p["id"]) for p in exact)
        raise UsageError(f"Несколько проектов «{value}»: {ids}. Укажите id в --project")
    near = "; ".join(str(p.get("name")) for p in items[:8]) or "ничего похожего"
    raise UsageError(f"Проект «{value}» не найден (похожие: {near}). Укажите id или точное название")


# ------------------------------------------------------------------------------------ команды


def cmd_projects(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    params: dict[str, Any] = {"limit": PAGE}
    if args.search:
        params["search"] = args.search
    page = portal.request("GET", "/api/v1/projects", params=params)
    items = page.get("items", []) if isinstance(page, dict) else []
    for item in items:
        _say(f"{item.get('id')}  {item.get('name')}")
    return EXIT_OK, [{"id": i.get("id"), "name": i.get("name")} for i in items]


def cmd_coordination(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    project_id, name = resolve_project(portal, args.project)
    with tempfile.TemporaryDirectory(prefix="quantor_agent_") as tmp:
        temp = Path(tmp) / f"coordination.{args.format}"
        try:
            _, headers = portal.download(
                f"/api/v1/projects/{project_id}/tender/base/coordination.{args.format}",
                temp,
                MAX_BASE_BYTES,
            )
        except PortalError as error:
            if error.status == 404:
                _say(f"Координационного файла нет: {error}")
                return EXIT_MISSING, None
            raise
        release = headers.get("x-quantor-base-release", "?")
        target = Path(args.output or f"coordination-{release}.{args.format}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(temp.read_bytes())
    _say(f"Координационный файл «{name}», выпуск базы №{release}: {target}")
    return EXIT_OK, {"project_id": project_id, "release": release, "file": str(target)}


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    for name in names:
        if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name:
            raise PortalError(f"В пакете опасное имя файла: {name!r}")
    return names


def cmd_base(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    project_id, name = resolve_project(portal, args.project)
    rows = portal.request("GET", f"/api/v1/projects/{project_id}/tender/base/releases") or []
    live = [r for r in rows if not r.get("revoked_at")]
    if not live:
        _say(f"У проекта «{name}» нет действующих выпусков базы: их выпускает человек кнопкой «Выпустить базу».")
        return EXIT_MISSING, None
    release = max(live, key=lambda r: int(r["number"]))
    number = int(release["number"])
    dest = Path(args.out) / f"выпуск-{number}"
    manifest = dest / "manifest.json"
    if manifest.is_file() and hashlib.sha256(manifest.read_bytes()).hexdigest() == release["manifest_sha256"]:
        state = "уже был"
    else:
        with tempfile.TemporaryDirectory(prefix="quantor_agent_") as tmp:
            zip_path = Path(tmp) / "base.zip"
            sha, _ = portal.download(
                f"/api/v1/projects/{project_id}/tender/base/releases/{release['id']}/download",
                zip_path,
                MAX_BASE_BYTES,
            )
            if sha != release["package_sha256"]:
                raise PortalError(f"Пакет выпуска №{number} не совпал с sha256 портала: не распаковываю")
            with zipfile.ZipFile(zip_path) as archive:
                names = _safe_members(archive)
                dest.mkdir(parents=True, exist_ok=True)
                for member in names:
                    if member.endswith("/"):
                        continue
                    out = dest / member
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(archive.read(member))
        state = "скачан"
    coord = dest / "coordination.ifc"
    _say(f"База «{name}»: выпуск №{number} {state}: {dest}")
    _say(f"Координационный файл: {coord}" if coord.is_file() else "В выпуске нет координационного файла (до 2026-11-18).")
    return EXIT_OK, {
        "project_id": project_id,
        "release": number,
        "dir": str(dest),
        "coordination_ifc": str(coord) if coord.is_file() else None,
    }


def _documents(portal: Portal, project: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = portal.request(
            "GET", f"/api/v1/projects/{project}/documents", params={"limit": PAGE, "offset": offset}
        )
        batch = page.get("items", []) if isinstance(page, dict) else []
        items += batch
        offset += len(batch)
        if not batch or offset >= int(page.get("total", offset)):
            return items


def _existing_ifc(documents: list[dict[str, Any]], filename: str) -> str | None:
    """Документ IFC проекта с тем же именем файла: новая ревизия вместо второго документа."""
    for item in documents:
        if item.get("document_kind") == "ifc" and item.get("display_name") == filename:
            return str(item["id"])
    return None


def _check_ifc(path: Path, max_mb: int) -> None:
    if not path.is_file():
        raise UsageError(f"Нет файла: {path}")
    if path.suffix.lower() != ".ifc":
        raise UsageError(f"Не IFC: {path.name}")
    size_mb = path.stat().st_size / CHUNK
    if size_mb > max_mb:
        raise UsageError(
            f"{path.name}: {size_mb:.0f} МБ больше предела {max_mb} МБ. Сделайте облегчённый IFC "
            "(tools/light_ifc/light_ifc.py) или поднимите предел ключом --max-mb."
        )


def _describe(job: dict[str, Any]) -> str:
    stage = f", {job['stage']}" if job.get("stage") else ""
    return f"{job.get('status', '?')}{stage}"


def _wait_import(portal: Portal, project: str, job_id: str, deadline: float) -> dict[str, Any] | None:
    last = ""
    while time.monotonic() < deadline:
        try:
            job = portal.request("GET", f"/api/v1/projects/{project}/model/imports/latest")
        except PortalError as error:
            if error.status != 404:
                raise
            job = {}
        if job.get("job_id") == job_id:
            line = _describe(job)
            if line != last:
                _say(f"  задание: {line}")
                last = line
            if job.get("status") in ("succeeded", "failed", "cancelled"):
                return job
        time.sleep(POLL_SECONDS)
    return None


def cmd_push(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    files = [Path(item) for item in args.files]
    for path in files:
        _check_ifc(path, args.max_mb)
    project_id, _ = resolve_project(portal, args.project)
    documents = _documents(portal, project_id)
    changed = 0
    for path in files:
        document_id = _existing_ifc(documents, path.name)
        fields = {"document_id": document_id} if document_id else {}
        _say(f"Загрузка {path.name} ({path.stat().st_size / CHUNK:.1f} МБ)")
        result = portal.upload(f"/api/v1/projects/{project_id}/uploads", path, fields)
        if result.get("is_duplicate"):
            _say("  такой файл уже загружен, ревизия не создана")
        else:
            changed += 1
            where = "новая ревизия документа" if document_id else "новый документ"
            _say(f"  {where}: {result['document']['id']}")
    if args.no_build:
        return EXIT_OK, {"uploaded": changed}
    if changed == 0 and not args.rebuild:
        _say("Новых ревизий нет, модель не пересобирается (ключ --rebuild - собрать всё равно).")
        return EXIT_OK, {"uploaded": 0, "build": None}
    job = portal.request("POST", f"/api/v1/projects/{project_id}/model/imports", {})
    _say(f"Сборка модели: задание {job['job_id']}, входных файлов {job.get('inputs')}")
    done = _wait_import(portal, project_id, str(job["job_id"]), time.monotonic() + args.wait)
    if done is None:
        _say("Не дождались задания: проверьте страницу «Модель» проекта.")
        return EXIT_TIMEOUT, {"job_id": job["job_id"]}
    if done.get("status") != "succeeded":
        reason = done.get("error_message") or done.get("error_code") or "причина не указана"
        _say(f"Сборка модели не удалась: {reason}")
        return EXIT_MISSING, {"job_id": job["job_id"], "status": done.get("status")}
    _say(f"Готово. Версия модели: {done.get('version_id')}.")
    return EXIT_OK, {"job_id": job["job_id"], "version_id": done.get("version_id")}


def cmd_status(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    project_id, name = resolve_project(portal, args.project)
    try:
        job = portal.request("GET", f"/api/v1/projects/{project_id}/model/imports/latest")
    except PortalError as error:
        if error.status != 404:
            raise
        job = None
    versions = portal.request("GET", f"/api/v1/projects/{project_id}/model/versions") or {}
    items = versions.get("items", []) if isinstance(versions, dict) else []
    newest = items[0] if items else None
    _say(f"Проект «{name}»: последняя сборка - {_describe(job) if job else 'не было'}")
    if newest:
        _say(f"Новейшая версия модели: №{newest.get('number')} ({newest.get('status')}), id {newest.get('id')}")
    return EXIT_OK, {"project_id": project_id, "import": job, "versions": len(items), "newest": newest}


def cmd_job(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    deadline = time.monotonic() + max(args.wait, 0)
    last = ""
    while True:
        job = portal.request("GET", f"/api/v1/jobs/{quote(args.job_id)}")
        line = _describe(job)
        if line != last:
            _say(f"задание {args.job_id}: {line}")
            last = line
        if job.get("status") in ("succeeded", "failed", "cancelled") or args.wait <= 0:
            return EXIT_OK, job
        if time.monotonic() >= deadline:
            return EXIT_TIMEOUT, job
        time.sleep(POLL_SECONDS)


def cmd_openapi(portal: Portal, args: argparse.Namespace) -> tuple[int, Any]:
    spec = portal.request("GET", "/api/v1/meta/openapi.json")
    target = Path(args.output or "quantor-openapi.json")
    target.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    _say(f"Описание API ({len(spec.get('paths', {}))} адресов): {target}")
    return EXIT_OK, {"file": str(target), "paths": len(spec.get("paths", {}))}


# ------------------------------------------------------------------------------------ CLI


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="quantor_agent", description="Клиент API портала Quantor для агентов"
    )
    root.add_argument("--url", default=os.environ.get("QUANTOR_URL", ""), help="адрес портала")
    root.add_argument("--token-file", default=DEFAULT_TOKEN_FILE, help="файл токена (права 600)")
    root.add_argument("--json", action="store_true", help="последней строкой - сводка JSON")
    sub = root.add_subparsers(dest="command", required=True)

    p = sub.add_parser("projects", help="проекты пространства")
    p.add_argument("--search", help="часть названия")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("coordination", help="координационный файл последнего выпуска базы")
    p.add_argument("--project", required=True, help="id или точное название проекта")
    p.add_argument("--format", choices=("ifc", "json"), default="ifc")
    p.add_argument("-o", "--output", help="куда сохранить (по умолчанию coordination-<выпуск>.<формат>)")
    p.set_defaults(func=cmd_coordination)

    p = sub.add_parser("base", help="последний выпуск базы объекта целиком")
    p.add_argument("--project", required=True, help="id или точное название проекта")
    p.add_argument("--out", default="Базы", help="папка, куда распаковать выпуск-<N>")
    p.set_defaults(func=cmd_base)

    p = sub.add_parser("push", help="загрузить IFC и собрать модель здания")
    p.add_argument("--project", required=True, help="id или точное название проекта")
    p.add_argument("files", nargs="+", help="файл(ы) IFC, по файлу на дисциплину")
    p.add_argument("--no-build", action="store_true", help="только загрузить, модель не собирать")
    p.add_argument("--rebuild", action="store_true", help="собрать модель, даже если ревизий нет")
    p.add_argument("--max-mb", type=int, default=DEFAULT_MAX_MB, help="предел размера файла, МБ")
    p.add_argument("--wait", type=int, default=DEFAULT_WAIT_SECONDS, help="сколько ждать сборку, с")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("status", help="последняя сборка и новейшая версия модели")
    p.add_argument("--project", required=True, help="id или точное название проекта")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("job", help="состояние задания (и ожидание)")
    p.add_argument("job_id")
    p.add_argument("--wait", type=int, default=0, help="ждать окончания, секунд (0 - не ждать)")
    p.set_defaults(func=cmd_job)

    p = sub.add_parser("openapi", help="описание API портала (JSON)")
    p.add_argument("-o", "--output", help="куда сохранить (по умолчанию quantor-openapi.json)")
    p.set_defaults(func=cmd_openapi)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not args.url:
            raise UsageError("Нужен адрес портала: --url или QUANTOR_URL")
        portal = Portal(args.url, read_token(args.token_file))
        code, summary = args.func(portal, args)
    except UsageError as error:
        print(f"Неверный вызов: {error}", file=sys.stderr)
        return EXIT_USAGE
    except PortalError as error:
        hint = " Проверьте токен и его области («Для чего токен»)." if error.status in (401, 403) else ""
        print(f"Портал отказал: {error}{hint}", file=sys.stderr)
        return EXIT_PORTAL
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
