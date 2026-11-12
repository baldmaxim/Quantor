"""Каталог вопросов к документации `consistency.doc_questions.v1` (ADR-0043, шаг 2, этап В2).

Данные, а не логика: что спросить у проекта, где это искать (разделы, типы листов, документы
Заказчика), по каким якорям, как извлечь значение и какой норматив предложить, если в проекте
ответа нет. Извлечение значений и ранжирование - `doc_search`. Модель чисел не выдаёт:
только шаблоны с версией. Норматив-допущение - не ответ проекта, а предложение с пунктом СП
и статусом; в расчёт идёт только после решения человека.

Тексты для поиска приводятся к виду «ё → е, любые тире → «-», пробелы схлопнуты», поэтому
шаблоны пишутся без «ё» и с обычным дефисом. Регистр не учитывается. Модуль не импортирует
БД, calc и CAD.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.services.consistency.dictionaries import SheetKind

DOC_QUESTIONS_VERSION: Final = "consistency.doc_questions.v1"


class DocQuestionCode(StrEnum):
    CORRIDOR_CEILING_HEIGHT = "corridor_ceiling_height"
    CLEAR_HEIGHT = "clear_height"
    CORRIDOR_FLOOR_BUILDUP = "corridor_floor_buildup"
    SLAB_THICKNESS = "slab_thickness"
    SPRINKLER_MODEL = "sprinkler_model"
    SPRINKLER_CEILING_GAP = "sprinkler_ceiling_gap"
    HOT_OVER_COLD_GAP = "hot_over_cold_gap"
    DUCT_SECTION = "duct_section"
    CABLE_TRAY_SECTION = "cable_tray_section"


class DocValueKind(StrEnum):
    LENGTH_MM = "length_mm"  # одно число в мм (с необязательным «не менее» / «не более»)
    RANGE_MM = "range_mm"  # диапазон «от - до» в мм; одиночное число допускается
    SECTION_MM = "section_mm"  # «ширина×высота» в мм или диаметр «Ø»
    TEXT = "text"
    ENUM = "enum"


class ExtractorKind(StrEnum):
    LENGTH = "length"
    RANGE = "range"
    SECTION = "section"
    FLOOR_BUILDUP = "floor_buildup"
    SPRINKLER_MODEL = "sprinkler_model"


class AssumptionStatus(StrEnum):
    """Статус норматива-допущения: как в навыке normy-prokladki-setey."""

    NORM = "norm"  # прямая норма на этот случай
    ANALOGY = "analogy"  # норма на соседний случай, распространена по аналогии
    PRACTICE = "practice"  # практика увязки, нормы нет


@dataclass(frozen=True, slots=True)
class DocSource:
    """Где искать: страницы раздела (и типов листов) либо документы Заказчика.

    Порядок источников в вопросе - приоритет: раньше в списке, выше оценка. `sheet_kinds`
    пуст - подходит любой тип; лист с неопределённым типом подходит под любой набор типов.
    """

    label: str
    section_marks: tuple[str, ...] = ()
    sheet_kinds: tuple[SheetKind, ...] = ()
    customer: bool = False


@dataclass(frozen=True, slots=True)
class DocAnchor:
    """Якорь поиска: шаблон по русскому тексту и его вес (очки оценки, до 20).

    `bare_number` - сразу после якоря допустимо число без единицы («тщ. 200», «h=2700»).
    """

    pattern: re.Pattern[str]
    weight: int
    bare_number: bool = False


@dataclass(frozen=True, slots=True)
class NormAssumption:
    """Норматив на случай «в проекте нет»: допущение со ссылкой на пункт СП, НЕ ответ проекта."""

    mm_from: int
    mm_to: int | None
    reference: str
    status: AssumptionStatus
    note: str


@dataclass(frozen=True, slots=True)
class DocQuestion:
    code: DocQuestionCode
    title: str
    receiver_param: str  # код параметра-получателя в CAD-трассах
    value_kind: DocValueKind
    extractor: ExtractorKind
    sources: tuple[DocSource, ...]
    anchors: tuple[DocAnchor, ...]
    context: tuple[re.Pattern[str], ...] = ()
    context_required: bool = False
    # Слова исключения («допускается увеличение», «настенный»): рядом с ними значение - не основной
    # ответ, оценка снижается.
    weak_markers: tuple[re.Pattern[str], ...] = ()
    min_mm: int = 0  # допустимый разброс извлечённых чисел (каждого размера), мм
    max_mm: int = 100_000
    assumption: NormAssumption | None = None


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def _anchor(pattern: str, weight: int, *, bare_number: bool = False) -> DocAnchor:
    return DocAnchor(_rx(pattern), weight, bare_number)


# --------------------------------------------------------------------------- документы Заказчика

# Имя файла (подчёркивания считаются пробелами) и первая строка первой страницы.
_CUSTOMER_FILE_RE: Final = _rx(
    r"договор|техническ\w+ задани|(?<![а-я])тз(?![а-я])|стандарт\w* проектирования|чек-?лист"
)
_CUSTOMER_HEADING_RE: Final = _rx(
    r"^(?:приложение[\s№\d.]*(?:к\s+)?)?"
    r"(?:договор(?:у|а|е)?|техническ\w+ задани\w+|стандарты проектирования)(?![а-я])"
)
_HEADING_CHARS: Final = 120


def is_customer_document(file_name: str, first_page_text: str | None = None) -> bool:
    """Договор, ТЗ, стандарты Заказчика: по имени файла или первой строке первой страницы."""
    name = file_name.replace("\\", "/").rsplit("/", 1)[-1].lower().replace("ё", "е")
    if _CUSTOMER_FILE_RE.search(name.replace("_", " ")):
        return True
    if first_page_text:
        first = next((line.strip() for line in first_page_text.splitlines() if line.strip()), "")
        head = " ".join(first.split())[:_HEADING_CHARS].lower().replace("ё", "е")
        return _CUSTOMER_HEADING_RE.search(head) is not None
    return False


# --------------------------------------------------------------------------- источники

_K = SheetKind
_AR = ("АР",)
_CUSTOMER = DocSource("Договор / ТЗ Заказчика", customer=True)
_WATER_FIRE = ("ИОС2", "ВК", "АПТ", "АУПТ")
_HVAC = ("ИОС4", "ОВ")
_ELECTRIC = ("ИОС1", "ЭОМ", "ЭМ", "ЭО", "ЭС", "ИОС5", "СС")

# Контекст «коридор / МОП»: без него высота потолка квартиры или номер пола не наш ответ.
_CORRIDOR_CTX: Final = (
    _rx(r"коридор\w*|(?<!\w)моп(?!\w)|лифтов\w+ хол\w*|общ\w+ пользован\w+|межквартирн\w+"),
)
# «ДУ» / «ДП» только заглавными: «Ду315» - диаметр трубы, не система.
_SMOKE_CTX: Final = (
    _rx(r"(?<!\w)(?-i:КДУ|ДУ|ДП)(?![а-яa-z])|дымоудален\w*|подпор\w*|противодымн\w*"),
)
_CLEAR_CTX: Final = (
    _rx(r"этаж\w*|плит\w+|перекрыт\w+|(?<!\w)пол(?:а|у|ом|е|ы|ов)?(?!\w)|потол[ок]\w+"),
)
_EXCEPTION_MARKERS: Final = (
    _rx(r"допускается|допустим\w+|в\s+особых\s+случаях|увеличен\w+|настенн\w+|карнизн\w+"),
)
_HOT_COLD_CTX: Final = (_rx(r"горяч\w+|холодн\w+|гвс|хвс|отоплен\w+"),)


# --------------------------------------------------------------------------- каталог v1

DOC_QUESTIONS: Final[tuple[DocQuestion, ...]] = (
    DocQuestion(
        code=DocQuestionCode.CORRIDOR_CEILING_HEIGHT,
        title="Высота подвесного (подшивного) потолка коридора / МОП от чистого пола",
        receiver_param="corridor_ceiling_height_mm",
        value_kind=DocValueKind.LENGTH_MM,
        extractor=ExtractorKind.LENGTH,
        sources=(
            DocSource("ПЗ АР", _AR, (_K.TEXT,)),
            DocSource("Разрезы АР", _AR, (_K.SECTION,)),
            DocSource("Ведомость отделки АР", _AR, (_K.TABLE,)),
            _CUSTOMER,
            DocSource("Прочие листы АР", _AR),
        ),
        anchors=(
            _anchor(r"пол\s*-\s*(?:подвесн\w+\s+|подшивн\w+\s+)?потол[ок]\w*", 20),
            _anchor(
                r"высот\w+\s+(?:до\s+)?(?:подвесн\w+\s+|подшивн\w+\s+|монтаж\w+\s+)?потол[ок]\w*",
                20,
            ),
            _anchor(
                r"(?:подвесн\w+|подшивн\w+)\s+потол[ок]\w*[^.;]{0,60}?"
                r"(?:от\s+(?:уровня\s+)?(?:чистого\s+)?пола|на\s+высот\w+)",
                20,
            ),
            _anchor(r"потол[ок]\w*\s+(?:на\s+высоте|не\s+ниже|не\s+менее)", 15),
            _anchor(r"(?:подвесн\w+|подшивн\w+)\s+потол[ок]\w*", 8),
        ),
        context=_CORRIDOR_CTX,
        context_required=True,
        min_mm=2000,
        max_mm=4500,
    ),
    DocQuestion(
        code=DocQuestionCode.CLEAR_HEIGHT,
        title="Высота в свету: чистый пол - низ плиты перекрытия",
        receiver_param="clear_height_mm",
        value_kind=DocValueKind.LENGTH_MM,
        extractor=ExtractorKind.LENGTH,
        sources=(
            DocSource("Разрезы АР", _AR, (_K.SECTION,)),
            DocSource("ПЗ АР", _AR, (_K.TEXT,)),
            DocSource("Таблицы АР", _AR, (_K.TABLE,)),
            DocSource("Прочие листы АР", _AR),
        ),
        anchors=(
            _anchor(
                r"(?:от\s+)?чист\w+\s+пол\w*\s+до\s+(?:низ\w*\s+)?(?:плит\w+|перекрыт\w+|потол[ок]\w+)",
                20,
            ),
            _anchor(r"высот\w+\s+(?:этаж\w*\s+|помещени\w+\s+)?в\s+свету", 20),
            _anchor(r"чист\w+\s+высот\w+", 15),
            _anchor(r"в\s+свету", 8),
        ),
        context=_CLEAR_CTX,
        context_required=True,
        min_mm=2200,
        max_mm=6000,
    ),
    DocQuestion(
        code=DocQuestionCode.CORRIDOR_FLOOR_BUILDUP,
        title="Пирог пола коридора / МОП: тип пола и толщина, мм",
        receiver_param="corridor_floor_buildup",
        value_kind=DocValueKind.TEXT,
        extractor=ExtractorKind.FLOOR_BUILDUP,
        sources=(
            DocSource("Экспликация полов АР", _AR, (_K.TABLE,)),
            DocSource("ПЗ АР", _AR, (_K.TEXT,)),
            DocSource("Прочие листы АР", _AR),
            # На 314 пол МОП описан только в ПЗ КР: источник ниже АР.
            DocSource("ПЗ КР", ("КР", "КЖ"), (_K.TEXT,)),
            _CUSTOMER,
        ),
        anchors=(
            _anchor(
                r"(?:тип\s+)?(?<!\w)п-?\s*\d+(?:\.\d+)?[а-я]?\s*\([^)]{0,80}"
                r"(?:(?<!\w)моп(?!\w)|коридор\w*|общ\w+\s+пользован\w+)",
                20,
            ),
            _anchor(
                r"(?:тип\s+)?(?<!\w)п-?\s*\d+(?:\.\d+)?[а-я]?[.\s]+пол\w*\s+(?:в\s*)?"
                r"(?:моп\w*|коридор\w*|мест\w+\s+общего\s+пользован\w+)",
                20,
            ),
            _anchor(r"толщин\w+\s+конструкци\w+\s+пол\w*", 18),
            _anchor(r"пирог\w*\s+пол\w*", 15),
            _anchor(r"пол\w*\s+(?:в\s*)?(?:(?<!\w)моп\w*|коридор\w*)", 8),
        ),
        context=_CORRIDOR_CTX,
        context_required=True,
        min_mm=3,
        max_mm=1000,
    ),
    DocQuestion(
        code=DocQuestionCode.SLAB_THICKNESS,
        title="Толщина плиты перекрытия типового этажа, мм",
        receiver_param="slab_thickness_mm",
        value_kind=DocValueKind.LENGTH_MM,
        extractor=ExtractorKind.LENGTH,
        sources=(DocSource("КР", ("КР", "КЖ")),),
        anchors=(
            _anchor(
                r"толщин\w+\s+(?:монолитн\w+\s+)?(?:ж/?б\s+|железобетонн\w+\s+)?"
                r"(?:плит\w+|перекрыт\w+)",
                20,
                bare_number=True,
            ),
            _anchor(r"(?:плит\w+|перекрыт\w+)[^.;]{0,30}?толщин\w*", 20, bare_number=True),
            _anchor(r"тщ\.?(?:\s*(?:плит\w+|перекрыт\w+))?", 18, bare_number=True),
            _anchor(r"(?:монолитн\w+\s+)?плит\w+\s+перекрыт\w+", 8),
        ),
        min_mm=100,
        max_mm=800,
    ),
    DocQuestion(
        code=DocQuestionCode.SPRINKLER_MODEL,
        title="Оросители АУП: тип и положение розетки",
        receiver_param="sprinkler_model",
        value_kind=DocValueKind.ENUM,
        extractor=ExtractorKind.SPRINKLER_MODEL,
        sources=(
            DocSource("ИОС2 / АУП: ПЗ и схемы", _WATER_FIRE, (_K.TEXT, _K.SCHEME)),
            DocSource("ИОС2 / АУП: прочее", _WATER_FIRE),
            DocSource("Пожарная безопасность", ("ПБ",)),
        ),
        anchors=(
            _anchor(r"оросител\w*[^.;]{0,60}?(?:модел\w+|тип\w*|марк\w+)", 20),
            _anchor(r"спринклерн\w+\s+оросител\w*", 15),
            _anchor(r"розетк\w+\s+(?:вниз|вверх)", 15),
        ),
    ),
    DocQuestion(
        code=DocQuestionCode.SPRINKLER_CEILING_GAP,
        title="Оросители АУП: расстояние от розетки до перекрытия, мм",
        receiver_param="sprinkler_ceiling_gap_mm",
        value_kind=DocValueKind.RANGE_MM,
        extractor=ExtractorKind.RANGE,
        sources=(
            DocSource("ИОС2 / АУП: ПЗ и схемы", _WATER_FIRE, (_K.TEXT, _K.SCHEME)),
            DocSource("ИОС2 / АУП: прочее", _WATER_FIRE),
            DocSource("Пожарная безопасность", ("ПБ",)),
        ),
        anchors=(
            _anchor(
                r"расстояни\w+[^.;]{0,80}?оросител\w*[^.;]{0,30}?до\s+(?:плоскост\w+\s+)?"
                r"(?:перекрыт\w+|покрыт\w+|потол[ок]\w+)",
                20,
            ),
            _anchor(
                r"расстояни\w+\s+от\s+розет\w+[^.;]{0,60}?до\s+(?:подвесн\w+\s+)?"
                r"(?:потол[ок]\w+|перекрыт\w+)",
                20,
            ),
            _anchor(r"оросител\w*[^.;]{0,40}до\s+плоскост\w+\s+перекрыт\w+", 15),
        ),
        weak_markers=_EXCEPTION_MARKERS,
        min_mm=20,
        max_mm=1500,
        assumption=NormAssumption(
            mm_from=80,
            mm_to=300,
            reference="СП 485.1311500.2020, п. 6.2.11",
            status=AssumptionStatus.NORM,
            note=(
                "Центр термочувствительного элемента общего оросителя, кроме скрытых, "
                "углублённых и потайных, до плоскости перекрытия: 0,08-0,30 м; в особых случаях "
                "по конструкции перекрытия до 0,40 м."
            ),
        ),
    ),
    DocQuestion(
        code=DocQuestionCode.HOT_OVER_COLD_GAP,
        title="Зазор между трубами «горячее над холодным», мм в свету",
        receiver_param="hot_over_cold_gap_mm",
        value_kind=DocValueKind.LENGTH_MM,
        extractor=ExtractorKind.LENGTH,
        sources=(
            DocSource("ПЗ ИОС2 / ИОС4", ("ИОС2", "ИОС4", "ВК", "ОВ"), (_K.TEXT,)),
            DocSource("ИОС2 / ИОС4: прочее", ("ИОС2", "ИОС4", "ВК", "ОВ")),
            _CUSTOMER,
        ),
        anchors=(
            _anchor(r"горяч\w+[^.;]{0,60}?(?:над|выше|ниже)\s+[^.;]{0,30}?холодн\w+", 20),
            _anchor(
                r"холодн\w+[^.;]{0,60}?(?:ниже|под|над)\s+[^.;]{0,30}?(?:горяч\w+|отоплен\w+)", 20
            ),
            _anchor(
                r"(?:расстояни\w+|зазор\w*)\s+(?:в\s+свету\s+)?между\s+(?:\w+\s+){0,2}"
                r"(?:трубопровод\w+|трубам\w*|сетями|сетей)",
                12,
            ),
        ),
        context=_HOT_COLD_CTX,
        context_required=True,
        min_mm=20,
        max_mm=500,
        assumption=NormAssumption(
            mm_from=100,
            mm_to=None,
            reference="СП 40-101-96, п. 2.25",
            status=AssumptionStatus.ANALOGY,
            note=(
                "Холодное ниже горячего и отопления, не менее 100 мм в свету. Норма написана для "
                "труб из PPRC; для сшитого полиэтилена (PE-Xa) распространена по аналогии."
            ),
        ),
    ),
    DocQuestion(
        code=DocQuestionCode.DUCT_SECTION,
        title="Сечения воздуховодов ДУ / ДП: система, ширина×высота, мм",
        receiver_param="duct_section_mm",
        value_kind=DocValueKind.SECTION_MM,
        extractor=ExtractorKind.SECTION,
        sources=(
            DocSource("ИОС4 / ОВ: ПЗ и таблицы", _HVAC, (_K.TEXT, _K.TABLE)),
            DocSource("ИОС4 / ОВ: прочее", _HVAC),
        ),
        anchors=(
            _anchor(
                r"клапан\w*\s+(?:дымоудален\w+|противодымн\w+|дымов\w+|огнезадерживающ\w+)", 15
            ),
            _anchor(
                r"(?:дымоудален\w+|подпор\w*|противодымн\w+)[^.;]{0,60}?"
                r"(?:воздуховод\w*|клапан\w*|шахт\w+)",
                15,
            ),
            _anchor(r"(?<!\w)(?-i:КДУ|ДУ|ДП)\s*-?\s*\d", 12),
            _anchor(r"воздуховод\w*", 8),
        ),
        context=_SMOKE_CTX,
        context_required=True,
        min_mm=100,
        max_mm=4000,
    ),
    DocQuestion(
        code=DocQuestionCode.CABLE_TRAY_SECTION,
        title="Сечения кабельных лотков: ширина×высота, мм",
        receiver_param="cable_tray_section_mm",
        value_kind=DocValueKind.SECTION_MM,
        extractor=ExtractorKind.SECTION,
        sources=(
            DocSource("ИОС1 / ЭОМ / СС: ПЗ и таблицы", _ELECTRIC, (_K.TEXT, _K.TABLE)),
            DocSource("ИОС1 / ЭОМ / СС: прочее", _ELECTRIC),
        ),
        anchors=(
            _anchor(r"кабельн\w+\s+(?:лот\w+|короб\w*|канал\w*)", 15),
            _anchor(r"перфорированн\w+\s+лот\w+", 15),
            _anchor(r"(?<![а-я])лот(?:ок|ки|ков|ка|ке|ку|ком|ками|ках)(?![а-я])", 12),
        ),
        min_mm=20,
        max_mm=1000,
    ),
)


def question_by_code(code: DocQuestionCode) -> DocQuestion:
    for question in DOC_QUESTIONS:
        if question.code == code:
            return question
    raise KeyError(code)
