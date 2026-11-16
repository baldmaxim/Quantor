"""Выпуск базы объекта для TENDER (ADR-0051, формат `docs/tender-exchange/01-format.md`).

Кандидаты — этажи общего вида здания (`cad_building3d_assembly.build_building3d`, тот же список,
что во вкладке «Здание»): модуль только импортирует его и не меняет. Выпуск неизменяем: ZIP со всеми
файлами видов собирается в потоке и ложится в объектное хранилище, в базе остаются виды,
sha256 пакета и манифеста. Состав файла вида:

- `view.json` — кадр вида как `CadFrameRead`, уровни и размещение этажа;
- `axes.json` — оси листа в мм кадра (только принятые движком);
- `zones.json` — зоны страницы (квартиры, МОП, машино-места) в мм кадра вида;
- `constructions.json` — конструкции последнего успешного `cad_walls` и принятые человеком
  свойства (материал, толщина);
- `risers.json` — реестр стояков листа, если он введён;
- `plan.dxf` — DXF вида, только при `include_dxf`.

Зоны хранятся нормализованными (доли страницы от левого верхнего угла, ADR-0008), поэтому
переводятся в мм кадра вида тем же кодом, что в `cad_walls_zones` и `cad_partitions`:
`cad_floor3d.room_zones_to_mm`. Страница с несколькими видами: зона относится к виду, если её
центр лежит в границах вида (`preview.json`); интерфейс и задания CAD берут зоны страницы целиком,
пока вид на странице один.

Сборка ZIP — в потоке (`asyncio.to_thread`), без накопления пакета в памяти. В итоги обмера и
calc выпуск не входит.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any, Final

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.contracts.cad import CadFrameRead
from app.contracts.cad_building3d import CadBuilding3dFloorRead
from app.contracts.cad_constructions import (
    CadConstructionProps,
    CadMaterial,
    WallsConstruction,
    WallsDocument,
)
from app.contracts.cad_floor3d import WallsFloorExtras
from app.contracts.tender_exchange import (
    MAX_BASE_VIEWS,
    ObjectBaseAxes,
    ObjectBaseAxis,
    ObjectBaseBuilding,
    ObjectBaseBuildingFloor,
    ObjectBaseConstruction,
    ObjectBaseConstructions,
    ObjectBaseEngine,
    ObjectBaseFrame,
    ObjectBaseLevel,
    ObjectBaseManifest,
    ObjectBaseManifestView,
    ObjectBaseOpening,
    ObjectBasePlacement,
    ObjectBaseProject,
    ObjectBaseRelease,
    ObjectBaseRiser,
    ObjectBaseRisers,
    ObjectBaseSlab,
    ObjectBaseView,
    ObjectBaseZone,
    ObjectBaseZones,
    TenderBaseCandidateRead,
    TenderBaseCandidatesRead,
    TenderBaseReleaseCreate,
    TenderBaseReleaseRead,
    TenderBaseViewRead,
    make_view_key,
    parse_view_key,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, http_error
from app.models import (
    Document,
    Job,
    Project,
    TenderBaseRelease,
    UserIdentity,
)
from app.services import cad as cad_service
from app.services import (
    cad_building3d,
    cad_building3d_assembly,
    cad_construction_store,
    cad_floor3d,
    cad_pins,
    cad_risers,
    cad_views,
    cad_walls,
    cad_zones,
)
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

READ_CONCURRENCY: Final = 6
ZIP_CHUNK: Final = 1024 * 1024
# Отступ от границ вида при выборе зон страницы с несколькими видами, мм.
VIEW_ZONE_MARGIN_MM: Final = 500.0
ZONE_KINDS: Final = ("room_apartment", "room_mop", "parking_space")
DXF_NAME: Final = "plan_candidates.dxf"

# Подписи материалов конструкции: в базе для человека и навыка, не коды движка (формат, образец).
MATERIAL_LABELS: Final[dict[str, str]] = {
    "aerated_concrete": "газобетон",
    "expanded_clay_block": "керамзитобетонный блок",
    "ceramic_block": "керамический блок",
    "brick_solid": "кирпич полнотелый",
    "brick_hollow": "кирпич пустотелый",
    "silicate_block": "силикатный блок",
    "gypsum_tongue_groove": "пазогребневая плита",
    "monolith_concrete": "монолитный железобетон",
    "other": "другое",
}


def view_dir(page_index: int, view: int, revision_id: uuid.UUID) -> str:
    """`p<page_index:04d>-v<view>-<первые 8 знаков revision_id>`."""
    return f"p{page_index:04d}-v{view}-{str(revision_id)[:8]}"


def package_key(project_id: uuid.UUID, release_id: uuid.UUID) -> str:
    return f"projects/{project_id}/tender/base/{release_id}.zip"


# --------------------------------------------------------------------------- источники видов


@dataclass(frozen=True, slots=True)
class ViewSource:
    """Вид проекта, собранный из базы и хранилища: этаж здания, лист, задание, DXF и кадр."""

    key: str
    dir: str
    floor: CadBuilding3dFloorRead
    sheet: cad_building3d.SheetRef
    job: Job
    document_title: str
    dxf_sha256: str | None
    dxf_key: str | None
    frame: CadFrameRead
    page_size_pt: tuple[float, float] | None
    problems: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.problems


def _artifact(job: Job, revision_id: uuid.UUID, name: str) -> tuple[dict[str, Any], str] | None:
    """Файл итога текущей попытки задания и его ключ в хранилище; нет или ключ чужой - `None`."""
    attempt = cad_service.current_result(job).get("attempt")
    if type(attempt) is not int:
        return None
    artifact = cad_service.find_artifact(job, name, attempt)
    if artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, job.id, attempt, name)
    return (artifact, key) if artifact.get("key") == key else None


async def _read_frame(storage: ObjectStorage, sheet: cad_building3d.SheetRef) -> CadFrameRead:
    """Кадр вида листа; не читается - неподтверждённый с причиной (как у 3D-вида здания)."""

    def unconfirmed(reason: str) -> CadFrameRead:
        return CadFrameRead(
            confirmed=False, reason=reason, units=None, origin_pt=None, mm_per_pdf_point=None
        )

    if sheet.scale_key is None or sheet.checks_key is None:
        return unconfirmed("масштаб и проверки вида не найдены")
    try:
        scale = cad_views.scale_from(await cad_views.read_json(storage, sheet.scale_key))
        checks = await cad_views.read_json(storage, sheet.checks_key)
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    except (ObjectNotFoundError, cad_views.ArtifactTooLargeError, ValueError):
        return unconfirmed("масштаб или проверки вида не читаются")
    return cad_views.frame_from(scale, checks)


async def load_sources(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[list[ViewSource], list[str]]:
    """Виды проекта в порядке этажей «Здания» и предупреждения сборки здания."""
    building = await cad_building3d_assembly.build_building3d(
        session, storage, workspace_id=workspace_id, project_id=project_id
    )
    warnings = [warning.message for warning in building.warnings]
    if not building.floors:
        return [], warnings
    sheets, _warnings, _slab = await cad_building3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    sheet_by_key = {(s.revision_id, s.page_index, s.view): s for s in sheets}
    job_ids = {floor.job_id for floor in building.floors}
    jobs = {job.id: job for job in await session.scalars(select(Job).where(Job.id.in_(job_ids)))}
    document_ids = {floor.document_id for floor in building.floors if floor.document_id}
    titles = {
        document.id: document.display_name
        for document in await session.scalars(select(Document).where(Document.id.in_(document_ids)))
    }
    gate = asyncio.Semaphore(READ_CONCURRENCY)

    async def frame_of(sheet: cad_building3d.SheetRef) -> CadFrameRead:
        async with gate:
            return await _read_frame(storage, sheet)

    pairs: list[tuple[CadBuilding3dFloorRead, cad_building3d.SheetRef, Job]] = []
    for floor in building.floors:
        sheet = sheet_by_key.get((floor.revision_id, floor.page_index, floor.view))
        job = jobs.get(floor.job_id)
        if sheet is not None and job is not None:
            pairs.append((floor, sheet, job))
    frames = await asyncio.gather(*(frame_of(sheet) for _f, sheet, _j in pairs))
    page_sizes = await _page_sizes(session, [floor for floor, _s, _j in pairs])

    sources: list[ViewSource] = []
    for (floor, sheet, job), frame in zip(pairs, frames, strict=True):
        problems: list[str] = []
        dxf = _artifact(
            job,
            floor.revision_id,
            f"{cad_service.view_folder(floor.page_index, floor.view)}/{DXF_NAME}",
        )
        dxf_sha = str(dxf[0].get("sha256")) if dxf is not None else None
        if dxf is None or dxf_sha is None or len(dxf_sha) != 64:
            problems.append("DXF вида не найден")
            dxf_sha = None
        if not frame.confirmed or frame.origin_pt is None or not frame.mm_per_pdf_point:
            problems.append(frame.reason or "кадр вида не подтверждён")
        size = page_sizes.get((floor.revision_id, floor.page_index))
        if size is None:
            problems.append("нет геометрии страницы")
        key = make_view_key(floor.revision_id, floor.page_index, floor.view)
        sources.append(
            ViewSource(
                key=key,
                dir=view_dir(floor.page_index, floor.view, floor.revision_id),
                floor=floor,
                sheet=sheet,
                job=job,
                document_title=titles.get(floor.document_id, floor.label)
                if floor.document_id
                else floor.label,
                dxf_sha256=dxf_sha,
                dxf_key=dxf[1] if dxf is not None else None,
                frame=frame,
                page_size_pt=size,
                problems=problems,
            )
        )
    return sources, warnings


async def _page_sizes(
    session: AsyncSession, floors: Sequence[CadBuilding3dFloorRead]
) -> dict[tuple[uuid.UUID, int], tuple[float, float]]:
    """Отображаемый размер страницы в пунктах PDF по ревизиям и страницам."""
    pages_by_revision: dict[uuid.UUID, set[int]] = {}
    for floor in floors:
        pages_by_revision.setdefault(floor.revision_id, set()).add(floor.page_index)
    sizes: dict[tuple[uuid.UUID, int], tuple[float, float]] = {}
    for revision_id, pages in pages_by_revision.items():
        scales = await cad_zones.page_scales(session, revision_id=revision_id, page_indexes=pages)
        for page_index, scale in scales.items():
            if scale.geometry is not None:
                sizes[(revision_id, page_index)] = (
                    float(scale.geometry.display_width_pt),
                    float(scale.geometry.display_height_pt),
                )
    return sizes


def candidate_read(source: ViewSource) -> TenderBaseCandidateRead:
    floor = source.floor
    return TenderBaseCandidateRead(
        view_key=source.key,
        dir=source.dir,
        revision_id=floor.revision_id,
        document_id=floor.document_id,
        document_title=source.document_title,
        page_index=floor.page_index,
        view=floor.view,
        label=floor.label,
        corps=floor.corps,
        section=floor.section,
        group_key=floor.group_key,
        group_label=floor.group_label,
        floors=[floor.label],
        base_z_mm=floor.base_z_mm,
        offset_mm=floor.offset_mm,
        alignment=floor.alignment,
        dxf_sha256=source.dxf_sha256,
        ready=source.ready,
        problems=list(source.problems),
    )


async def list_candidates(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> TenderBaseCandidatesRead:
    sources, warnings = await load_sources(
        session, storage, workspace_id=workspace_id, project_id=project_id
    )
    return TenderBaseCandidatesRead(
        candidates=[candidate_read(source) for source in sources], warnings=warnings
    )


# --------------------------------------------------------------------------- текущий DXF видов


async def current_dxf_hashes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    view_keys: Sequence[str],
) -> dict[str, str | None]:
    """Текущий sha256 DXF каждого вида: из последнего успешного преобразования его ревизии.

    Вид, которого в проекте больше нет (переконвертирован без него), получает `None`.
    """
    wanted: dict[uuid.UUID, list[tuple[str, int, int]]] = {}
    for key in dict.fromkeys(view_keys):
        revision_id, page_index, view = parse_view_key(key)
        wanted.setdefault(revision_id, []).append((key, page_index, view))
    result: dict[str, str | None] = {}
    for revision_id, entries in wanted.items():
        jobs = await session.scalars(
            select(Job)
            .where(
                Job.workspace_id == workspace_id,
                Job.project_id == project_id,
                Job.job_type == JobType.CAD_PDF_CONVERT,
                Job.status == JobStatus.SUCCEEDED,
                Job.payload["revision_id"].astext == str(revision_id),
            )
            .order_by(Job.created_at.desc(), Job.id)
        )
        ordered = list(jobs)
        for key, page_index, view in entries:
            result[key] = None
            for job in ordered:
                artifact = cad_walls.view_has_dxf(job, page_index, view)
                if artifact is not None:
                    sha = artifact.get("sha256")
                    result[key] = sha if isinstance(sha, str) else None
                    break
    return result


# --------------------------------------------------------------------------- файлы вида


def _dump(model: BaseModel) -> bytes:
    """Канонический вид файла пакета: UTF-8, без пробелов, поля в порядке модели."""
    return json.dumps(
        model.model_dump(mode="json", by_alias=True), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _ring(points: Sequence[Sequence[float]]) -> list[list[int]]:
    """Кольцо в целых мм без замыкающей точки."""
    ring = [[round(point[0]), round(point[1])] for point in points]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    return ring


def _ring_area_m2(ring: Sequence[Sequence[int]]) -> float:
    twice = 0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        twice += x0 * y1 - x1 * y0
    return round(abs(twice) / 2 / 1_000_000, 2)


def _centroid(ring: Sequence[Sequence[int]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in ring) / len(ring),
        sum(point[1] for point in ring) / len(ring),
    )


def _material_label(
    construction: WallsConstruction, props: CadConstructionProps | None
) -> str | None:
    """Материал: принятый человеком, иначе однозначная подсказка условных обозначений."""
    code: CadMaterial | None = None
    if props is not None and props.material is not None:
        code = props.material
    else:
        hint = construction.material_hint
        if hint is not None and hint.status == "matched" and hint.value is not None:
            code = hint.value
    return None if code is None else MATERIAL_LABELS.get(code, code)


def _thickness(construction: WallsConstruction, props: CadConstructionProps | None) -> int | None:
    """Толщина номинала; принятое человеком значение главнее. Нет номинала - `None`."""
    if props is not None and props.thickness_override_mm is not None:
        return int(props.thickness_override_mm)
    if construction.thickness_nominal_mm is not None:
        return round(construction.thickness_nominal_mm)
    return None


def build_constructions(
    document: WallsDocument,
    extras: WallsFloorExtras,
    accepted_props: dict[str, CadConstructionProps],
) -> ObjectBaseConstructions:
    """`constructions.json`: конструкции и проёмы вида, плита; свойства - только принятые."""
    constructions: list[ObjectBaseConstruction] = []
    for item in [*document.constructions, *document.frame_partitions]:
        if item.kind == "floor_slab":
            continue
        shell = _ring(item.polygon.shell)
        if len(shell) < 3:
            continue
        props = accepted_props.get(item.id)
        constructions.append(
            ObjectBaseConstruction(
                id=item.id,
                kind=item.kind,
                material=_material_label(item, props),
                thickness_mm=_thickness(item, props),
                shell=shell,
                holes=[ring for hole in item.polygon.holes if len(ring := _ring(hole)) >= 3],
            )
        )
    directions = {opening.id: opening.direction for opening in extras.openings}
    openings: list[ObjectBaseOpening] = []
    for opening in document.openings:
        if len(opening.center) < 2:
            continue
        direction = directions.get(opening.id)
        openings.append(
            ObjectBaseOpening(
                id=opening.id,
                kind=opening.kind,
                host_id=opening.host_id,
                width_mm=round(opening.width_mm),
                center=[round(opening.center[0]), round(opening.center[1])],
                direction=(
                    [round(direction[0]), round(direction[1])]
                    if direction is not None and len(direction) >= 2
                    else None
                ),
            )
        )
    slab: ObjectBaseSlab | None = None
    if extras.slab is not None and len(shell := _ring(extras.slab.shell)) >= 3:
        slab = ObjectBaseSlab(shell=shell)
    return ObjectBaseConstructions(
        schema_name="quantor.object_base.constructions.v1",
        constructions=constructions,
        openings=openings,
        slab=slab,
    )


def build_axes(raw_walls: Any, frame: CadFrameRead) -> ObjectBaseAxes:
    """`axes.json`: оси листа в мм кадра вида (те же, по которым «Здание» совмещает этажи)."""
    axes = cad_building3d.axes_in_mm(raw_walls, frame)
    rows = [
        ObjectBaseAxis(label=label, orient="vertical", pos_mm=round(pos))
        for label, pos in sorted(axes.vertical.items())
    ] + [
        ObjectBaseAxis(label=label, orient="horizontal", pos_mm=round(pos))
        for label, pos in sorted(axes.horizontal.items())
    ]
    return ObjectBaseAxes(schema_name="quantor.object_base.axes.v1", axes=rows)


def build_zones(
    rows: Sequence[Any],
    *,
    page_size_pt: tuple[float, float],
    origin_pt: tuple[float, float],
    mm_per_pdf_point: float,
    view_bbox_mm: Sequence[float] | None,
) -> ObjectBaseZones:
    """`zones.json`: зоны страницы в мм кадра вида; `view_bbox_mm` - границы вида при нескольких."""
    zones: list[ObjectBaseZone] = []
    for zone in rows:
        if zone.kind not in ZONE_KINDS or len(zone.points) < 3:
            continue
        (mapped,) = cad_floor3d.room_zones_to_mm(
            [cad_floor3d.RoomZoneNormalized(zone.kind, [list(p) for p in zone.points])],
            page_width_pt=page_size_pt[0],
            page_height_pt=page_size_pt[1],
            origin_pt=origin_pt,
            mm_per_pdf_point=mm_per_pdf_point,
        )
        ring = _ring(mapped.shell)
        if len(ring) < 3:
            continue
        if view_bbox_mm is not None:
            cx, cy = _centroid(ring)
            margin = VIEW_ZONE_MARGIN_MM
            if not (
                view_bbox_mm[0] - margin <= cx <= view_bbox_mm[2] + margin
                and view_bbox_mm[1] - margin <= cy <= view_bbox_mm[3] + margin
            ):
                continue
        room_type, _source = cad_zones.effective_room_type(zone.kind, zone.room_type, zone.name)
        zones.append(
            ObjectBaseZone(
                id=zone.id,
                kind=zone.kind,
                apartment_no=zone.apartment_no,
                room_mark=zone.room_mark,
                name=zone.name,
                room_type=room_type,
                area_m2=_ring_area_m2(ring),
                points=ring,
            )
        )
    return ObjectBaseZones(schema_name="quantor.object_base.zones.v1", zones=zones)


def build_view(source: ViewSource) -> ObjectBaseView:
    """`view.json`: кадр вида, уровни и размещение этажа в здании."""
    floor, frame = source.floor, source.frame
    assert frame.origin_pt is not None and frame.mm_per_pdf_point is not None
    assert source.page_size_pt is not None
    return ObjectBaseView(
        schema_name="quantor.object_base.view.v1",
        key=source.key,
        frame=ObjectBaseFrame(
            mm_per_pdf_point=frame.mm_per_pdf_point,
            origin_pt=list(frame.origin_pt),
            page_size_pt=list(source.page_size_pt),
            confirmed=frame.confirmed,
        ),
        level=ObjectBaseLevel(
            floor_elevation_mm=floor.base_z_mm,
            floor_height_mm=floor.floor_height_mm,
            slab_thickness_mm=floor.slab_thickness_mm,
            elevation_known=floor.elevation_known,
            floor_height_known=floor.floor_height_known,
            slab_thickness_known=floor.slab_thickness_known,
        ),
        placement=ObjectBasePlacement(
            group_key=floor.group_key,
            group_label=floor.group_label,
            offset_mm=[round(floor.offset_mm[0]), round(floor.offset_mm[1])],
            alignment=floor.alignment,
            alignment_axes=list(floor.alignment_axes),
        ),
        bbox=[round(value) for value in floor.bbox] if floor.bbox is not None else None,
    )


def build_risers(entries: Sequence[Any]) -> ObjectBaseRisers:
    return ObjectBaseRisers(
        schema_name="quantor.object_base.risers.v1",
        risers=[
            ObjectBaseRiser(
                system=entry.system.value,
                mark=entry.mark,
                dn_mm=entry.dn_mm,
                role=entry.role.value,
                count=entry.count,
                shaft_id=entry.shaft_id,
                source=entry.source,
                note=entry.note,
            )
            for entry in entries
        ],
    )


# --------------------------------------------------------------------------- сборка ZIP


class _ZipSink:
    """Запись в ZIP из асинхронного кода: каждая запись - в потоке, sha256 считается на лету."""

    def __init__(self, target: IO[bytes]) -> None:
        self._zip = zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
        self._moment = datetime.now(UTC).timetuple()[:6]
        self.files: dict[str, str] = {}

    def _info(self, name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, date_time=self._moment)
        info.compress_type = zipfile.ZIP_DEFLATED
        return info

    async def add_bytes(self, name: str, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        await asyncio.to_thread(self._zip.writestr, self._info(name), data)
        self.files[name] = sha
        return sha

    async def add_stream(self, name: str, chunks: AsyncIterator[bytes]) -> str:
        digest = hashlib.sha256()
        handle = await asyncio.to_thread(self._zip.open, self._info(name), "w", force_zip64=True)
        try:
            async for chunk in chunks:
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
        finally:
            await asyncio.to_thread(handle.close)
        self.files[name] = digest.hexdigest()
        return self.files[name]

    async def close(self) -> None:
        await asyncio.to_thread(self._zip.close)


async def _file_chunks(handle: IO[bytes]) -> AsyncIterator[bytes]:
    while chunk := await asyncio.to_thread(handle.read, ZIP_CHUNK):
        yield chunk


def _engine_versions(settings: Settings, walls_generator: str | None) -> ObjectBaseEngine:
    cad_mep: str | None = None
    try:
        cad_mep = cad_pins.load_generator_pin(settings, "cad_mep").generator_version
    except DomainError:
        cad_mep = None
    return ObjectBaseEngine(
        version=cad_service.ENGINE_VERSION, cad_walls=walls_generator, cad_mep=cad_mep
    )


async def _read_walls(
    storage: ObjectStorage, source: ViewSource
) -> tuple[Any, WallsDocument, WallsFloorExtras]:
    key = source.sheet.walls_key
    if key is None:
        raise DomainError(
            ErrorCode.CAD_WALLS_NOT_READY, f"{source.floor.label}: конструкции вида не посчитаны"
        )
    try:
        raw = await cad_views.read_json(storage, key)
        document = await asyncio.to_thread(WallsDocument.model_validate, raw)
        extras = await asyncio.to_thread(WallsFloorExtras.model_validate, raw)
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    except (ObjectNotFoundError, cad_views.ArtifactTooLargeError, ValueError, ValidationError) as e:
        raise DomainError(
            ErrorCode.CAD_ENGINE_FAILED, f"{source.floor.label}: walls.json не читается"
        ) from e
    return raw, document, extras


async def _view_bbox(storage: ObjectStorage, source: ViewSource) -> list[float] | None:
    """Границы вида из preview.json (мм DXF); нет файла - `None` (зоны страницы целиком)."""
    folder = cad_service.view_folder(source.floor.page_index, source.floor.view)
    found = _artifact(source.job, source.floor.revision_id, f"{folder}/preview.json")
    if found is None:
        return None
    try:
        preview = await cad_views.read_json(storage, found[1])
    except (ObjectNotFoundError, cad_views.ArtifactTooLargeError, ValueError):
        return None
    bbox = preview.get("bbox") if isinstance(preview, dict) else None
    if (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in bbox)
    ):
        return [float(v) for v in bbox]
    return None


def _views_on_page(source: ViewSource) -> int:
    """Сколько видов с DXF у страницы в итоге преобразования."""
    count = 0
    for page in cad_service.current_result(source.job).get("pages", []):
        if isinstance(page, dict) and page.get("index") == source.floor.page_index:
            for row in page.get("views", []):
                view = row.get("view") if isinstance(row, dict) else None
                if (
                    type(view) is int
                    and cad_walls.view_has_dxf(source.job, source.floor.page_index, view)
                    is not None
                ):
                    count += 1
    return count


async def _write_view(
    session: AsyncSession,
    storage: ObjectStorage,
    sink: _ZipSink,
    source: ViewSource,
    *,
    include_dxf: bool,
) -> str | None:
    """Файлы одного вида в пакет. Возвращает версию генератора конструкций из walls.json."""
    floor, frame = source.floor, source.frame
    assert frame.origin_pt is not None and frame.mm_per_pdf_point is not None
    assert source.page_size_pt is not None
    raw, document, extras = await _read_walls(storage, source)
    props = await cad_construction_store.load_props(
        session, revision_id=floor.revision_id, page_index=floor.page_index, view=floor.view
    )
    accepted = {key: value for key, (value, is_accepted) in props.items() if is_accepted}
    zone_rows = await cad_zones.list_zones(
        session, revision_id=floor.revision_id, page_index=floor.page_index
    )
    bbox = await _view_bbox(storage, source) if _views_on_page(source) > 1 else None
    risers = await cad_risers.load_risers(
        session, revision_id=floor.revision_id, page_index=floor.page_index, view=floor.view
    )
    base = f"views/{source.dir}"
    await sink.add_bytes(f"{base}/view.json", _dump(build_view(source)))
    await sink.add_bytes(f"{base}/axes.json", _dump(build_axes(raw, frame)))
    await sink.add_bytes(
        f"{base}/zones.json",
        _dump(
            build_zones(
                zone_rows,
                page_size_pt=source.page_size_pt,
                origin_pt=(frame.origin_pt[0], frame.origin_pt[1]),
                mm_per_pdf_point=frame.mm_per_pdf_point,
                view_bbox_mm=bbox,
            )
        ),
    )
    await sink.add_bytes(
        f"{base}/constructions.json", _dump(build_constructions(document, extras, accepted))
    )
    if risers:
        await sink.add_bytes(f"{base}/risers.json", _dump(build_risers(risers)))
    if include_dxf and source.dxf_key is not None:
        await sink.add_stream(f"{base}/plan.dxf", storage.iter_stream(source.dxf_key))
    return document.generator


def _select(sources: Sequence[ViewSource], view_keys: Sequence[str] | None) -> list[ViewSource]:
    """Виды выпуска: названные или все готовые. Неизвестный или неготовый - отказ со списком."""
    if view_keys is None:
        chosen = [source for source in sources if source.ready]
    else:
        by_key = {source.key.lower(): source for source in sources}
        chosen = []
        problems: list[str] = []
        for key in dict.fromkeys(view_keys):
            source = by_key.get(key.lower())
            if source is None:
                problems.append(f"{key}: вида нет в здании проекта")
            elif not source.ready:
                problems.append(f"{source.floor.label} ({key}): {'; '.join(source.problems)}")
            else:
                chosen.append(source)
        if problems:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "Не все виды годятся для выпуска: " + " | ".join(problems),
            )
    if not chosen:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Нет видов, готовых к выпуску базы")
    if len(chosen) > MAX_BASE_VIEWS:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, f"В выпуске не больше {MAX_BASE_VIEWS} видов"
        )
    return chosen


def _author_name(context: AuthContext) -> str:
    principal = context.principal
    return principal.display_name or principal.email or principal.label


async def create_release(
    session: AsyncSession,
    storage: ObjectStorage,
    settings: Settings,
    *,
    context: AuthContext,
    project: Project,
    body: TenderBaseReleaseCreate,
) -> tuple[TenderBaseRelease, str | None]:
    """Выпуск базы объекта: ZIP в хранилище и строка выпуска.

    Транзакция держит блокировку проекта на время сборки: номер выпуска нужен манифесту, а два
    параллельных выпуска одного проекта получили бы один номер. Возвращает выпуск и имя
    выпустившего (для ответа).
    """
    await session.scalar(select(Project.id).where(Project.id == project.id).with_for_update())
    sources, _warnings = await load_sources(
        session, storage, workspace_id=project.workspace_id, project_id=project.id
    )
    chosen = _select(sources, body.view_keys)
    number = (
        await session.scalar(
            select(func.coalesce(func.max(TenderBaseRelease.number), 0)).where(
                TenderBaseRelease.project_id == project.id
            )
        )
        or 0
    ) + 1
    release_id = uuid.uuid4()
    released_at = datetime.now(UTC).replace(microsecond=0)
    author = _author_name(context)

    stored_key = package_key(project.id, release_id)
    with tempfile.TemporaryFile() as target:
        sink = _ZipSink(target)
        walls_generator: str | None = None
        for source in chosen:
            generator = await _write_view(
                session, storage, sink, source, include_dxf=body.include_dxf
            )
            walls_generator = walls_generator or generator
        building = ObjectBaseBuilding(
            schema_name="quantor.object_base.building.v1",
            floors=[
                ObjectBaseBuildingFloor(
                    view_key=source.key,
                    label=source.floor.label,
                    group_key=source.floor.group_key,
                    base_z_mm=source.floor.base_z_mm,
                    floor_height_mm=source.floor.floor_height_mm,
                    offset_mm=[
                        round(source.floor.offset_mm[0]),
                        round(source.floor.offset_mm[1]),
                    ],
                    alignment=source.floor.alignment,
                )
                for source in chosen
            ],
        )
        await sink.add_bytes("building.json", _dump(building))
        manifest = ObjectBaseManifest(
            schema_name="quantor.object_base.v1",
            release=ObjectBaseRelease(
                id=release_id,
                number=number,
                released_at=released_at,
                released_by=author,
                comment=body.comment,
            ),
            project=ObjectBaseProject(id=project.id, name=project.name),
            engine=_engine_versions(settings, walls_generator),
            units="mm",
            frame="view_dxf_mm",
            z_reference="finished_floor",
            views=[
                ObjectBaseManifestView(
                    key=source.key,
                    dir=f"views/{source.dir}",
                    revision_id=source.floor.revision_id,
                    document_id=source.floor.document_id,
                    document_title=source.document_title,
                    page_index=source.floor.page_index,
                    view=source.floor.view,
                    sheet_label=source.floor.label,
                    dxf_sha256=source.dxf_sha256 or "",
                    corps=source.floor.corps,
                    section=source.floor.section,
                    floors=[source.floor.label],
                )
                for source in chosen
            ],
            files=dict(sink.files),
        )
        manifest_sha = await sink.add_bytes("manifest.json", _dump(manifest))
        await sink.close()
        size = await asyncio.to_thread(target.seek, 0, 2)
        await asyncio.to_thread(target.seek, 0)
        try:
            stored = await storage.put_stream(
                stored_key,
                _file_chunks(target),
                content_type="application/zip",
                original_filename=f"quantor-base-{number}.zip",
            )
        except StorageUnavailableError as error:
            raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    if stored.size != size:
        await storage.delete(stored_key)
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "хранилище приняло пакет не полностью")

    release = TenderBaseRelease(
        id=release_id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        number=number,
        comment=body.comment,
        released_by=context.principal.user_id,
        released_at=released_at,
        include_dxf=body.include_dxf,
        views=[
            {
                "key": source.key,
                "dir": f"views/{source.dir}",
                "revision_id": str(source.floor.revision_id),
                "page_index": source.floor.page_index,
                "view": source.floor.view,
                "job_id": str(source.job.id),
                "dxf_sha256": source.dxf_sha256,
                "document_title": source.document_title,
                "label": source.floor.label,
                "corps": source.floor.corps,
                "section": source.floor.section,
                "floors": [source.floor.label],
            }
            for source in chosen
        ],
        package_key=stored_key,
        package_sha256=stored.sha256,
        manifest_sha256=manifest_sha,
        size_bytes=stored.size,
    )
    session.add(release)
    await session.flush()
    return release, author


# --------------------------------------------------------------------------- чтение и отзыв


async def user_names(
    session: AsyncSession, user_ids: Sequence[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    ids = {user_id for user_id in user_ids if user_id is not None}
    if not ids:
        return {}
    rows = await session.scalars(select(UserIdentity).where(UserIdentity.id.in_(ids)))
    return {user.id: user.display_name or user.email or user.subject for user in rows}


def release_read(release: TenderBaseRelease, names: dict[uuid.UUID, str]) -> TenderBaseReleaseRead:
    return TenderBaseReleaseRead(
        id=release.id,
        project_id=release.project_id,
        number=release.number,
        comment=release.comment,
        released_by_name=names.get(release.released_by) if release.released_by else None,
        released_at=release.released_at,
        include_dxf=release.include_dxf,
        views=[TenderBaseViewRead.model_validate(view) for view in release.views],
        package_sha256=release.package_sha256,
        manifest_sha256=release.manifest_sha256,
        size_bytes=release.size_bytes,
        revoked_at=release.revoked_at,
        revoked_by_name=names.get(release.revoked_by) if release.revoked_by else None,
    )


async def list_releases(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[TenderBaseRelease]:
    rows = await session.scalars(
        select(TenderBaseRelease)
        .where(
            TenderBaseRelease.workspace_id == workspace_id,
            TenderBaseRelease.project_id == project_id,
        )
        .order_by(TenderBaseRelease.number.desc())
    )
    return list(rows)


async def get_release(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    release_id: uuid.UUID,
    lock: bool = False,
) -> TenderBaseRelease | None:
    query = select(TenderBaseRelease).where(
        TenderBaseRelease.id == release_id,
        TenderBaseRelease.workspace_id == workspace_id,
        TenderBaseRelease.project_id == project_id,
    )
    if lock:
        query = query.with_for_update()
    release: TenderBaseRelease | None = await session.scalar(query)
    return release


async def revoke_release(
    session: AsyncSession, release: TenderBaseRelease, *, user_id: uuid.UUID
) -> bool:
    """Отзыв выпуска: новые расчёты по нему не принимаются, пакет остаётся. Повтор - без эффекта."""
    if release.revoked_at is not None:
        return False
    release.revoked_at = datetime.now(UTC)
    release.revoked_by = user_id
    await session.flush()
    return True
