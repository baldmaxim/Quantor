"""Приём пакета расчёта `quantor.tender_calc.v1` от TENDER (ADR-0051).

Пакет приходит по персональному токену и считается недоверенным. Проверки (раздел «Проверки
портала» формата) выполняются все сразу и собираются в список нарушений с путём файла:

1. ZIP безопасен: пути внутри корня, без ссылок, распакованный объём и сжатие в пределах
   (защита `services/legacy/archive.py`), только JSON по раскладке пакета;
2. схемы всех файлов (`contracts/tender_exchange.py`, `extra="forbid"`), sha256 из `files`;
3. проект и выпуск базы (не отозван), виды пакета есть в выпуске;
4. запрет цен: ключи и значения про стоимость во всех файлах;
5. привязка к осям `fit`: больше 500 мм - отказ, больше 100 мм - предупреждение.

Предупреждения (не отказ) пишутся в версию: база устарела, `fit` больше 100 мм, допущение в
объёмах без вопроса. Версия неизменяема; тот же пакет (sha256) - та же версия, 200.
Объёмы - внешний результат с происхождением (навык, версия, автор): не `Measurement`, не
`ExpectedQuantity`, не ВОР Quantor.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import IO, Any, Final

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.contracts.tender_exchange import (
    FIT_REFUSAL_MM,
    FIT_WARNING_MM,
    MAX_CALC_COMPRESSION_RATIO,
    MAX_CALC_FILE_BYTES,
    MAX_CALC_PACKAGE_BYTES,
    MAX_CALC_PACKAGE_FILES,
    MAX_CALC_UNPACKED_BYTES,
    CalcManifest,
    CalcQuantitiesFile,
    CalcQuestionsFile,
    CalcViewFile,
    TenderViolationRead,
    TenderWarningRead,
    parse_view_key,
)
from app.core.logging import get_logger
from app.errors import MESSAGES, STATUS_CODES, DomainError, ErrorCode, http_error
from app.models import Project, TenderBaseRelease, TenderCalc, TenderCalcVersion
from app.services import tender_base
from app.services.legacy import archive as archive_guard
from app.storage.base import ObjectStorage, StorageUnavailableError

log = get_logger(__name__)

MANIFEST_NAME: Final = "manifest.json"
QUANTITIES_NAME: Final = "quantities.json"
QUESTIONS_NAME: Final = "questions.json"
_VIEW_NAME: Final = re.compile(r"^views/[^/]+\.json$")
MAX_VIOLATIONS: Final = 100
MAX_ERRORS_PER_FILE: Final = 10
OUT_OF_BBOX_MARGIN_MM: Final = 1000
RECEIVE_CHUNK: Final = 1024 * 1024
_SPOOL_BYTES: Final = 8 * 1024 * 1024

LIMITS: Final = archive_guard.ArchiveLimits(
    max_files=MAX_CALC_PACKAGE_FILES,
    max_total_uncompressed_bytes=MAX_CALC_UNPACKED_BYTES,
    max_file_bytes=MAX_CALC_FILE_BYTES,
    max_compression_ratio=MAX_CALC_COMPRESSION_RATIO,
)

# --------------------------------------------------------------------------- запрет цен

_PRICE_WORDS: Final = frozenset(
    {
        "price",
        "prices",
        "cost",
        "costs",
        "amount",
        "amounts",
        "currency",
        "vat",
        "цена",
        "цены",
        "цену",
        "ценой",
        "цене",
        "ценам",
        "ценах",
        "цен",
        "стоимость",
        "стоимости",
        "стоимостью",
        "руб",
        "рубль",
        "рубля",
        "рублю",
        "рублей",
        "рублях",
        "рублям",
        "ндс",
    }
)
_PRICE_PREFIXES: Final = ("стоим",)
_PRICE_SIGNS: Final = ("₽",)
_WORD: Final = re.compile(r"[^\W_]+")


def _is_price_text(text: str) -> bool:
    """Строка про стоимость: слово из перечня целиком («руб», но не «труба»), знак рубля."""
    if any(sign in text for sign in _PRICE_SIGNS):
        return True
    for word in _WORD.findall(text.lower()):
        if word in _PRICE_WORDS or word.startswith(_PRICE_PREFIXES):
            return True
    return False


def find_prices(value: Any) -> list[str]:
    """Пути к ключам и строкам про стоимость во всём JSON (обход без рекурсии)."""
    found: list[str] = []
    stack: list[tuple[str, Any]] = [("", value)]
    while stack and len(found) < MAX_ERRORS_PER_FILE:
        path, node = stack.pop()
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                if _is_price_text(str(key)):
                    found.append(f"{child_path} (ключ)")
                stack.append((child_path, child))
        elif isinstance(node, list):
            stack.extend((f"{path}[{index}]", child) for index, child in enumerate(node))
        elif isinstance(node, str) and _is_price_text(node):
            found.append(f"{path or '$'} (значение)")
    return sorted(found)


# --------------------------------------------------------------------------- нарушения


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    code: ErrorCode
    message: str

    def read(self) -> TenderViolationRead:
        return TenderViolationRead(path=self.path, code=self.code.value, message=self.message)


def violations_error(violations: list[Violation]) -> HTTPException:
    """422 со списком нарушений. Код ответа - общий код нарушений, а при разных - пакетный."""
    codes = {item.code for item in violations}
    code = next(iter(codes)) if len(codes) == 1 else ErrorCode.TENDER_PACKAGE_INVALID
    return HTTPException(
        status_code=STATUS_CODES[code],
        detail={
            "code": code.value,
            "message": MESSAGES[code],
            "violations": [item.read().model_dump() for item in violations[:MAX_VIOLATIONS]],
        },
    )


def _schema_violations(name: str, error: ValidationError) -> list[Violation]:
    result: list[Violation] = []
    for item in error.errors()[:MAX_ERRORS_PER_FILE]:
        where = ".".join(str(part) for part in item["loc"])
        result.append(
            Violation(
                f"{name}: {where}" if where else name,
                ErrorCode.TENDER_PACKAGE_INVALID,
                str(item["msg"]),
            )
        )
    return result


# --------------------------------------------------------------------------- разбор пакета


@dataclass(slots=True)
class ParsedPackage:
    """Результат разбора ZIP: проверенные модели и нарушения. Содержимое видов не удерживается."""

    manifest: CalcManifest | None = None
    quantities: CalcQuantitiesFile | None = None
    questions: CalcQuestionsFile | None = None
    # Имя файла в пакете -> проверенный вид.
    views: dict[str, CalcViewFile] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)


def _load_json(
    archive: zipfile.ZipFile,
    member: archive_guard.ArchiveMember,
    violations: list[Violation],
) -> tuple[Any, str] | None:
    """Файл пакета: разобранный JSON и sha256 содержимого; ошибка - нарушение и `None`."""
    try:
        data = archive_guard.read_member(archive, member, max_bytes=member.size)
    except DomainError as error:
        violations.append(Violation(member.name, ErrorCode.TENDER_PACKAGE_INVALID, error.detail))
        return None
    sha = hashlib.sha256(data).hexdigest()
    try:
        return json.loads(data), sha
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        violations.append(
            Violation(member.name, ErrorCode.TENDER_PACKAGE_INVALID, "Файл не является JSON UTF-8")
        )
        return None


def _validate[ModelT: BaseModel](
    name: str, raw: Any, model: type[ModelT], violations: list[Violation]
) -> ModelT | None:
    """Схема файла; перед ней - запрет цен: файл с ценой не разбирается дальше."""
    prices = find_prices(raw)
    if prices:
        violations.extend(
            Violation(
                f"{name}: {path}",
                ErrorCode.TENDER_PRICE_FORBIDDEN,
                "Стоимость в пакете не принимается: цены ведутся в TENDER",
            )
            for path in prices
        )
        return None
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        violations.extend(_schema_violations(name, error))
        return None


def parse_package(stream: IO[bytes]) -> ParsedPackage:
    """Проверки ZIP и схем всех файлов; ничего не пишет, всё сразу."""
    parsed = ParsedPackage()
    violations = parsed.violations
    try:
        archive = zipfile.ZipFile(stream)
    except zipfile.BadZipFile:
        violations.append(
            Violation("пакет", ErrorCode.TENDER_PACKAGE_INVALID, "Файл не является ZIP-архивом")
        )
        return parsed
    with archive:
        try:
            members = archive_guard.inspect(archive, LIMITS)
        except DomainError as error:
            violations.append(Violation("пакет", ErrorCode.TENDER_PACKAGE_INVALID, error.detail))
            return parsed
        names = [member.name for member in members]
        for name in {name for name in names if names.count(name) > 1}:
            violations.append(
                Violation(
                    name, ErrorCode.TENDER_PACKAGE_INVALID, "Файл встречается в архиве дважды"
                )
            )
        digests: dict[str, str] = {}
        for member in members:
            name = member.name
            if name not in (
                MANIFEST_NAME,
                QUANTITIES_NAME,
                QUESTIONS_NAME,
            ) and not _VIEW_NAME.match(name):
                violations.append(
                    Violation(
                        name,
                        ErrorCode.TENDER_PACKAGE_INVALID,
                        "Файл не предусмотрен пакетом: допустимы manifest.json, quantities.json, "
                        "questions.json и views/*.json",
                    )
                )
                continue
            loaded = _load_json(archive, member, violations)
            if loaded is None:
                continue
            raw, sha = loaded
            digests[name] = sha
            if name == MANIFEST_NAME:
                parsed.manifest = _validate(name, raw, CalcManifest, violations)
            elif name == QUANTITIES_NAME:
                parsed.quantities = _validate(name, raw, CalcQuantitiesFile, violations)
            elif name == QUESTIONS_NAME:
                parsed.questions = _validate(name, raw, CalcQuestionsFile, violations)
            else:
                view = _validate(name, raw, CalcViewFile, violations)
                if view is not None:
                    parsed.views[name] = view
        for required in (MANIFEST_NAME, QUANTITIES_NAME):
            if required not in names:
                violations.append(
                    Violation(required, ErrorCode.TENDER_PACKAGE_INVALID, "Файла нет в пакете")
                )
        if parsed.manifest is not None:
            violations.extend(_check_files(parsed.manifest, digests, names))
    return parsed


def _check_files(
    manifest: CalcManifest, digests: dict[str, str], names: list[str]
) -> list[Violation]:
    """`files` манифеста совпадают с содержимым: каждый файл указан и его sha256 верен."""
    result: list[Violation] = []
    for name, expected in manifest.files.items():
        if name not in names:
            result.append(
                Violation(
                    name, ErrorCode.TENDER_PACKAGE_INVALID, "Файл из files не найден в пакете"
                )
            )
        elif name in digests and digests[name] != expected:
            result.append(
                Violation(
                    name, ErrorCode.TENDER_PACKAGE_INVALID, "sha256 файла не совпадает с files"
                )
            )
    for name in names:
        if name != MANIFEST_NAME and name not in manifest.files:
            result.append(
                Violation(
                    name, ErrorCode.TENDER_PACKAGE_INVALID, "Файл не указан в files манифеста"
                )
            )
    return result


# --------------------------------------------------------------------------- приём загрузки


@dataclass(frozen=True, slots=True)
class ReceivedPackage:
    stream: IO[bytes]
    sha256: str
    size: int


def spool() -> tempfile.SpooledTemporaryFile[bytes]:
    """Временный файл приёма: в памяти до порога, дальше на диске. Закрывает вызывающий."""
    return tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES)


async def receive(upload: UploadFile, target: IO[bytes]) -> ReceivedPackage:
    """Принимает загрузку в `target`: размер не больше предела, sha256 считается на лету."""
    digest = hashlib.sha256()
    size = 0
    while chunk := await upload.read(RECEIVE_CHUNK):
        size += len(chunk)
        if size > MAX_CALC_PACKAGE_BYTES:
            raise DomainError(ErrorCode.UPLOAD_TOO_LARGE, "Пакет расчёта больше 50 МБ")
        digest.update(chunk)
        await asyncio.to_thread(target.write, chunk)
    if size == 0:
        raise DomainError(ErrorCode.EMPTY_FILE)
    target.seek(0)
    return ReceivedPackage(target, digest.hexdigest(), size)


async def _file_chunks(handle: IO[bytes]) -> AsyncIterator[bytes]:
    while chunk := await asyncio.to_thread(handle.read, RECEIVE_CHUNK):
        yield chunk


# --------------------------------------------------------------------------- проверки с базой


def _release_views(release: TenderBaseRelease) -> dict[str, dict[str, Any]]:
    return {str(view["key"]).lower(): view for view in release.views}


async def _cross_checks(
    session: AsyncSession,
    *,
    project: Project,
    parsed: ParsedPackage,
    manifest: CalcManifest,
) -> tuple[TenderBaseRelease | None, list[Violation], list[TenderWarningRead]]:
    """Проект, выпуск базы, виды пакета, привязка; предупреждения приёма."""
    violations: list[Violation] = []
    warnings: list[TenderWarningRead] = []
    if manifest.project_id != project.id:
        violations.append(
            Violation(
                f"{MANIFEST_NAME}: project_id",
                ErrorCode.TENDER_PROJECT_MISMATCH,
                "Пакет составлен для другого проекта",
            )
        )
    release = await tender_base.get_release(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        release_id=manifest.base.release_id,
    )
    if release is None or release.revoked_at is not None:
        violations.append(
            Violation(
                f"{MANIFEST_NAME}: base.release_id",
                ErrorCode.TENDER_BASE_UNKNOWN,
                "Выпуск базы не найден в проекте"
                if release is None
                else "Выпуск базы отозван: возьмите актуальный выпуск",
            )
        )
        release = None
    elif manifest.base.manifest_sha256 != release.manifest_sha256:
        violations.append(
            Violation(
                f"{MANIFEST_NAME}: base.manifest_sha256",
                ErrorCode.TENDER_BASE_UNKNOWN,
                "manifest_sha256 не совпадает с манифестом выпуска базы",
            )
        )
    for index, fit in enumerate(manifest.fit):
        if fit.max_mm > FIT_REFUSAL_MM:
            violations.append(
                Violation(
                    f"{MANIFEST_NAME}: fit[{index}].max_mm",
                    ErrorCode.TENDER_FIT_TOO_LARGE,
                    f"Привязка вида {fit.view_key} хуже {FIT_REFUSAL_MM:.0f} мм: {fit.max_mm:g} мм",
                )
            )
        elif fit.max_mm > FIT_WARNING_MM:
            warnings.append(
                TenderWarningRead(
                    code="fit_over_100",
                    message=f"Привязка вида хуже {FIT_WARNING_MM:.0f} мм: {fit.max_mm:g} мм",
                    view_key=fit.view_key,
                )
            )
    seen: set[str] = set()
    for name, view in parsed.views.items():
        key = view.view_key.lower()
        if key in seen:
            violations.append(
                Violation(
                    name, ErrorCode.TENDER_PACKAGE_INVALID, f"Вид {view.view_key} повторяется"
                )
            )
        seen.add(key)
    if release is None:
        return None, violations, warnings

    in_release = _release_views(release)
    referenced: list[tuple[str, str]] = [
        (name, view.view_key) for name, view in parsed.views.items()
    ]
    referenced += [
        (f"{MANIFEST_NAME}: fit[{index}].view_key", fit.view_key)
        for index, fit in enumerate(manifest.fit)
    ]
    if parsed.quantities is not None:
        for row_index, row in enumerate(parsed.quantities.rows):
            referenced += [
                (f"{QUANTITIES_NAME}: rows[{row_index}].view_keys", key) for key in row.view_keys
            ]
    reported: set[tuple[str, str]] = set()
    for path, key in referenced:
        if key.lower() not in in_release and (path, key) not in reported:
            reported.add((path, key))
            violations.append(
                Violation(
                    path,
                    ErrorCode.TENDER_VIEW_UNKNOWN,
                    f"Вида {key} нет в выпуске базы №{release.number}",
                )
            )
    if violations:
        return release, violations, warnings

    current = await tender_base.current_dxf_hashes(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        view_keys=[view.view_key for view in parsed.views.values()],
    )
    for name, view in parsed.views.items():
        released = in_release[view.view_key.lower()].get("dxf_sha256")
        if current.get(view.view_key) != released:
            warnings.append(
                TenderWarningRead(
                    code="base_stale",
                    message="База устарела: вид перестроен движком после выпуска базы",
                    view_key=view.view_key,
                )
            )
        if view.dxf_sha256 != released:
            warnings.append(
                TenderWarningRead(
                    code="view_dxf_mismatch",
                    message=f"{name}: dxf_sha256 вида отличается от выпуска базы",
                    view_key=view.view_key,
                )
            )
        warning = _out_of_bbox_warning(name, view, in_release[view.view_key.lower()].get("bbox"))
        if warning is not None:
            warnings.append(warning)
    warnings.extend(_assumption_warnings(parsed))
    return release, violations, warnings


def _out_of_bbox_warning(name: str, view: CalcViewFile, bbox: Any) -> TenderWarningRead | None:
    """Объекты вида за рамкой вида базы больше чем на `OUT_OF_BBOX_MARGIN_MM`.

    Рамка есть только у выпусков, где портал её сохранил; без неё проверка молча пропускается.
    """
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(value, int | float) for value in bbox)
    ):
        return None
    x_min, y_min = bbox[0] - OUT_OF_BBOX_MARGIN_MM, bbox[1] - OUT_OF_BBOX_MARGIN_MM
    x_max, y_max = bbox[2] + OUT_OF_BBOX_MARGIN_MM, bbox[3] + OUT_OF_BBOX_MARGIN_MM

    def outside(point: list[int]) -> bool:
        return not (x_min <= point[0] <= x_max and y_min <= point[1] <= y_max)

    count = sum(1 for item in view.polylines if any(outside(point) for point in item.pts))
    count += sum(1 for item in view.elements if outside(item.pos))
    if count == 0:
        return None
    return TenderWarningRead(
        code="out_of_bbox",
        message=f"{name}: {count} объектов за рамкой вида (bbox ±1 м) — проверь привязку",
        view_key=view.view_key,
    )


def _assumption_warnings(parsed: ParsedPackage) -> list[TenderWarningRead]:
    """Допущение в объёмах без вопроса: код строки не назван ни в одном вопросе (id или текст)."""
    if parsed.quantities is None:
        return []
    questions = parsed.questions.rows if parsed.questions is not None else []
    result: list[TenderWarningRead] = []
    for row in parsed.quantities.rows:
        if row.basis != "assumption":
            continue
        if not any(row.code in question.ids or row.code in question.text for question in questions):
            result.append(
                TenderWarningRead(
                    code="assumption_without_question",
                    message=f"Строка {row.code}: допущение без вопроса в questions.json",
                )
            )
    return result


# --------------------------------------------------------------------------- сохранение


def _version_package_key(project_id: uuid.UUID, version_id: uuid.UUID) -> str:
    return f"projects/{project_id}/tender/calcs/{version_id}/package.zip"


def _version_view_key(
    project_id: uuid.UUID, version_id: uuid.UUID, revision_id: uuid.UUID, page: int, view: int
) -> str:
    return f"projects/{project_id}/tender/calcs/{version_id}/views/{revision_id}_{page}_{view}.json"


async def find_existing(
    session: AsyncSession, *, project: Project, package_sha256: str
) -> tuple[TenderCalcVersion, TenderCalc] | None:
    """Тот же пакет уже загружен в проект: существующая версия."""
    row = (
        await session.execute(
            select(TenderCalcVersion, TenderCalc)
            .join(TenderCalc, TenderCalcVersion.calc_id == TenderCalc.id)
            .where(
                TenderCalc.project_id == project.id,
                TenderCalc.workspace_id == project.workspace_id,
                TenderCalcVersion.package_sha256 == package_sha256,
            )
            .order_by(TenderCalcVersion.uploaded_at)
            .limit(1)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def _get_or_create_calc(
    session: AsyncSession, *, project: Project, manifest: CalcManifest, user_id: uuid.UUID
) -> TenderCalc:
    where = (
        TenderCalc.project_id == project.id,
        TenderCalc.discipline == manifest.calc.discipline,
        TenderCalc.system == manifest.calc.system,
        TenderCalc.title == manifest.calc.title,
    )
    calc = await session.scalar(select(TenderCalc).where(*where).with_for_update())
    if calc is not None:
        return calc
    calc = TenderCalc(
        workspace_id=project.workspace_id,
        project_id=project.id,
        discipline=manifest.calc.discipline,
        system=manifest.calc.system,
        title=manifest.calc.title,
        created_by=user_id,
    )
    try:
        async with session.begin_nested():
            session.add(calc)
            await session.flush()
    except IntegrityError:
        # Параллельная загрузка той же системы создала репозиторий первой.
        existing = await session.scalar(select(TenderCalc).where(*where).with_for_update())
        if existing is None:  # pragma: no cover - конфликт без строки невозможен
            raise
        return existing
    return calc


@dataclass(frozen=True, slots=True)
class ImportResult:
    version: TenderCalcVersion
    calc: TenderCalc
    created: bool


async def import_package(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    context: AuthContext,
    project: Project,
    package: ReceivedPackage,
) -> ImportResult:
    """Проверки, затем новая версия или существующая (тот же sha256). Коммит - у вызывающего."""
    existing = await find_existing(session, project=project, package_sha256=package.sha256)
    if existing is not None:
        return ImportResult(existing[0], existing[1], created=False)

    parsed = await asyncio.to_thread(parse_package, package.stream)
    violations = list(parsed.violations)
    manifest = parsed.manifest
    release: TenderBaseRelease | None = None
    warnings: list[TenderWarningRead] = []
    if manifest is not None:
        release, more, warnings = await _cross_checks(
            session, project=project, parsed=parsed, manifest=manifest
        )
        violations.extend(more)
    if violations or manifest is None or release is None or parsed.quantities is None:
        raise violations_error(
            violations
            or [Violation("пакет", ErrorCode.TENDER_PACKAGE_INVALID, "Пакет не разобран")]
        )

    user_id = context.principal.user_id
    calc = await _get_or_create_calc(session, project=project, manifest=manifest, user_id=user_id)
    # Повторная загрузка того же пакета в гонке: версия уже создана параллельным запросом.
    again = await session.scalar(
        select(TenderCalcVersion).where(
            TenderCalcVersion.calc_id == calc.id,
            TenderCalcVersion.package_sha256 == package.sha256,
        )
    )
    if again is not None:
        return ImportResult(again, calc, created=False)

    number = (
        await session.scalar(
            select(func.coalesce(func.max(TenderCalcVersion.number), 0)).where(
                TenderCalcVersion.calc_id == calc.id
            )
        )
        or 0
    ) + 1
    version_id = uuid.uuid4()
    stored_keys: list[str] = []
    try:
        package_key = _version_package_key(project.id, version_id)
        package.stream.seek(0)
        try:
            await storage.put_stream(
                package_key,
                _file_chunks(package.stream),
                content_type="application/zip",
                original_filename=f"quantor-calc-{calc.id}-v{number}.zip",
            )
            stored_keys.append(package_key)
            views_meta: list[dict[str, Any]] = []
            for view in parsed.views.values():
                revision_id, page_index, view_no = parse_view_key(view.view_key)
                object_key = _version_view_key(
                    project.id, version_id, revision_id, page_index, view_no
                )
                payload = json.dumps(
                    view.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                await storage.put_bytes(object_key, payload, content_type="application/json")
                stored_keys.append(object_key)
                views_meta.append(
                    {
                        "view_key": view.view_key,
                        "revision_id": str(revision_id),
                        "page_index": page_index,
                        "view": view_no,
                        "floors": list(view.floors),
                        "dxf_sha256": view.dxf_sha256,
                        "object_key": object_key,
                        "polylines": len(view.polylines),
                        "elements": len(view.elements),
                    }
                )
        except StorageUnavailableError as error:
            raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error

        # Одна действующая версия на репозиторий: прежняя выводится из строя до вставки новой.
        await session.execute(
            update(TenderCalcVersion)
            .where(TenderCalcVersion.calc_id == calc.id, TenderCalcVersion.status == "active")
            .values(status="superseded")
        )
        version = TenderCalcVersion(
            id=version_id,
            calc_id=calc.id,
            number=number,
            base_release_id=release.id,
            label=manifest.version.label,
            message=manifest.version.message,
            author=manifest.version.author,
            uploaded_by=user_id,
            producer=manifest.producer.model_dump(mode="json"),
            fit=[item.model_dump(mode="json") for item in manifest.fit],
            package_key=package_key,
            package_sha256=package.sha256,
            views=views_meta,
            quantities=[row.model_dump(mode="json") for row in parsed.quantities.rows],
            questions=(
                [row.model_dump(mode="json") for row in parsed.questions.rows]
                if parsed.questions is not None
                else []
            ),
            warnings=[warning.model_dump(mode="json") for warning in warnings],
            status="active",
        )
        session.add(version)
        await session.flush()
        await session.refresh(version)
    except BaseException:
        for key in stored_keys:
            try:
                await storage.delete(key)
            except Exception:
                log.warning("tender_calc_cleanup_failed", key=key)
        raise
    return ImportResult(version, calc, created=True)
