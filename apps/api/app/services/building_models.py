"""Приём и чтение модели здания (ADR-0053): версии, части, фиксация, утверждение.

Правила проверки - `model_package`; здесь база и объектное хранилище. Выгрузка идёт по частям:
`start_version` принимает манифест, `store_part` - каждую объявленную часть (размер и sha256
сверяются с манифестом на приёме), `commit_version` проверяет пакет целиком и делает версию
кандидатом. Утверждает человек.
"""

from __future__ import annotations

import json
import struct
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import ModelVersionStatus
from app.errors import DomainError, ErrorCode
from app.models import BuildingModelVersion, ModelPart, ModelStorey, Project
from app.services import model_package as qmp
from app.storage.base import ObjectNotFoundError, ObjectStorage
from app.storage.keys import model_part_key

MANIFEST_PATH = "manifest.json"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PRELOAD_BYTES = 256 * 1024 * 1024
MAX_WARNINGS = 200
MAX_REPORTED_ERRORS = 10
MAX_COMMENT = 500
_CONTENT_TYPES = {
    ".glb": "model/gltf-binary",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
}


def _invalid(code: str, where: str, message: str) -> DomainError:
    return DomainError(
        ErrorCode.MODEL_PACKAGE_INVALID, message, issue={"code": code, "where": where}
    )


def _report_error(report: qmp.Report) -> DomainError:
    errors = report.errors
    first = errors[0]
    lines = [f"{item.code} @ {item.where}: {item.message}" for item in errors[:MAX_REPORTED_ERRORS]]
    return DomainError(
        ErrorCode.MODEL_PACKAGE_INVALID,
        "Пакет модели не прошёл проверку:\n" + "\n".join(lines),
        issue={"code": first.code, "where": first.where, "errors": len(errors)},
    )


def content_type_of(path: str) -> str:
    for suffix, content_type in _CONTENT_TYPES.items():
        if path.endswith(suffix):
            return content_type
    return "application/octet-stream"


async def get_version(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    lock: bool = False,
) -> BuildingModelVersion | None:
    query = select(BuildingModelVersion).where(
        BuildingModelVersion.id == version_id,
        BuildingModelVersion.project_id == project_id,
        BuildingModelVersion.workspace_id == workspace_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(query)).scalar_one_or_none()


async def list_versions(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[BuildingModelVersion]:
    rows = await session.execute(
        select(BuildingModelVersion)
        .where(
            BuildingModelVersion.project_id == project_id,
            BuildingModelVersion.workspace_id == workspace_id,
        )
        .order_by(BuildingModelVersion.number.desc())
    )
    return list(rows.scalars())


async def storeys_of(session: AsyncSession, version_id: uuid.UUID) -> list[ModelStorey]:
    """Этажи в порядке storeys.json (по зданиям, внутри по отметке); прежние версии - по отметке."""
    rows = await session.execute(
        select(ModelStorey)
        .where(ModelStorey.version_id == version_id)
        .order_by(ModelStorey.position.asc().nulls_last(), ModelStorey.elevation_mm)
    )
    return list(rows.scalars())


async def parts_of(session: AsyncSession, version_id: uuid.UUID) -> list[ModelPart]:
    rows = await session.execute(
        select(ModelPart).where(ModelPart.version_id == version_id).order_by(ModelPart.path)
    )
    return list(rows.scalars())


async def _read_all(storage: ObjectStorage, key: str, *, limit: int) -> bytes:
    out = bytearray()
    try:
        async for chunk in storage.iter_stream(key):
            out += chunk
            if len(out) > limit:
                raise _invalid("PART_SIZE", key, "Часть больше допустимого размера чтения")
    except ObjectNotFoundError as error:
        raise _invalid("PART_MISSING", key, "Часть не найдена в хранилище") from error
    return bytes(out)


async def _read_head(storage: ObjectStorage, key: str) -> bytes:
    """Заголовок GLB и его JSON-блок: сначала 20 байт, затем объявленная длина JSON."""
    out = bytearray()
    need = 20
    try:
        async for chunk in storage.iter_stream(key):
            out += chunk
            if len(out) >= 20 and need == 20:
                need = 20 + min(struct.unpack_from("<I", out, 12)[0], qmp.MAX_GLB_JSON_BYTES)
            if len(out) >= need:
                break
    except ObjectNotFoundError as error:
        raise _invalid("PART_MISSING", key, "Часть не найдена в хранилище") from error
    return bytes(out[:need]) if need > 20 else bytes(out)


async def _manifest_of(
    storage: ObjectStorage, version: BuildingModelVersion
) -> tuple[bytes, qmp.Manifest]:
    key = model_part_key(version.project_id, version.id, MANIFEST_PATH)
    data = await _read_all(storage, key, limit=MAX_MANIFEST_BYTES)
    manifest, _raw = qmp.parse_manifest(data, qmp.Report())
    if manifest is None:
        raise _invalid("MANIFEST_SCHEMA", MANIFEST_PATH, "Сохранённый манифест не читается")
    return data, manifest


async def start_version(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    manifest_bytes: bytes,
    tender_version_id: uuid.UUID | None = None,
    comment: str | None = None,
) -> tuple[BuildingModelVersion, bool]:
    """Начинает выгрузку по манифесту; тот же манифест повторно возвращает прежнюю версию."""
    report = qmp.Report()
    manifest, raw = qmp.parse_manifest(manifest_bytes, report)
    if manifest is not None:
        qmp.check_manifest(manifest, raw, report)
    if manifest is None or not report.ok:
        raise _report_error(report)
    await session.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    existing = (
        await session.execute(
            select(BuildingModelVersion).where(
                BuildingModelVersion.project_id == project_id,
                BuildingModelVersion.manifest_sha256 == manifest.manifest_sha256,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    number = (
        await session.execute(
            select(func.coalesce(func.max(BuildingModelVersion.number), 0)).where(
                BuildingModelVersion.project_id == project_id
            )
        )
    ).scalar_one() + 1
    version_id = uuid.uuid4()
    generator = manifest.generator.get("name")
    version = BuildingModelVersion(
        id=version_id,
        workspace_id=workspace_id,
        project_id=project_id,
        tender_version_id=tender_version_id,
        number=number,
        status=ModelVersionStatus.UPLOADING,
        source_kind=manifest.source.kind,
        manifest_sha256=manifest.manifest_sha256,
        generator=(
            f"{generator} {manifest.generator.get('version', '')}".strip() if generator else None
        ),
        storage_prefix=f"models/{project_id}/{version_id}/",
        counts=manifest.counts.model_dump(),
        warnings=[],
        comment=comment[:MAX_COMMENT] if comment else None,
        created_by=user_id,
    )
    session.add(version)
    await storage.put_bytes(
        model_part_key(project_id, version_id, MANIFEST_PATH),
        manifest_bytes,
        content_type="application/json",
        original_filename=MANIFEST_PATH,
    )
    await session.flush()
    return version, True


async def missing_parts(
    session: AsyncSession, storage: ObjectStorage, version: BuildingModelVersion
) -> list[str]:
    """Объявленные в манифесте части, которых ещё нет среди принятых."""
    _data, manifest = await _manifest_of(storage, version)
    have = {part.path for part in await parts_of(session, version.id)}
    return [part.path for part in manifest.parts if part.path not in have]


async def _guarded(chunks: AsyncIterator[bytes], *, limit: int, path: str) -> AsyncIterator[bytes]:
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise _invalid("PART_SIZE", path, "Часть больше объявленного размера")
        yield chunk


async def store_part(
    session: AsyncSession,
    storage: ObjectStorage,
    version: BuildingModelVersion,
    path: str,
    chunks: AsyncIterator[bytes],
) -> ModelPart:
    """Принимает одну часть: путь объявлен в манифесте, размер и sha256 совпали."""
    if version.status is not ModelVersionStatus.UPLOADING:
        raise DomainError(ErrorCode.MODEL_VERSION_STATE, "Версия уже зафиксирована")
    _data, manifest = await _manifest_of(storage, version)
    declared = next((part for part in manifest.parts if part.path == path), None)
    if declared is None:
        raise _invalid("PART_UNDECLARED", path, "Часть не объявлена в манифесте")
    key = model_part_key(version.project_id, version.id, path)
    try:
        stored = await storage.put_stream(
            key,
            _guarded(chunks, limit=declared.bytes, path=path),
            content_type=content_type_of(path),
            original_filename=path,
        )
        if stored.size != declared.bytes or stored.sha256 != declared.sha256:
            raise _invalid("PART_HASH", path, "Размер или sha256 части не совпали с манифестом")
    except Exception:
        await storage.delete(key)
        raise
    row = (
        await session.execute(
            select(ModelPart).where(ModelPart.version_id == version.id, ModelPart.path == path)
        )
    ).scalar_one_or_none()
    if row is None:
        row = ModelPart(version_id=version.id, path=path, storage_key=key)
        session.add(row)
    row.kind = declared.kind
    row.storey_key = declared.storey_key
    row.discipline = declared.discipline
    row.size_bytes = stored.size
    row.sha256 = stored.sha256
    await session.flush()
    return row


@dataclass(frozen=True, slots=True)
class _Stat:
    bytes: int
    sha256: str


class _Preloaded:
    """Читатель частей для проверки: нужные части прочитаны заранее, у остальных - размер и хеш."""

    def __init__(
        self,
        stats: dict[str, _Stat],
        heads: dict[str, bytes],
        blobs: dict[str, bytes],
    ) -> None:
        self._stats = stats
        self._heads = heads
        self._blobs = blobs

    def stat(self, path: str) -> qmp.PartStat | None:
        return self._stats.get(path)

    def head(self, path: str, size: int) -> bytes:
        return self._heads[path][:size]

    def read(self, path: str) -> bytes:
        return self._blobs[path]

    def lines(self, path: str) -> Iterator[str]:
        return iter(self._blobs[path].decode("utf-8", errors="replace").splitlines())


async def _preload(
    storage: ObjectStorage, parts: list[ModelPart], manifest: qmp.Manifest
) -> _Preloaded:
    declared = {part.path: part for part in manifest.parts}
    stats = {part.path: _Stat(part.size_bytes, part.sha256) for part in parts}
    heads: dict[str, bytes] = {}
    blobs: dict[str, bytes] = {}
    total = 0
    for part in parts:
        kind = declared[part.path].kind if part.path in declared else part.kind
        if kind == "geometry":
            heads[part.path] = await _read_head(storage, part.storage_key)
        elif kind in ("storeys", "grids", "elements"):
            total += part.size_bytes
            if total > MAX_PRELOAD_BYTES:
                raise _invalid("PRELOAD", part.path, "Пакет слишком велик для проверки целиком")
            blobs[part.path] = await _read_all(storage, part.storage_key, limit=part.size_bytes)
    return _Preloaded(stats, heads, blobs)


def _issues(items: list[qmp.Issue]) -> list[dict[str, str]]:
    return [
        {"code": item.code, "where": item.where, "message": item.message}
        for item in items[:MAX_WARNINGS]
    ]


async def commit_version(
    session: AsyncSession, storage: ObjectStorage, version: BuildingModelVersion
) -> BuildingModelVersion:
    """Проверяет пакет целиком и делает версию кандидатом; ошибка оставляет её на загрузке."""
    if version.status is not ModelVersionStatus.UPLOADING:
        raise DomainError(ErrorCode.MODEL_VERSION_STATE, "Версия уже зафиксирована")
    manifest_bytes, manifest = await _manifest_of(storage, version)
    parts = await parts_of(session, version.id)
    reader = await _preload(storage, parts, manifest)
    report, checked = qmp.validate_package(manifest_bytes, reader)
    if not report.ok or checked is None:
        raise _report_error(report)
    storey_part = next(part.path for part in checked.parts if part.kind == "storeys")
    storeys = qmp.check_storeys(reader.read(storey_part), qmp.Report())
    per_storey = {
        part.storey_key: sum(1 for line in reader.lines(part.path) if line.strip())
        for part in checked.parts
        if part.kind == "elements"
    }
    for position, storey in enumerate(storeys):
        session.add(
            ModelStorey(
                version_id=version.id,
                storey_key=storey.storey_key,
                name=storey.name,
                elevation_mm=storey.elevation_mm,
                height_mm=storey.height_mm,
                bbox_mm=storey.bbox_mm,
                element_count=per_storey.get(storey.storey_key, 0),
                building_key=storey.building_key,
                building_name=storey.building_name,
                position=position,
            )
        )
    version.warnings = _issues(report.warnings)
    version.counts = checked.counts.model_dump()
    version.status = ModelVersionStatus.CANDIDATE
    version.committed_at = datetime.now(UTC)
    await session.flush()
    return version


async def approve_version(
    session: AsyncSession, version: BuildingModelVersion, *, user_id: uuid.UUID, comment: str | None
) -> BuildingModelVersion:
    """Кандидат становится утверждённой версией; прежняя утверждённая - заменённой."""
    if version.status is not ModelVersionStatus.CANDIDATE:
        raise DomainError(ErrorCode.MODEL_VERSION_STATE, "Утвердить можно только кандидата")
    await session.execute(
        update(BuildingModelVersion)
        .where(
            BuildingModelVersion.project_id == version.project_id,
            BuildingModelVersion.status == ModelVersionStatus.APPROVED,
        )
        .values(status=ModelVersionStatus.SUPERSEDED)
    )
    version.status = ModelVersionStatus.APPROVED
    version.approved_by = user_id
    version.approved_at = datetime.now(UTC)
    if comment:
        version.comment = comment[:MAX_COMMENT]
    await session.flush()
    return version


async def delete_uploading(
    session: AsyncSession, storage: ObjectStorage, version: BuildingModelVersion
) -> None:
    """Отменяет выгрузку, не доведённую до фиксации: части и версия удаляются."""
    if version.status is not ModelVersionStatus.UPLOADING:
        raise DomainError(
            ErrorCode.MODEL_VERSION_STATE, "Удалить можно только незавершённую выгрузку"
        )
    for part in await parts_of(session, version.id):
        await storage.delete(part.storage_key)
    await storage.delete(model_part_key(version.project_id, version.id, MANIFEST_PATH))
    await session.delete(version)
    await session.flush()


async def find_part(
    session: AsyncSession, version: BuildingModelVersion, path: str
) -> ModelPart | None:
    if version.status is ModelVersionStatus.UPLOADING:
        return None
    return (
        await session.execute(
            select(ModelPart).where(ModelPart.version_id == version.id, ModelPart.path == path)
        )
    ).scalar_one_or_none()


async def elements_page(
    session: AsyncSession,
    storage: ObjectStorage,
    version: BuildingModelVersion,
    storey_key: str,
    *,
    category: str | None,
    discipline: str | None,
    query: str | None,
    offset: int,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Элементы этажа с отбором по категории, дисциплине и подстроке имени или типа."""
    part = (
        await session.execute(
            select(ModelPart).where(
                ModelPart.version_id == version.id,
                ModelPart.kind == "elements",
                ModelPart.storey_key == storey_key,
            )
        )
    ).scalar_one_or_none()
    if part is None or version.status is ModelVersionStatus.UPLOADING:
        return 0, []
    data = await _read_all(storage, part.storage_key, limit=qmp.MAX_PART_BYTES)
    needle = query.casefold() if query else None
    matched: list[dict[str, Any]] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if category and row.get("category") != category:
            continue
        if discipline and row.get("discipline") != discipline:
            continue
        if needle and needle not in f"{row.get('name') or ''} {row.get('type') or ''}".casefold():
            continue
        matched.append(row)
    return len(matched), matched[offset : offset + limit]
