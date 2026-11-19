"""MCP-сервер портала: инструменты Quantor для ИИ-чатов и агентов (Model Context Protocol).

Транспорт - Streamable HTTP без потока событий: каждый запрос JSON-RPC 2.0 приходит POST на
`/api/v1/mcp`, ответ - JSON (спецификация это допускает). Сеансов нет: запрос самодостаточен.

Вход - только личный токен `qtk_…` в заголовке `Authorization`. Каждый инструмент вызывает обычные
адреса `/api/v1/…` того же приложения с тем же заголовком (внутренний вызов ASGI, без сети), поэтому
права те же, что у токена: роль владельца, суженная областями (`read`, `upload`, `tender`). Логики
доступа здесь нет - её проверяют сами адреса.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "quantor", "title": "Quantor — портал объекта", "version": "1.0"}
INSTRUCTIONS = (
    "Портал Quantor: проекты (тендерные объекты), документы, модель здания и координационный "
    "файл - общая сетка осей и этажи объекта, к которым привязываются все разделы. "
    "Перед работой с объектом "
    "возьми координационный файл (get_coordination). «Отправить в 3D» - send_ifc_to_3d: IFC своей "
    "дисциплины новой ревизией документа того же имени, затем сборка модели (4-9 минут, следить - "
    "job_status или model_status). Отправляй только облегчённые IFC (через MCP - до 3 МБ). "
    "Новый выпуск "
    "базы делает только человек. Проект можно называть точным названием или id."
)
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
MAX_MCP_IFC_BYTES = 3 * 1024 * 1024
# Пачка JSON-RPC больше - отказ: каждый вызов инструмента идёт в портал (а get_coordination
# читает ZIP выпуска), и одна пачка не должна занимать сервер.
MAX_BATCH = 20
# Сколько ждать один инструмент: внутренний вызов ASGI тайм-аутов httpx не знает.
TOOL_TIMEOUT_SECONDS = 120.0
DOCUMENTS_PAGE = 200

# Коды ошибок JSON-RPC 2.0
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


class CallError(Exception):
    """Адрес портала отказал: код HTTP и суть ответа."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class ToolInputError(Exception):
    """Неверные аргументы инструмента (их заполнил агент) - ответ isError, не сбой протокола."""


class Caller:
    """Вызовы адресов портала от имени токена: тот же заголовок, то же приложение."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @staticmethod
    def _error(response: httpx.Response) -> CallError:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("code") or response.status_code)
        else:
            message = str(detail or f"HTTP {response.status_code}")
        if response.status_code == 403:
            message += " (у токена нет нужной области или права у роли)"
        return CallError(response.status_code, message)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise CallError(response.status_code, "портал ответил не JSON") from None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.client.get(path, params=params)
        if response.status_code >= 400:
            raise self._error(response)
        return self._json(response)

    async def get_raw(self, path: str) -> httpx.Response:
        response = await self.client.get(path)
        if response.status_code >= 400:
            raise self._error(response)
        return response

    async def post(self, path: str, body: Any) -> Any:
        response = await self.client.post(path, json=body)
        if response.status_code >= 400:
            raise self._error(response)
        return self._json(response) if response.content else None

    async def upload(self, path: str, filename: str, data: bytes, fields: dict[str, str]) -> Any:
        response = await self.client.post(
            path, data=fields, files={"file": (filename, data, "application/octet-stream")}
        )
        if response.status_code >= 400:
            raise self._error(response)
        return self._json(response)


@dataclass
class ToolResult:
    text: str
    data: Any = None
    is_error: bool = False

    def as_mcp(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "content": [{"type": "text", "text": self.text}],
            "isError": self.is_error,
        }
        if self.data is not None and isinstance(self.data, dict):
            out["structuredContent"] = self.data
        return out


Handler = Callable[[Caller, dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    title: str
    description: str
    properties: dict[str, Any]
    required: list[str] = field(default_factory=list)
    handler: Handler | None = None
    read_only: bool = True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": self.required,
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": self.read_only, "openWorldHint": False},
        }


PROJECT_ARG = {"type": "string", "description": "id проекта или его точное название в портале"}


async def resolve_project(caller: Caller, value: str) -> tuple[str, str]:
    """(id, название) по id или точному названию; несколько или ни одного - ToolInputError."""
    value = (value or "").strip()
    if not value:
        raise ToolInputError("Укажите проект: id или точное название")
    if UUID_RE.match(value):
        return value, value
    page = await caller.get("/api/v1/projects", {"search": value, "limit": 50})
    items = page.get("items", []) if isinstance(page, dict) else []
    exact = [p for p in items if str(p.get("name", "")).strip().casefold() == value.casefold()]
    if len(exact) == 1:
        return str(exact[0]["id"]), str(exact[0]["name"])
    if len(exact) > 1:
        raise ToolInputError(
            f"Несколько проектов «{value}»: укажите id ({', '.join(str(p['id']) for p in exact)})"
        )
    near = "; ".join(str(p.get("name")) for p in items[:8]) or "ничего похожего"
    raise ToolInputError(f"Проект «{value}» не найден. Похожие: {near}")


# ------------------------------------------------------------------------------------ инструменты


async def find_projects(caller: Caller, args: dict[str, Any]) -> ToolResult:
    params: dict[str, Any] = {"limit": 100}
    if args.get("search"):
        params["search"] = str(args["search"])
    page = await caller.get("/api/v1/projects", params)
    items = [{"id": p.get("id"), "name": p.get("name")} for p in page.get("items", [])]
    lines = [f"{p['name']} — {p['id']}" for p in items] or ["Проектов не найдено"]
    return ToolResult("\n".join(lines), {"projects": items})


async def get_coordination(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    fmt = args.get("format") or "json"
    if fmt not in ("json", "ifc"):
        raise ToolInputError("format: json или ifc")
    try:
        response = await caller.get_raw(
            f"/api/v1/projects/{project_id}/tender/base/coordination.{fmt}"
        )
    except CallError as error:
        if error.status == 404:
            return ToolResult(
                f"Координационного файла у «{name}» нет: {error}. Его создаёт выпуск базы (кнопка "
                "«Выпустить базу» в портале, делает человек).",
                is_error=True,
            )
        raise
    release = response.headers.get("x-quantor-base-release", "?")
    if fmt == "ifc":
        return ToolResult(
            response.text, {"project_id": project_id, "release": release, "format": "ifc"}
        )
    data = response.json()
    summary = [f"Координационный файл «{name}», выпуск базы №{release}."]
    for group in data.get("groups", []):
        axes = group.get("axes", [])
        storeys = group.get("storeys", [])
        summary.append(
            f"{group.get('group_label')}: осей {len(axes)} "
            f"({', '.join(a['label'] for a in axes)}), "
            f"этажей {len(storeys)} ({storeys[0]['base_z_mm'] if storeys else '-'}…"
            f"{storeys[-1]['base_z_mm'] if storeys else '-'} мм)."
        )
    if data.get("doubts"):
        summary.append("Сомнения: " + "; ".join(data["doubts"]))
    summary.append(json.dumps(data, ensure_ascii=False))
    return ToolResult(
        "\n".join(summary), {"project_id": project_id, "release": release, "coordination": data}
    )


async def list_base_releases(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    rows = await caller.get(f"/api/v1/projects/{project_id}/tender/base/releases") or []
    items = [
        {
            "number": r.get("number"),
            "released_at": r.get("released_at"),
            "released_by": r.get("released_by_name"),
            "revoked": bool(r.get("revoked_at")),
            "id": r.get("id"),
        }
        for r in rows
    ]
    if not items:
        return ToolResult(f"У «{name}» выпусков базы нет.", {"releases": []})
    lines = [
        f"№{i['number']} от {i['released_at']} ({i['released_by'] or '?'})"
        + (" — отозван" if i["revoked"] else "")
        for i in items
    ]
    return ToolResult(f"Выпуски базы «{name}»:\n" + "\n".join(lines), {"releases": items})


async def model_status(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    try:
        job = await caller.get(f"/api/v1/projects/{project_id}/model/imports/latest")
    except CallError as error:
        if error.status != 404:
            raise
        job = None
    versions = await caller.get(f"/api/v1/projects/{project_id}/model/versions") or {}
    items = versions.get("items", []) if isinstance(versions, dict) else []
    newest = items[0] if items else None
    storeys: list[dict[str, Any]] = []
    if newest:
        detail = await caller.get(f"/api/v1/projects/{project_id}/model/versions/{newest['id']}")
        storeys = [
            {"name": s.get("name"), "elevation_mm": s.get("elevation_mm")}
            | ({"building": s["building_name"]} if s.get("building_name") else {})
            for s in detail.get("storeys", [])
        ]
    lines = [f"Модель «{name}»."]
    lines.append(
        f"Последняя сборка: {job.get('status')} ({job.get('stage') or '-'}), "
        f"задание {job.get('job_id')}"
        if job
        else "Сборок ещё не было."
    )
    if newest:
        lines.append(
            f"Новейшая версия №{newest.get('number')} ({newest.get('status')}), "
            f"этажей {len(storeys)}: "
            + ", ".join(
                f"{s['building'] + ': ' if 'building' in s else ''}{s['name']} {s['elevation_mm']}"
                for s in storeys
            )
        )
    return ToolResult(
        "\n".join(lines), {"import": job, "newest_version": newest, "storeys": storeys}
    )


async def all_documents(caller: Caller, project_id: str) -> list[dict[str, Any]]:
    """Все документы проекта, по страницам (в большом проекте их больше одной страницы)."""
    items: list[dict[str, Any]] = []
    while True:
        page = await caller.get(
            f"/api/v1/projects/{project_id}/documents",
            {"limit": DOCUMENTS_PAGE, "offset": len(items)},
        )
        batch = page.get("items", []) if isinstance(page, dict) else []
        items += batch
        if not batch or len(items) >= int(page.get("total", len(items))):
            return items


async def list_documents(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    kind = args.get("kind")
    items = [
        {"id": d.get("id"), "name": d.get("display_name"), "kind": d.get("document_kind")}
        for d in await all_documents(caller, project_id)
        if not kind or d.get("document_kind") == kind
    ]
    lines = [f"{d['name']} [{d['kind']}] — {d['id']}" for d in items] or ["Документов нет"]
    return ToolResult(f"Документы «{name}»:\n" + "\n".join(lines), {"documents": items})


async def send_ifc_to_3d(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    filename = str(args.get("filename", "")).strip()
    if not filename.lower().endswith(".ifc") or "/" in filename or "\\" in filename:
        raise ToolInputError(
            "filename: имя файла дисциплины с расширением .ifc, без папок (например KR.ifc)"
        )
    content = args.get("content")
    if not isinstance(content, str) or not content.lstrip().startswith("ISO-10303-21"):
        raise ToolInputError("content: текст IFC (STEP), начинается с ISO-10303-21")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        raise ToolInputError("content: в тексте IFC есть недопустимые символы") from None
    if len(data) > MAX_MCP_IFC_BYTES:
        raise ToolInputError(
            f"IFC {len(data) // 1024} КБ больше предела MCP {MAX_MCP_IFC_BYTES // 1024} КБ: "
            "загрузите его "
            "клиентом push (tools/quantor_agent) или облегчите"
        )
    same = next(
        (
            d
            for d in await all_documents(caller, project_id)
            if d.get("document_kind") == "ifc" and d.get("display_name") == filename
        ),
        None,
    )
    fields = {"document_id": str(same["id"])} if same else {}
    uploaded = await caller.upload(f"/api/v1/projects/{project_id}/uploads", filename, data, fields)
    where = "новая ревизия документа" if same else "новый документ"
    if uploaded.get("is_duplicate"):
        where = "такой файл уже был загружен, ревизия не создана"
    result: dict[str, Any] = {
        "document_id": (uploaded.get("document") or {}).get("id"),
        "upload": where,
    }
    lines = [f"«{name}»: {filename} - {where}."]
    if args.get("build", True):
        job = await caller.post(f"/api/v1/projects/{project_id}/model/imports", {})
        result["job_id"] = job.get("job_id")
        lines.append(
            f"Сборка модели запущена: задание {job.get('job_id')} "
            f"(входных IFC {job.get('inputs')}). "
            "Обычно 4-9 минут; следите model_status или job_status."
        )
    return ToolResult("\n".join(lines), result)


async def build_model(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    job = await caller.post(f"/api/v1/projects/{project_id}/model/imports", {})
    return ToolResult(
        f"«{name}»: сборка модели - задание {job.get('job_id')}, статус {job.get('status')}.", job
    )


async def job_status(caller: Caller, args: dict[str, Any]) -> ToolResult:
    job_id = str(args.get("job_id", "")).strip()
    if not UUID_RE.match(job_id):
        raise ToolInputError("job_id: id задания (uuid)")
    job = await caller.get(f"/api/v1/jobs/{job_id}")
    return ToolResult(
        f"Задание {job_id}: {job.get('status')} ({job.get('stage') or '-'}), "
        f"{round(float(job.get('progress') or 0) * 100)} %."
        + (f" Ошибка: {job.get('error_message')}" if job.get("error_message") else ""),
        job,
    )


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "find_projects",
            "Найти проекты",
            "Проекты пространства (тендерные объекты): название и id.",
            {"search": {"type": "string", "description": "часть названия"}},
            handler=find_projects,
        ),
        Tool(
            "get_coordination",
            "Координационный файл",
            "Общая сетка осей и этажи объекта из последнего выпуска базы: "
            "format=json - оси линиями в мм "
            "системы здания и этажи с отметками; format=ifc - тот же файл IFC4.",
            {
                "project": PROJECT_ARG,
                "format": {"type": "string", "enum": ["json", "ifc"], "default": "json"},
            },
            ["project"],
            get_coordination,
        ),
        Tool(
            "list_base_releases",
            "Выпуски базы",
            "Выпуски базы объекта, новые сверху (отозванные помечены).",
            {"project": PROJECT_ARG},
            ["project"],
            list_base_releases,
        ),
        Tool(
            "model_status",
            "Модель здания",
            "Последняя сборка модели из IFC и новейшая версия: этажи с отметками.",
            {"project": PROJECT_ARG},
            ["project"],
            model_status,
        ),
        Tool(
            "list_documents",
            "Документы",
            "Документы проекта (kind: ifc, pdf…).",
            {
                "project": PROJECT_ARG,
                "kind": {"type": "string", "description": "фильтр: ifc, pdf…"},
            },
            ["project"],
            list_documents,
        ),
        Tool(
            "send_ifc_to_3d",
            "Отправить в 3D",
            "Загрузить IFC своей дисциплины (текст STEP) новой ревизией документа того же имени "
            "и собрать "
            "модель здания. Нужна область токена upload. Только облегчённые IFC, до 3 МБ.",
            {
                "project": PROJECT_ARG,
                "filename": {
                    "type": "string",
                    "description": "имя файла дисциплины, например KR.ifc",
                },
                "content": {"type": "string", "description": "текст IFC (ISO-10303-21 …)"},
                "build": {
                    "type": "boolean",
                    "default": True,
                    "description": "сразу собрать модель",
                },
            },
            ["project", "filename", "content"],
            send_ifc_to_3d,
            read_only=False,
        ),
        Tool(
            "build_model",
            "Собрать модель",
            "Пересобрать модель здания из IFC проекта (область upload).",
            {"project": PROJECT_ARG},
            ["project"],
            build_model,
            read_only=False,
        ),
        Tool(
            "job_status",
            "Задание",
            "Состояние задания портала по id (сборка модели и другие).",
            {"job_id": {"type": "string", "description": "id задания"}},
            ["job_id"],
            job_status,
        ),
    )
}


# ------------------------------------------------------------------------------------ протокол


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


async def handle_message(message: Any, caller: Caller) -> dict[str, Any] | None:
    """Одно сообщение JSON-RPC. Уведомления (без id) ответа не получают."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "Нужен запрос JSON-RPC 2.0",
        )
    method = message["method"]
    message_id = message.get("id")
    is_notification = "id" not in message
    params = message.get("params") or {}
    if is_notification:
        return None
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(
            message_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": [tool.describe() for tool in TOOLS.values()]})
    if method == "tools/call":
        if not isinstance(params, dict) or params.get("name") not in TOOLS:
            return _error(
                message_id,
                INVALID_PARAMS,
                f"Нет инструмента {params.get('name') if isinstance(params, dict) else ''!r}",
            )
        tool = TOOLS[params["name"]]
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(message_id, INVALID_PARAMS, "arguments должен быть объектом")
        missing = [name for name in tool.required if name not in arguments]
        if missing:
            return _result(
                message_id,
                ToolResult(f"Не хватает аргументов: {', '.join(missing)}", is_error=True).as_mcp(),
            )
        assert tool.handler is not None
        try:
            outcome = await asyncio.wait_for(
                tool.handler(caller, arguments), timeout=TOOL_TIMEOUT_SECONDS
            )
        except ToolInputError as error:
            outcome = ToolResult(str(error), is_error=True)
        except CallError as error:
            outcome = ToolResult(f"Портал отказал (HTTP {error.status}): {error}", is_error=True)
        except TimeoutError:
            outcome = ToolResult("Инструмент не уложился во время: повторите позже", is_error=True)
        except Exception:
            # Ответ остаётся ответом JSON-RPC с тем же id: пачка и клиент не теряются.
            log.exception("mcp_tool_failed", tool=tool.name)
            outcome = ToolResult("Внутренняя ошибка портала при вызове инструмента", is_error=True)
        return _result(message_id, outcome.as_mcp())
    return _error(message_id, METHOD_NOT_FOUND, f"Метод {method!r} не поддерживается")


async def dispatch(payload: Any, caller: Caller) -> Any:
    """Сообщение или пачка; None - ответ не нужен (одни уведомления)."""
    if isinstance(payload, list):
        if not payload:
            return _error(None, INVALID_REQUEST, "Пустая пачка")
        if len(payload) > MAX_BATCH:
            return _error(None, INVALID_REQUEST, f"В пачке больше {MAX_BATCH} сообщений")
        answers = [
            answer for item in payload if (answer := await handle_message(item, caller)) is not None
        ]
        return answers or None
    return await handle_message(payload, caller)
