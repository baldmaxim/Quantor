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
import base64
import hashlib
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

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
    "базы делает только человек. Проект можно называть точным названием или id. "
    "Пакетный импорт тендерной документации: start_tender_import присылает перечень ZIP с хешами "
    "(файлы через MCP не передаются), tender_import_status показывает, что принято. "
    "Работа с результатами построения чертежей CAD (за флагом cad.export): get_cad_pipeline "
    "показывает листы и виды проекта, get_cad_view — конструкции, итоги, высоты, диагностику и "
    "замечания вида, get_cad_view_images — снимки plan.png и overlay.png вида с координатами "
    "render.json, get_cad_artifact — текстовый/JSON-артефакт (scale.json, walls.json, DXF до "
    "1 МБ), add_cad_remark — добавить замечание с рамкой bbox_pt или bbox_px (область upload), "
    "rebuild_cad_view — перестроить конструкции или повторить PDF->DXF по открытым замечаниям "
    "(область upload). Геометрию и величины считает только движок Quantor; одобрение вида "
    "выполняет человек."
)
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
REMARK_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
CAD_REMARK_TYPES = (
    "missing_wall",
    "false_wall",
    "missing_door",
    "door_geometry",
    "missing_gate",
    "missing_glazing",
    "monolith",
    "room_boundary",
    "wrong_class",
    "route",
    "other",
)
MAX_MCP_IFC_BYTES = 3 * 1024 * 1024
MAX_MCP_ARTIFACT_BYTES = 1 * 1024 * 1024
MAX_MCP_IMAGE_BYTES = 4 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_BBOX_PAD_PT = 6.0
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

    async def get_raw(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = await self.client.get(path, params=params)
        if response.status_code >= 400:
            raise self._error(response)
        return response

    async def post(self, path: str, body: Any) -> Any:
        response = await self.client.post(path, json=body)
        if response.status_code >= 400:
            raise self._error(response)
        return self._json(response) if response.content else None

    async def put(self, path: str, body: Any, params: dict[str, Any] | None = None) -> Any:
        response = await self.client.put(path, json=body, params=params)
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
    images: list[tuple[str, bytes]] = field(default_factory=list)

    def as_mcp(self) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": self.text}]
        for mime_type, raw in self.images:
            content.append(
                {
                    "type": "image",
                    "data": base64.b64encode(raw).decode("ascii"),
                    "mimeType": mime_type,
                }
            )
        out: dict[str, Any] = {"content": content, "isError": self.is_error}
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


TENDER_IMPORT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "ключ позиции в перечне, 1-200 знаков"},
        "filename": {"type": "string", "description": "имя ZIP без пути, оканчивается на .zip"},
        "size": {"type": "integer", "description": "размер ZIP, байт"},
        "sha256": {"type": "string", "description": "SHA-256 ZIP (проверка передачи)"},
        "pdf_sha256": {"type": "string", "description": "SHA-256 PDF внутри ZIP"},
        "blocks_sha256": {"type": "string", "description": "SHA-256 blocks.json внутри ZIP"},
    },
    "required": ["key", "filename", "size", "sha256", "pdf_sha256", "blocks_sha256"],
    "additionalProperties": False,
}


def _import_text(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    return (
        f"Импорт {data.get('import_id')}: объект «{data.get('project_name')}» "
        f"({data.get('matched_by')}), {data.get('project_url')}. "
        f"Позиций {summary.get('total')}: ждут загрузки {summary.get('pending')}, "
        f"принято {summary.get('received')}, импортировано {summary.get('imported')}, "
        f"ошибок {summary.get('failed')}, конфликтов {summary.get('conflict')}. "
        + ("Импорт завершён." if data.get("complete") else "Импорт не завершён.")
    )


async def start_tender_import(caller: Caller, args: dict[str, Any]) -> ToolResult:
    tenderhub_id = str(args.get("tenderhub_id") or "").strip()
    project = str(args.get("project") or "").strip()
    if bool(tenderhub_id) == bool(project):
        raise ToolInputError("Укажите ровно одно из полей: tenderhub_id или project")
    items = args.get("items")
    if not isinstance(items, list) or not items:
        raise ToolInputError("items: непустой массив позиций перечня")
    body: dict[str, Any] = {"items": items}
    if tenderhub_id:
        body["tenderhub_id"] = tenderhub_id
    else:
        project_id, _ = await resolve_project(caller, project)
        body["project_id"] = project_id
    data = await caller.post("/api/v1/tender-imports", body)
    return ToolResult(_import_text(data), data)


async def tender_import_status(caller: Caller, args: dict[str, Any]) -> ToolResult:
    import_id = str(args.get("import_id", "")).strip()
    if not UUID_RE.match(import_id):
        raise ToolInputError("import_id: id пакетного импорта (uuid)")
    data = await caller.get(f"/api/v1/tender-imports/{import_id}")
    return ToolResult(_import_text(data), data)


def _require_uuid(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key, "")).strip()
    if not UUID_RE.match(value):
        raise ToolInputError(f"{key}: нужен uuid")
    return value


def _require_nonneg_int(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if type(value) is not int or value < 0:
        raise ToolInputError(f"{key}: целое число >= 0")
    return value


def _parse_bbox(raw: Any, key: str = "bbox_pt") -> list[float]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise ToolInputError(f"{key}: массив из 4 чисел [x0, y0, x1, y1]")
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
        raise ToolInputError(f"{key}: все 4 координаты должны быть числами")
    coords = [float(v) for v in raw]
    if not all(math.isfinite(v) for v in coords):
        raise ToolInputError(f"{key}: координаты должны быть конечными числами")
    x0, y0, x1, y1 = coords
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        raise ToolInputError(f"{key}: нужны x0 >= 0, y0 >= 0, x1 > x0, y1 > y0")
    return coords


def _cad_view_folder(page_index: int, view: int) -> str:
    if page_index < 0 or page_index > 998 or view < 0 or view > 99:
        raise ToolInputError("Недопустимый номер страницы (0..998) или вида (0..99)")
    return f"views/p{page_index + 1:03d}_v{view:02d}"


def _bbox_px_to_pt(
    bbox_px: list[float], clip: list[float], zoom: float, pad: float = _BBOX_PAD_PT
) -> list[float]:
    """Пиксели plan.png/overlay.png -> pt страницы PDF (та же формула, что в ai_review.py)."""
    cx0, cy0, cx1, cy1 = clip
    x0, y0, x1, y1 = bbox_px
    left = min(max(cx0 + x0 / zoom - pad, cx0), cx1)
    top = min(max(cy0 + y0 / zoom - pad, cy0), cy1)
    right = min(max(cx0 + x1 / zoom + pad, cx0), cx1)
    bottom = min(max(cy0 + y1 / zoom + pad, cy0), cy1)
    if right - left < 1.0:
        left, right = max(cx0, right - 1.0), max(right, min(cx1, cx0 + 1.0))
    if bottom - top < 1.0:
        top, bottom = max(cy0, bottom - 1.0), max(bottom, min(cy1, cy0 + 1.0))
    return [round(left, 2), round(top, 2), round(right, 2), round(bottom, 2)]


async def _resolve_walls_job_id(
    caller: Caller,
    *,
    project_id: str,
    job_id: str,
    page_index: int,
    view: int,
    explicit: str | None,
) -> str:
    if explicit:
        if not UUID_RE.match(explicit):
            raise ToolInputError("walls_job_id: нужен uuid задания cad_walls")
        return explicit
    data = await caller.get(
        f"/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}/constructions"
    )
    walls_job_id = str((data or {}).get("walls_job_id") or "").strip()
    if not UUID_RE.match(walls_job_id):
        raise ToolInputError("У вида нет готового задания конструкций (walls_job_id)")
    return walls_job_id


async def _fetch_render_meta(
    caller: Caller,
    *,
    project_id: str,
    revision_id: str,
    walls_job_id: str,
    folder: str,
) -> dict[str, Any]:
    path = (
        f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{walls_job_id}"
        f"/artifacts/{folder}/render.json"
    )
    raw = await caller.get_raw(path)
    try:
        meta = json.loads(raw.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ToolInputError("Некорректный render.json у задания конструкций") from None
    if not isinstance(meta, dict):
        raise ToolInputError("Некорректный render.json у задания конструкций")
    return meta


async def get_cad_pipeline(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    raw_revision = str(args.get("revision_id") or "").strip()
    if raw_revision:
        if not UUID_RE.match(raw_revision):
            raise ToolInputError("revision_id: нужен uuid ревизии")
        data = await caller.get(
            f"/api/v1/projects/{project_id}/revisions/{raw_revision}/cad/pipeline"
        )
        sheets = data.get("sheets", []) if isinstance(data, dict) else []
        lines = [f"Конвейер CAD «{name}», ревизия {raw_revision}: листов {len(sheets)}."]
        for sheet in sheets:
            convert = sheet.get("convert") or {}
            views = sheet.get("views") or []
            view_parts = [
                f"вид {v.get('view')} (walls: {(v.get('walls') or {}).get('status') or 'нет'}"
                + (", одобрен" if v.get("approved") else "")
                + ")"
                for v in views
            ]
            label = sheet.get("title") or sheet.get("page_label") or "-"
            lines.append(
                f"стр. {sheet.get('page_index')} ({label}): "
                f"convert={convert.get('job_id') or '-'} [{convert.get('status') or 'нет'}]; "
                + (", ".join(view_parts) if view_parts else "видов нет")
            )
        return ToolResult("\n".join(lines), {"project_id": project_id, "pipeline": data})

    data = await caller.get(f"/api/v1/projects/{project_id}/ai-pipeline")
    sheets = data.get("sheets", []) if isinstance(data, dict) else []
    lines = [f"Конвейер чертежей CAD «{name}»: видов/листов {len(sheets)}."]
    for row in sheets:
        stage1 = (row.get("stage1") or {}).get("state", "-")
        stage4 = row.get("stage4") or {}
        remarks = stage4.get("open_remarks", 0)
        approved = ", одобрен" if stage4.get("approved") else ""
        lines.append(
            f"{row.get('document_name')} · стр. {row.get('page_index')} "
            f"({row.get('sheet_title') or '-'}) · вид {row.get('view')} · "
            f"rev={row.get('revision_id')} · job={row.get('convert_job_id') or '-'} · "
            f"этап1={stage1}, замечаний={remarks}{approved}"
        )
    return ToolResult("\n".join(lines), {"project_id": project_id, "pipeline": data})


async def get_cad_view(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    job_id = _require_uuid(args, "job_id")
    page_index = _require_nonneg_int(args, "page_index")
    view = _require_nonneg_int(args, "view")
    raw_revision = str(args.get("revision_id") or "").strip()
    if raw_revision and not UUID_RE.match(raw_revision):
        raise ToolInputError("revision_id: нужен uuid ревизии")
    include_constructions = bool(args.get("include_constructions", False))
    include_openings = bool(args.get("include_openings", False))

    constructions_data: dict[str, Any] | None = None
    constructions_error: str | None = None
    try:
        constructions_data = await caller.get(
            f"/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}/constructions"
        )
    except CallError as error:
        if error.status != 404 or not raw_revision:
            raise
        constructions_error = str(error)

    diagnostics: dict[str, Any] | None = None
    remarks: list[dict[str, Any]] | None = None
    if raw_revision:
        diagnostics = await caller.get(
            f"/api/v1/projects/{project_id}/revisions/{raw_revision}/cad/{job_id}"
            f"/views/{page_index}/{view}"
        )
        attempt = diagnostics.get("attempt") if isinstance(diagnostics, dict) else None
        if type(attempt) is int and attempt >= 1:
            loaded_remarks = await caller.get(
                f"/api/v1/projects/{project_id}/revisions/{raw_revision}/cad/{job_id}/remarks",
                {"attempt": attempt, "page_index": page_index, "view": view},
            )
            if isinstance(loaded_remarks, list):
                remarks = loaded_remarks

    payload: dict[str, Any] = {
        "project_id": project_id,
        "job_id": job_id,
        "page_index": page_index,
        "view": view,
    }
    if raw_revision:
        payload["revision_id"] = raw_revision

    lines = [f"Вид CAD «{name}»: job={job_id}, стр. {page_index}, вид {view}."]
    if diagnostics is not None:
        files = [f.get("name") for f in diagnostics.get("files") or [] if isinstance(f, dict)]
        frame = diagnostics.get("frame") or {}
        lines.append(
            f"Преобразование: статус={diagnostics.get('status')}, "
            f"масштаб={diagnostics.get('scale_status') or '-'}, "
            f"кадр={'подтверждён' if frame.get('confirmed') else 'нет'}, "
            f"файлы: {', '.join(str(x) for x in files) or 'нет'}."
        )
        payload["diagnostics"] = diagnostics

    if constructions_data is not None:
        summary = constructions_data.get("summary") or {}
        totals = constructions_data.get("totals") or []
        warnings = constructions_data.get("warnings") or []
        hints_applied = constructions_data.get("hints_applied") or []
        lines.append(
            f"Конструкции (walls_job={constructions_data.get('walls_job_id')}, "
            f"генератор={constructions_data.get('generator')}): "
            f"всего {summary.get('total_count', 0)}, групп {len(totals)}, "
            f"предупреждений {len(warnings)}, подсказок применено {len(hints_applied)}."
        )
        for group in totals[:15]:
            lines.append(
                f"  - {group.get('kind')} {group.get('thickness_mm')} мм "
                f"({group.get('material') or 'материал не задан'}): "
                f"шт={group.get('count')}, длина={group.get('length_m')} м, "
                f"площадь={group.get('wall_area_m2')} м², объём={group.get('volume_m3')} м³"
            )
        compact = {
            k: v for k, v in constructions_data.items() if k not in ("constructions", "openings")
        }
        compact["constructions_count"] = len(constructions_data.get("constructions") or [])
        compact["openings_count"] = len(constructions_data.get("openings") or [])
        if include_constructions:
            compact["constructions"] = constructions_data.get("constructions") or []
        if include_openings:
            compact["openings"] = constructions_data.get("openings") or []
        payload["constructions"] = compact
    elif constructions_error is not None:
        lines.append(f"Конструкции ещё не готовы: {constructions_error}.")

    if remarks is not None:
        open_count = sum(1 for r in remarks if r.get("status") == "open")
        lines.append(f"Замечания: открыто {open_count}, всего {len(remarks)}.")
        payload["remarks"] = remarks

    return ToolResult("\n".join(lines), payload)


async def get_cad_artifact(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    revision_id = _require_uuid(args, "revision_id")
    job_id = _require_uuid(args, "job_id")
    artifact_name = str(args.get("name", "")).strip().lstrip("/")
    if not artifact_name or len(artifact_name) > 256 or ".." in artifact_name.split("/"):
        raise ToolInputError("name: относительный путь артефакта вида (без '..')")
    params: dict[str, Any] | None = None
    if args.get("attempt") is not None:
        attempt = args["attempt"]
        if type(attempt) is not int or attempt < 1:
            raise ToolInputError("attempt: целое число >= 1")
        params = {"attempt": attempt}
    encoded = "/".join(quote(part, safe="") for part in artifact_name.split("/"))
    response = await caller.get_raw(
        f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}/artifacts/{encoded}",
        params=params,
    )
    raw = response.content
    if len(raw) > MAX_MCP_ARTIFACT_BYTES:
        raise ToolInputError(
            f"Артефакт {artifact_name} ({len(raw) // 1024} КБ) больше предела MCP "
            f"({MAX_MCP_ARTIFACT_BYTES // 1024} КБ): скачайте его через REST API портала."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolInputError(
            f"Артефакт {artifact_name} бинарный и не передаётся текстом через MCP."
        ) from None
    sha256 = response.headers.get("x-content-sha256")
    meta: dict[str, Any] = {
        "project_id": project_id,
        "revision_id": revision_id,
        "job_id": job_id,
        "name": artifact_name,
        "size": len(raw),
        "sha256": sha256,
    }
    if artifact_name.lower().endswith(".json"):
        try:
            meta["content"] = json.loads(text)
        except ValueError:
            meta["content_text"] = text
    else:
        meta["content_text"] = text
    return ToolResult(
        f"Артефакт «{name}» · {artifact_name} ({len(raw)} байт, sha256={sha256 or '-'}):\n{text}",
        meta,
    )


async def get_cad_view_images(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    revision_id = _require_uuid(args, "revision_id")
    job_id = _require_uuid(args, "job_id")
    page_index = _require_nonneg_int(args, "page_index")
    view = _require_nonneg_int(args, "view")
    which = str(args.get("which") or "both").strip()
    if which not in ("both", "plan", "overlay"):
        raise ToolInputError("which: both, plan или overlay")
    folder = _cad_view_folder(page_index, view)
    walls_job_id = await _resolve_walls_job_id(
        caller,
        project_id=project_id,
        job_id=job_id,
        page_index=page_index,
        view=view,
        explicit=str(args.get("walls_job_id") or "").strip() or None,
    )
    try:
        render_meta = await _fetch_render_meta(
            caller,
            project_id=project_id,
            revision_id=revision_id,
            walls_job_id=walls_job_id,
            folder=folder,
        )
    except CallError as error:
        if error.status == 404:
            return ToolResult(
                f"Снимки вида «{name}» (стр. {page_index}, вид {view}, walls_job={walls_job_id}) "
                "ещё не сформированы: пересчитайте конструкции вида на новом cad-worker, "
                "после чего появятся plan.png, overlay.png и render.json.",
                is_error=True,
            )
        raise

    wanted = ("plan.png", "overlay.png") if which == "both" else (f"{which}.png",)
    images: list[tuple[str, bytes]] = []
    files_meta: list[dict[str, Any]] = []
    for filename in wanted:
        path = (
            f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{walls_job_id}"
            f"/artifacts/{folder}/{filename}"
        )
        try:
            response = await caller.get_raw(path)
        except CallError as error:
            if error.status == 404:
                return ToolResult(
                    f"Файл {folder}/{filename} не найден у задания {walls_job_id}: "
                    "пересчитайте конструкции вида на новом cad-worker.",
                    is_error=True,
                )
            raise
        raw = response.content
        if len(raw) > MAX_MCP_IMAGE_BYTES:
            raise ToolInputError(
                f"Снимок {filename} ({len(raw) // 1024} КБ) превышает предел MCP "
                f"({MAX_MCP_IMAGE_BYTES // 1024} КБ)."
            )
        if not raw.startswith(_PNG_MAGIC):
            raise ToolInputError(f"Снимок {filename} повреждён (не PNG).")
        images.append(("image/png", raw))
        files_meta.append(
            {
                "name": f"{folder}/{filename}",
                "size": len(raw),
                "sha256": response.headers.get("x-content-sha256"),
            }
        )

    order_desc = (
        "1) plan.png (исходный чертёж PDF), 2) overlay.png (наложение обводки: красные — стены "
        "и перегородки, синие — каркасные перегородки, зелёные — перемычки дверей)"
        if which == "both"
        else f"{wanted[0]}"
    )
    text = (
        f"Снимки вида CAD «{name}» (стр. {page_index}, вид {view}, walls_job={walls_job_id}): "
        f"{order_desc}.\n"
        f"Размер: {render_meta.get('width_px')}x{render_meta.get('height_px')} px, "
        f"zoom={render_meta.get('zoom')}, clip_pt={render_meta.get('clip')}.\n"
        "Для отправки найденных ошибок в Quantor передайте bbox_px=[x0, y0, x1, y1] "
        "(в пикселях снимка от левого верхнего угла) прямо в add_cad_remark — сервер сам "
        "переведёт координаты в pt PDF по render.json."
    )
    return ToolResult(
        text,
        {
            "project_id": project_id,
            "revision_id": revision_id,
            "job_id": job_id,
            "walls_job_id": walls_job_id,
            "page_index": page_index,
            "view": view,
            "render": render_meta,
            "images": files_meta,
        },
        images=images,
    )


async def add_cad_remark(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    revision_id = _require_uuid(args, "revision_id")
    job_id = _require_uuid(args, "job_id")
    page_index = _require_nonneg_int(args, "page_index")
    view = _require_nonneg_int(args, "view")
    remark_type = str(args.get("type", "")).strip()
    if remark_type not in CAD_REMARK_TYPES:
        raise ToolInputError(f"type: одно из {', '.join(CAD_REMARK_TYPES)}")
    has_pt, has_px = args.get("bbox_pt") is not None, args.get("bbox_px") is not None
    if has_pt == has_px:
        raise ToolInputError("Укажите ровно одно из полей: bbox_pt (pt PDF) или bbox_px (пиксели)")
    if has_pt:
        bbox_pt = _parse_bbox(args.get("bbox_pt"), "bbox_pt")
    else:
        bbox_px = _parse_bbox(args.get("bbox_px"), "bbox_px")
        walls_job_id = await _resolve_walls_job_id(
            caller,
            project_id=project_id,
            job_id=job_id,
            page_index=page_index,
            view=view,
            explicit=str(args.get("walls_job_id") or "").strip() or None,
        )
        render_meta = await _fetch_render_meta(
            caller,
            project_id=project_id,
            revision_id=revision_id,
            walls_job_id=walls_job_id,
            folder=_cad_view_folder(page_index, view),
        )
        clip = render_meta.get("clip")
        zoom = render_meta.get("zoom")
        if (
            not isinstance(clip, list)
            or len(clip) != 4
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in clip)
            or not isinstance(zoom, int | float)
            or isinstance(zoom, bool)
            or float(zoom) <= 0
        ):
            raise ToolInputError("В render.json отсутствуют корректные clip и zoom")
        bbox_pt = _bbox_px_to_pt(bbox_px, [float(v) for v in clip], float(zoom))
    comment = str(args.get("comment", "")).strip()
    if not comment or len(comment) > 4000:
        raise ToolInputError("comment: непустой текст до 4000 знаков")
    reviewer = str(args.get("reviewer") or "ИИ агент (MCP)").strip()[:200]
    status_val = str(args.get("status") or "open").strip()
    if status_val not in ("open", "resolved"):
        raise ToolInputError("status: open или resolved")

    attempt_arg = args.get("attempt")
    attempt: int | None = None
    if attempt_arg is not None:
        if type(attempt_arg) is not int or attempt_arg < 1:
            raise ToolInputError("attempt: целое число >= 1")
        attempt = attempt_arg

    dxf_sha256: str | None = None
    diagnostics = await caller.get(
        f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}"
        f"/views/{page_index}/{view}"
    )
    if isinstance(diagnostics, dict):
        if attempt is None and type(diagnostics.get("attempt")) is int:
            attempt = diagnostics["attempt"]
        dxf = diagnostics.get("dxf")
        if isinstance(dxf, dict) and isinstance(dxf.get("sha256"), str):
            dxf_sha256 = dxf["sha256"]
    if attempt is None or attempt < 1:
        raise ToolInputError("Не удалось определить номер попытки (attempt) для вида")

    raw_key = str(args.get("remark_key") or "").strip()
    if raw_key:
        if not REMARK_KEY_RE.match(raw_key):
            raise ToolInputError("remark_key: 1-64 знака (латиница, цифры, ., _, -)")
        remark_key = raw_key
    else:
        seed = f"{job_id}:{page_index}:{view}:{remark_type}:{bbox_pt}:{comment}"
        remark_key = "mcp-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    body: dict[str, Any] = {
        "type": remark_type,
        "comment": comment,
        "reviewer": reviewer,
        "status": status_val,
        "bbox_pt": bbox_pt,
        "dxf_sha256": dxf_sha256,
    }
    saved = await caller.put(
        f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}/remarks/{remark_key}",
        body,
        params={"attempt": attempt, "page_index": page_index, "view": view},
    )
    return ToolResult(
        f"Замечание {remark_key} ({remark_type}, {status_val}) сохранено для «{name}» "
        f"(стр. {page_index}, вид {view}, попытка {attempt}, автор: {reviewer}).",
        {"project_id": project_id, "attempt": attempt, "remark": saved},
    )


async def rebuild_cad_view(caller: Caller, args: dict[str, Any]) -> ToolResult:
    project_id, name = await resolve_project(caller, str(args.get("project", "")))
    job_id = _require_uuid(args, "job_id")
    page_index = _require_nonneg_int(args, "page_index")
    view = _require_nonneg_int(args, "view")
    mode = str(args.get("mode") or "rebuild_walls").strip()
    if mode == "rebuild_walls":
        data = await caller.post(
            f"/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}"
            "/walls/rebuild-by-remarks",
            {},
        )
        return ToolResult(
            f"«{name}»: перестроение конструкций по замечаниям поставлено — "
            f"задание {data.get('job_id')}, статус {data.get('status')}.",
            {"mode": mode, "job": data},
        )
    if mode == "reconvert_pdf":
        revision_id = _require_uuid(args, "revision_id")
        data = await caller.post(
            f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}"
            f"/views/{page_index}/{view}/reconvert-by-remarks",
            {},
        )
        return ToolResult(
            f"«{name}»: повторное преобразование PDF->DXF с подсказками поставлено — "
            f"задание {data.get('job_id')}, статус {data.get('status')}.",
            {"mode": mode, "job": data},
        )
    raise ToolInputError("mode: rebuild_walls или reconvert_pdf")


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
            "start_tender_import",
            "Пакетный импорт тендера",
            "Начать пакетный импорт тендерной документации: перечень ZIP-пакетов распознавалки "
            "(PDF + blocks.json) с хешами. Объект - по tenderhub_id (создаётся, если токену "
            "разрешено: области upload и tender_import) или по project. Возвращает, что уже "
            "есть и что догрузить; сами файлы через MCP не передаются.",
            {
                "tenderhub_id": {"type": "string", "description": "id тендера в TenderHUB"},
                "project": PROJECT_ARG,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": TENDER_IMPORT_ITEM_SCHEMA,
                    "description": "перечень позиций (ZIP-пакетов)",
                },
            },
            ["items"],
            start_tender_import,
            read_only=False,
        ),
        Tool(
            "tender_import_status",
            "Состояние пакетного импорта",
            "Состояние позиций пакетного импорта по id импорта: ждут загрузки, приняты, "
            "импортированы, ошибки, конфликты распознавания.",
            {"import_id": {"type": "string", "description": "id пакетного импорта"}},
            ["import_id"],
            tender_import_status,
        ),
        Tool(
            "job_status",
            "Задание",
            "Состояние задания портала по id (сборка модели, CAD и другие).",
            {"job_id": {"type": "string", "description": "id задания"}},
            ["job_id"],
            job_status,
        ),
        Tool(
            "get_cad_pipeline",
            "Листы и виды CAD",
            "Состояние построения чертежей CAD проекта (или конкретной ревизии): листы, виды, "
            "job_id преобразования и конструкций, число открытых замечаний. Флаг cad.export, "
            "область read.",
            {
                "project": PROJECT_ARG,
                "revision_id": {
                    "type": "string",
                    "description": "id ревизии (необязательно: без него — все планы проекта)",
                },
            },
            ["project"],
            get_cad_pipeline,
        ),
        Tool(
            "get_cad_view",
            "Результат вида CAD",
            "Результаты построения чертежа вида: итоги групп конструкций, высоты, предупреждения, "
            "подсказки hints_applied; при указании revision_id также диагностика (масштаб, кадр, "
            "перечень артефактов) и замечания. Область read.",
            {
                "project": PROJECT_ARG,
                "job_id": {"type": "string", "description": "id задания cad_pdf_convert"},
                "page_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "индекс страницы с 0",
                },
                "view": {"type": "integer", "minimum": 0, "description": "номер вида на странице"},
                "revision_id": {
                    "type": "string",
                    "description": "id ревизии (добавляет диагностику, артефакты и замечания)",
                },
                "include_constructions": {
                    "type": "boolean",
                    "default": False,
                    "description": "включить полный список конструкций вида",
                },
                "include_openings": {
                    "type": "boolean",
                    "default": False,
                    "description": "включить список проёмов вида",
                },
            },
            ["project", "job_id", "page_index", "view"],
            get_cad_view,
        ),
        Tool(
            "get_cad_artifact",
            "Артефакт вида CAD",
            "Прочитать текстовый или JSON-артефакт задания CAD (scale.json, cad_checks.json, "
            "walls.json, plan_candidates.dxf и др., до 1 МБ). Область read.",
            {
                "project": PROJECT_ARG,
                "revision_id": {"type": "string", "description": "id ревизии документа"},
                "job_id": {"type": "string", "description": "id задания CAD (convert/walls/mep)"},
                "name": {
                    "type": "string",
                    "description": (
                        "путь артефакта из diagnostics.files (напр. views/p008_v01/scale.json)"
                    ),
                },
                "attempt": {"type": "integer", "minimum": 1, "description": "номер попытки (опц.)"},
            },
            ["project", "revision_id", "job_id", "name"],
            get_cad_artifact,
        ),
        Tool(
            "get_cad_view_images",
            "Снимки вида CAD (plan/overlay PNG)",
            "Получить изображения plan.png (исходный чертёж) и overlay.png (наложение обводки "
            "walls.json) вместе с координатами render.json (clip, zoom) в формате MCP image/png "
            "для визуальной проверки чертежа в Gemini, Claude или Codex. Область read.",
            {
                "project": PROJECT_ARG,
                "revision_id": {"type": "string", "description": "id ревизии документа"},
                "job_id": {"type": "string", "description": "id задания cad_pdf_convert"},
                "page_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "индекс страницы с 0",
                },
                "view": {"type": "integer", "minimum": 0, "description": "номер вида на странице"},
                "which": {
                    "type": "string",
                    "enum": ["both", "plan", "overlay"],
                    "default": "both",
                    "description": "какие снимки вернуть: both, plan или overlay",
                },
                "walls_job_id": {
                    "type": "string",
                    "description": "id задания cad_walls (опц.; без него берётся последний)",
                },
            },
            ["project", "revision_id", "job_id", "page_index", "view"],
            get_cad_view_images,
        ),
        Tool(
            "add_cad_remark",
            "Добавить замечание CAD",
            "Сохранить замечание агента (Gemini, Claude, Codex и др.) на виде чертежа с рамкой "
            "bbox_pt (в pt PDF) или bbox_px (в пикселях plan.png/overlay.png — переводится по "
            "render.json). Область upload.",
            {
                "project": PROJECT_ARG,
                "revision_id": {"type": "string", "description": "id ревизии документа"},
                "job_id": {"type": "string", "description": "id задания cad_pdf_convert"},
                "page_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "индекс страницы с 0",
                },
                "view": {"type": "integer", "minimum": 0, "description": "номер вида на странице"},
                "type": {
                    "type": "string",
                    "enum": list(CAD_REMARK_TYPES),
                    "description": "тип замечания CAD",
                },
                "bbox_pt": {
                    "type": "array",
                    "minItems": 4,
                    "maxItems": 4,
                    "items": {"type": "number"},
                    "description": "рамка [x0, y0, x1, y1] в pt PDF от левого верхнего угла",
                },
                "bbox_px": {
                    "type": "array",
                    "minItems": 4,
                    "maxItems": 4,
                    "items": {"type": "number"},
                    "description": "рамка [x0, y0, x1, y1] в пикселях plan.png/overlay.png",
                },
                "walls_job_id": {
                    "type": "string",
                    "description": "id задания cad_walls для чтения render.json при bbox_px (опц.)",
                },
                "comment": {"type": "string", "description": "суть замечания и доказательство"},
                "reviewer": {
                    "type": "string",
                    "default": "ИИ агент (MCP)",
                    "description": "подпись отправителя (например Gemini (MCP))",
                },
                "remark_key": {
                    "type": "string",
                    "description": "ключ замечания (опц.; без него генерируется детерминированно)",
                },
                "attempt": {"type": "integer", "minimum": 1, "description": "попытка (опц.)"},
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved"],
                    "default": "open",
                    "description": "статус замечания",
                },
            },
            [
                "project",
                "revision_id",
                "job_id",
                "page_index",
                "view",
                "type",
                "comment",
            ],
            add_cad_remark,
            read_only=False,
        ),
        Tool(
            "rebuild_cad_view",
            "Перестроить вид по замечаниям",
            "Запустить детерминированное перестроение конструкций (rebuild_walls) или повторное "
            "преобразование PDF->DXF (reconvert_pdf) по открытым замечаниям вида. Область upload.",
            {
                "project": PROJECT_ARG,
                "job_id": {"type": "string", "description": "id задания cad_pdf_convert"},
                "page_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "индекс страницы с 0",
                },
                "view": {"type": "integer", "minimum": 0, "description": "номер вида на странице"},
                "mode": {
                    "type": "string",
                    "enum": ["rebuild_walls", "reconvert_pdf"],
                    "default": "rebuild_walls",
                    "description": "rebuild_walls (cad_walls --hints) или reconvert_pdf (PDF->DXF)",
                },
                "revision_id": {
                    "type": "string",
                    "description": "id ревизии (обязателен для mode=reconvert_pdf)",
                },
            },
            ["project", "job_id", "page_index", "view"],
            rebuild_cad_view,
            read_only=False,
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
