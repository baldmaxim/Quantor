"""Провайдер канонической геометрии страницы PDF.

Узкий интерфейс между извлечением и конкретной библиотекой: «дай страницы с отображаемым
размером, поворотом и рамками». Всё остальное про геометрию строится поверх и о библиотеке
не знает (ADR-0016).

Реализация — pypdf, лицензия BSD-3. Серверный рендеринг и текстовый слой на Stage 2A не
нужны: просмотрщик остаётся на pdf.js, а здесь читаются четыре числа на страницу. Если
позже понадобится растр или извлечение вектора, меняется реализация, а не то, что на неё
опирается — на это и заведены `parser_name` с `parser_version` в каждой строке геометрии.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Protocol

from app.errors import DomainError, ErrorCode

# Точность хранения и отпечатка: 0,0001 pt — 35 нанометров чертежа. Значение выбрано
# в ADR-0016 и повторяется здесь, потому что квантование обязано совпасть со схемой.
QUANTUM = Decimal("0.0001")

# Предел числа страниц. Не про производительность: документ на миллион страниц — это
# отказ, а не долгая работа.
MAX_PAGES = 5000


@dataclass(frozen=True, slots=True)
class RawPageGeometry:
    """Геометрия одной страницы в том виде, в каком её отдал парсер."""

    page_index: int
    # Отображаемый размер: поворот уже учтён, стороны при 90/270 переставлены.
    display_width_pt: Decimal
    display_height_pt: Decimal
    rotation: int
    # Рамки в исходном пространстве PDF: начало внизу слева, поворот не применён.
    # Диагностика и происхождение, а не короткий путь к измерению.
    media_box: list[Decimal]
    crop_box: list[Decimal]


class PageGeometryProvider(Protocol):
    """Реализация чтения геометрии. Меняется целиком, а не по частям."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def read(self, path: Path) -> list[RawPageGeometry]:
        """Читает все страницы файла. Бросает DomainError с доменным кодом."""
        ...


def _quantize(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(QUANTUM, rounding=ROUND_HALF_UP)


def _normalize_rotation(value: int | None) -> int:
    """Приводит поворот к одному из четырёх допустимых.

    В документах встречаются отрицательные и превышающие 360 значения: спецификация
    требует кратности 90, но не диапазона.
    """
    rotation = int(value or 0)
    if rotation % 90 != 0:
        raise DomainError(
            ErrorCode.PDF_PAGE_GEOMETRY_INVALID,
            f"Поворот страницы не кратен 90 градусам: {rotation}",
        )
    return rotation % 360


class PypdfGeometryProvider:
    """Чтение геометрии через pypdf."""

    @property
    def name(self) -> str:
        return "pypdf"

    @property
    def version(self) -> str:
        from pypdf import __version__

        return str(__version__)

    def read(self, path: Path) -> list[RawPageGeometry]:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(str(path))
        except PdfReadError as error:
            raise DomainError(ErrorCode.PDF_UNREADABLE, "Файл не читается как PDF") from error
        # Библиотека бросает на битом входе всё что угодно, вплоть до ValueError
        # из глубины разбора. Наружу это должно выйти доменным кодом, а не трассировкой.
        except Exception as error:
            raise DomainError(ErrorCode.PDF_UNREADABLE, "Файл не читается как PDF") from error

        # Защищённый паролем PDF читается только после расшифровки, а пароля у портала нет
        # и быть не должно. Это отказ по содержимому, а не поломка.
        if reader.is_encrypted:
            raise DomainError(ErrorCode.PDF_ENCRYPTED, "PDF защищён паролем")

        try:
            page_count = len(reader.pages)
        except Exception as error:
            raise DomainError(ErrorCode.PDF_UNREADABLE, "Не удалось прочитать страницы") from error

        if page_count == 0:
            raise DomainError(ErrorCode.PDF_UNREADABLE, "В PDF нет страниц")
        if page_count > MAX_PAGES:
            raise DomainError(
                ErrorCode.PDF_PAGE_GEOMETRY_INVALID,
                f"Слишком много страниц: {page_count}, предел {MAX_PAGES}",
            )

        return [self._page(reader, index) for index in range(page_count)]

    def _page(self, reader: object, index: int) -> RawPageGeometry:
        page = reader.pages[index]  # type: ignore[attr-defined]

        try:
            media = [_quantize(float(value)) for value in page.mediabox]
            crop = [_quantize(float(value)) for value in page.cropbox]
        except Exception as error:
            raise DomainError(
                ErrorCode.PDF_PAGE_GEOMETRY_INVALID,
                f"Страница {index + 1}: рамки не читаются",
            ) from error

        rotation = _normalize_rotation(page.rotation)
        width, height = _display_size(media, crop, rotation, index)

        return RawPageGeometry(
            page_index=index,
            display_width_pt=width,
            display_height_pt=height,
            rotation=rotation,
            media_box=media,
            crop_box=crop,
        )


def _display_size(
    media: list[Decimal], crop: list[Decimal], rotation: int, index: int
) -> tuple[Decimal, Decimal]:
    """Отображаемый размер страницы: то же, что показывает `pdf.js`.

    Порядок операций повторяет `getViewport({ scale: 1 })`:

    1. видимая область — пересечение CropBox с MediaBox. CropBox по спецификации может
       выходить за MediaBox, и тогда отображается только общая часть;
    2. при повороте 90 или 270 стороны меняются местами.

    Совпадение с отрисовщиком не предполагается, а проверяется тестом: расхождение здесь
    означает, что разметка ляжет мимо чертежа.
    """
    left = max(min(media[0], media[2]), min(crop[0], crop[2]))
    bottom = max(min(media[1], media[3]), min(crop[1], crop[3]))
    right = min(max(media[0], media[2]), max(crop[0], crop[2]))
    top = min(max(media[1], media[3]), max(crop[1], crop[3]))

    width = _quantize(right - left)
    height = _quantize(top - bottom)

    if width <= 0 or height <= 0:
        raise DomainError(
            ErrorCode.PDF_PAGE_GEOMETRY_INVALID,
            f"Страница {index + 1}: пустая видимая область {width}×{height} pt",
        )

    if rotation in (90, 270):
        width, height = height, width

    return width, height
