"""Схема пакета `recognized-package/legacy-v1` и её проверка.

Формат определяется именами файлов: манифеста в нём нет (ADR-0007). Поэтому роли
определяются по суффиксам имён, а всё остальное проверяется явно и с понятными кодами
ошибок — импорт не должен падать неопределённой пятисоткой на кривом архиве.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.domain import COORDINATE_SPACE_NORMALIZED_TOP_LEFT, RegionShape
from app.errors import DomainError, ErrorCode
from app.services.legacy.archive import ArchiveMember

SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1})
SUPPORTED_COORDINATE_SPACES: Final[frozenset[str]] = frozenset(
    {COORDINATE_SPACE_NORMALIZED_TOP_LEFT}
)

BLOCKS_SUFFIX: Final = "_blocks.json"
RESULTS_MD_SUFFIX: Final = "_results.md"
RESULTS_HTML_SUFFIX: Final = "_results.html"


class PageRecord(BaseModel):
    """Страница исходного документа."""

    model_config = ConfigDict(extra="ignore")

    page_index: int = Field(ge=0)
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)
    rotation: int = 0

    @field_validator("rotation")
    @classmethod
    def _known_rotation(cls, value: int) -> int:
        if value not in (0, 90, 180, 270):
            raise ValueError(f"недопустимый поворот страницы: {value}")
        return value


class BlockRecord(BaseModel):
    """Распознанная область.

    Координаты нормализованы от левого верхнего угла: [x0, y0, x1, y1] в диапазоне [0, 1].
    """

    model_config = ConfigDict(extra="allow")

    block_id: str = Field(min_length=1, max_length=128)
    ordinal: int | None = None
    page_index: int = Field(ge=0)
    page_label: str | int | None = None
    block_type: str = Field(min_length=1, max_length=64)
    shape_type: RegionShape
    status: str | None = None
    export_status: str | None = None
    coords_norm: list[float]
    polygon_points: list[list[float]] | None = None
    crop_url: str | None = None

    @field_validator("coords_norm")
    @classmethod
    def _valid_rectangle(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("coords_norm должен содержать ровно четыре числа")
        if any(not 0.0 <= coordinate <= 1.0 for coordinate in value):
            raise ValueError("координаты должны лежать в диапазоне [0, 1]")
        x0, y0, x1, y1 = value
        if x1 < x0 or y1 < y0:
            raise ValueError("правый нижний угол не может быть левее или выше левого верхнего")
        return value

    @field_validator("polygon_points")
    @classmethod
    def _valid_polygon(cls, value: list[list[float]] | None) -> list[list[float]] | None:
        if value is None:
            return None
        if len(value) < 3:
            raise ValueError("полигон должен содержать хотя бы три точки")
        for point in value:
            if len(point) != 2:
                raise ValueError("точка полигона задаётся двумя числами")
            if any(not 0.0 <= coordinate <= 1.0 for coordinate in point):
                raise ValueError("координаты полигона должны лежать в диапазоне [0, 1]")
        return value

    @property
    def legacy_metadata(self) -> dict[str, Any]:
        """Всё, что пришло из пакета и не разложено по колонкам.

        crop_url сохраняется как метаданные и никогда не загружается сервером: пакет должен
        оставаться самодостаточным, а обращение к внешнему адресу — это SSRF (ADR-0007).
        """
        extra = dict(self.model_extra or {})
        if self.crop_url:
            extra["crop_url"] = self.crop_url
        if self.export_status:
            extra["export_status"] = self.export_status
        if self.page_label is not None:
            extra["page_label"] = self.page_label
        return extra


class BlocksDocument(BaseModel):
    """Содержимое `*_blocks.json`."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int
    coordinate_space: str
    pages: list[PageRecord]
    blocks: list[BlockRecord]
    document_id: str | None = None
    document_name: str | None = None
    generated_at: str | None = None


@dataclass(frozen=True, slots=True)
class PackageLayout:
    """Роли файлов внутри архива."""

    pdf: ArchiveMember
    blocks: ArchiveMember
    results_md: ArchiveMember | None
    results_html: ArchiveMember | None


def locate(members: list[ArchiveMember]) -> PackageLayout:
    """Определяет роли файлов по именам.

    Хрупкое место формата: манифеста нет, и роль угадывается по суффиксу. Именно поэтому
    в ADR-0007 записан переход на пакет с манифестом.
    """
    pdfs = [member for member in members if member.extension == "pdf"]
    if not pdfs:
        raise DomainError(ErrorCode.LEGACY_PDF_MISSING, "В пакете нет PDF документа")
    if len(pdfs) > 1:
        raise DomainError(
            ErrorCode.LEGACY_PDF_MISSING,
            "В пакете больше одного PDF — какой из них исходный, определить нельзя",
        )

    blocks = _single_with_suffix(members, BLOCKS_SUFFIX)
    if blocks is None:
        raise DomainError(ErrorCode.LEGACY_BLOCKS_INVALID, "В пакете нет файла *_blocks.json")

    return PackageLayout(
        pdf=pdfs[0],
        blocks=blocks,
        results_md=_single_with_suffix(members, RESULTS_MD_SUFFIX),
        results_html=_single_with_suffix(members, RESULTS_HTML_SUFFIX),
    )


def _single_with_suffix(members: list[ArchiveMember], suffix: str) -> ArchiveMember | None:
    matches = [member for member in members if member.name.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def parse_blocks(raw: bytes) -> BlocksDocument:
    """Разбирает и проверяет `*_blocks.json`."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise DomainError(
            ErrorCode.LEGACY_BLOCKS_INVALID, "Файл *_blocks.json не в кодировке UTF-8"
        ) from error
    except json.JSONDecodeError as error:
        raise DomainError(
            ErrorCode.LEGACY_BLOCKS_INVALID, f"Некорректный JSON: {error.msg}"
        ) from error

    if not isinstance(payload, dict):
        raise DomainError(
            ErrorCode.LEGACY_BLOCKS_INVALID, "Ожидался объект JSON с полями pages и blocks"
        )

    version = payload.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise DomainError(
            ErrorCode.LEGACY_SCHEMA_UNSUPPORTED,
            f"Версия схемы пакета {version!r} не поддерживается",
        )

    space = payload.get("coordinate_space")
    if space not in SUPPORTED_COORDINATE_SPACES:
        raise DomainError(
            ErrorCode.LEGACY_SCHEMA_UNSUPPORTED,
            f"Пространство координат {space!r} не поддерживается",
        )

    try:
        document = BlocksDocument.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise DomainError(ErrorCode.LEGACY_BLOCKS_INVALID, f"{location}: {first['msg']}") from error

    _validate_consistency(document)
    return document


def _validate_consistency(document: BlocksDocument) -> None:
    """Проверки, которые нельзя выразить схемой отдельной записи."""
    if not document.pages:
        raise DomainError(ErrorCode.LEGACY_BLOCKS_INVALID, "В пакете нет ни одной страницы")

    indexes = [page.page_index for page in document.pages]
    if len(set(indexes)) != len(indexes):
        raise DomainError(ErrorCode.LEGACY_BLOCKS_INVALID, "Страницы с одинаковым page_index")

    known_pages = set(indexes)
    seen_blocks: set[str] = set()
    for block in document.blocks:
        if block.block_id in seen_blocks:
            raise DomainError(
                ErrorCode.LEGACY_BLOCKS_INVALID,
                f"Повторяющийся block_id: {block.block_id}",
            )
        seen_blocks.add(block.block_id)

        if block.page_index not in known_pages:
            raise DomainError(
                ErrorCode.LEGACY_BLOCKS_INVALID,
                f"Область {block.block_id} ссылается на несуществующую страницу {block.page_index}",
            )

        if block.shape_type is RegionShape.POLYGON and not block.polygon_points:
            raise DomainError(
                ErrorCode.LEGACY_BLOCKS_INVALID,
                f"Область {block.block_id} объявлена полигоном, но точек нет",
            )
