"""Зоны помещений листа как вход задания `cad_walls` (контур плиты по зонам, cad_walls v1.4).

Сервер собирает зоны квартир и МОП страницы, переводит их в мм DXF по кадру вида (тем же кодом,
что зоны двери 3D-вида) и кладёт канонический JSON в хранилище: адрес по sha256 содержимого.
Скрипт получает его опцией `--zones`. Кадр вида не установлен — зон нет, задание строится как
прежде, а причина фиксируется в `zones_warning` задания. Модуль стандартный: ни Shapely, ни
ezdxf сюда не импортируются.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any, Final

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain import JobType
from app.errors import DomainError, ErrorCode, http_error
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_floor3d, cad_views, cad_zones
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

ViewZonePt = tuple[float, float, float, float]

ROOM_KINDS: Final = ("room_apartment", "room_mop")
# Предел входа: контуры зон одного листа, с большим запасом.
MAX_ZONES_BYTES: Final = 8 * 1024 * 1024
_ROUND_MM: Final = 1
_ROUND_PT: Final = 2


@dataclass(frozen=True, slots=True)
class ZonesInput:
    """Вход зон задания: пусто (`sha256` пуст) или канонический JSON с адресом по содержимому."""

    raw: bytes
    sha256: str
    count: int
    warning: str | None
    # Прямоугольник вида в пунктах PDF (x0, y0, x1, y1; левый верхний угол) для `--view-zone`:
    # скрипт по его центру выбирает заголовок плана. `None` — кадр не подтверждён или bbox нет.
    view_zone: ViewZonePt | None = None

    @property
    def present(self) -> bool:
        return bool(self.sha256)


NO_ZONES = ZonesInput(b"", "", 0, None)


def input_key(revision_id: uuid.UUID, sha256: str) -> str:
    """Ключ входного объекта зон; адрес по содержимому, вне каталогов попыток."""
    return f"revisions/{revision_id}/cad/walls-zones-input/{sha256}.json"


def canonical_bytes(zones: list[cad_floor3d.RoomZoneMm]) -> bytes:
    """Канонический JSON `[{"kind", "shell"}]`: те же зоны дают те же байты при любом порядке."""
    rows = sorted(
        (
            {
                "kind": z.kind,
                "shell": [[round(x, _ROUND_MM), round(y, _ROUND_MM)] for x, y in z.shell],
            }
            for z in zones
        ),
        key=lambda row: (row["kind"], json.dumps(row["shell"])),
    )
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


async def _artifact_json(
    storage: ObjectStorage, parent: Job, revision_id: uuid.UUID, attempt: int, name: str
) -> Any:
    artifact = cad_service.find_artifact(parent, name, attempt)
    if artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, parent.id, attempt, name)
    if artifact.get("key") != key:
        return None
    try:
        return await cad_views.read_json(storage, key)
    except ObjectNotFoundError:
        return None
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    except (cad_views.ArtifactTooLargeError, ValueError):
        return None


def view_zone_pt(
    bbox_mm: object,
    *,
    origin_pt: tuple[float, float] | None,
    mm_per_pdf_point: float | None,
) -> ViewZonePt | None:
    """bbox вида из preview.json (мм DXF: x0, y0, x1, y1) -> прямоугольник в пунктах PDF.

    Обратное к кадру вида (`pt = origin_pt + (x_mm, -y_mm) / mm_per_pdf_point`, ось Y вниз):
    x_pt = ox + x_mm / k; y_pt = oy - y_mm / k, поэтому верхний край — по наибольшему y_mm.
    Нет bbox, начала координат или коэффициента — `None` (аргумент скрипту не передаётся).
    """
    if (
        origin_pt is None
        or mm_per_pdf_point is None
        or mm_per_pdf_point <= 0
        or not isinstance(bbox_mm, list)
        or len(bbox_mm) != 4
    ):
        return None
    values: list[float] = []
    for item in bbox_mm:
        if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item):
            return None
        values.append(float(item))
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        return None
    ox, oy = origin_pt
    return (
        round(ox + x0 / mm_per_pdf_point, _ROUND_PT),
        round(oy - y1 / mm_per_pdf_point, _ROUND_PT),
        round(ox + x1 / mm_per_pdf_point, _ROUND_PT),
        round(oy - y0 / mm_per_pdf_point, _ROUND_PT),
    )


async def sheet_room_zones(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
) -> ZonesInput:
    """Зоны квартир и МОП страницы в мм DXF вида; нет зон — `NO_ZONES`, нет кадра — с причиной."""
    revision_id = parent.payload.get("revision_id")
    if parent.job_type is not JobType.CAD_PDF_CONVERT or not isinstance(revision_id, str):
        return NO_ZONES
    revision = uuid.UUID(revision_id)
    attempt = cad_service.current_result(parent).get("attempt")
    frame = None
    view_zone: ViewZonePt | None = None
    if type(attempt) is int:
        folder = cad_service.view_folder(page_index, view)
        scale = cad_views.scale_from(
            await _artifact_json(storage, parent, revision, attempt, f"{folder}/scale.json")
        )
        checks = await _artifact_json(
            storage, parent, revision, attempt, f"{folder}/cad_checks.json"
        )
        frame = cad_views.frame_from(scale, checks)
        if frame.confirmed:
            preview = await _artifact_json(
                storage, parent, revision, attempt, f"{folder}/preview.json"
            )
            view_zone = view_zone_pt(
                preview.get("bbox") if isinstance(preview, dict) else None,
                origin_pt=frame.origin_pt,
                mm_per_pdf_point=frame.mm_per_pdf_point,
            )
    rows = [
        zone
        for zone in await cad_zones.list_zones(session, revision_id=revision, page_index=page_index)
        if zone.kind in ROOM_KINDS and len(zone.points) >= 3
    ]
    if not rows:
        return dataclasses.replace(NO_ZONES, view_zone=view_zone)
    page = (
        await cad_zones.page_scales(session, revision_id=revision, page_indexes={page_index})
    ).get(page_index)
    geometry = None if page is None else page.geometry
    origin = None if frame is None else frame.origin_pt
    factor = None if frame is None else frame.mm_per_pdf_point
    if frame is None or not frame.confirmed:
        reason = frame.reason if frame is not None and frame.reason else "кадр вида не установлен"
    elif geometry is None or origin is None or factor is None:
        reason = "нет геометрии страницы" if geometry is None else "кадр вида неполон"
    else:
        reason = None
    if reason is not None or geometry is None or origin is None or factor is None:
        return ZonesInput(
            b"",
            "",
            0,
            f"Контур плиты построен без зон помещений: {reason or 'кадр неполон'}.",
            view_zone,
        )
    mapped = cad_floor3d.room_zones_to_mm(
        [
            cad_floor3d.RoomZoneNormalized(zone.kind, [list(p) for p in zone.points])
            for zone in rows
        ],
        page_width_pt=float(geometry.display_width_pt),
        page_height_pt=float(geometry.display_height_pt),
        origin_pt=origin,
        mm_per_pdf_point=factor,
    )
    if not mapped:
        return dataclasses.replace(NO_ZONES, view_zone=view_zone)
    raw = canonical_bytes(mapped)
    if len(raw) > MAX_ZONES_BYTES:
        raise DomainError(ErrorCode.CAD_INPUT_LIMIT_EXCEEDED, "зоны листа больше допустимого")
    return ZonesInput(raw, hashlib.sha256(raw).hexdigest(), len(mapped), None, view_zone)


async def store(
    storage: ObjectStorage, *, revision_id: uuid.UUID, parent_id: uuid.UUID, zones: ZonesInput
) -> None:
    """Кладёт вход зон в хранилище (идемпотентно: адрес по содержимому)."""
    if not zones.present:
        return
    try:
        stored = await storage.put_bytes(
            input_key(revision_id, zones.sha256),
            zones.raw,
            content_type="application/json",
            metadata={"sha256": zones.sha256, "parent-job-id": str(parent_id)},
        )
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    if stored.sha256 != zones.sha256 or stored.size != len(zones.raw):
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "хранилище получило другие зоны")


async def prepare(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
) -> ZonesInput:
    """Зоны вида и их вход в хранилище: общий путь автопостановки и пересчёта конструкций."""
    zones = await sheet_room_zones(
        session, storage, parent=parent, page_index=page_index, view=view
    )
    revision_id = parent.payload.get("revision_id")
    if zones.present and isinstance(revision_id, str):
        await store(storage, revision_id=uuid.UUID(revision_id), parent_id=parent.id, zones=zones)
    return zones


async def prepare_or_empty(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    page_index: int,
    view: int,
) -> ZonesInput:
    """То же, но сбой чтения зон или записи входа не прерывает вызывающего.

    Задание строится без зон, причина — в `zones_warning`. Работа идёт во вложенной транзакции,
    чтобы сбой базы не портил внешнюю (в ней пишется успех конвертации или авторазметки).
    """
    try:
        async with session.begin_nested():
            return await prepare(session, storage, parent=parent, page_index=page_index, view=view)
    except (DomainError, HTTPException, StorageUnavailableError, SQLAlchemyError) as error:
        log.warning(
            "cad_walls_zones_unavailable",
            job_id=str(parent.id),
            page_index=page_index,
            view=view,
            error=type(error).__name__,
        )
        return ZonesInput(
            b"", "", 0, "Контур плиты построен без зон помещений: зоны листа не прочитаны."
        )
