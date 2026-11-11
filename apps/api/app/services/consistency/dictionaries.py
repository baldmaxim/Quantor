"""Общие словари контура согласованности (ADR-0043).

Только общедоступные нормативные обозначения (ПП РФ № 87, ГОСТ Р 21.101, СП 30, СП 60,
ГОСТ 21.601). Ничего про конкретные объекты: отклонение проекта решает человек при
подтверждении, а не правка словаря. Модуль не импортирует calc и CAD.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# --------------------------------------------------------------------------- нормализация

_LOOKALIKES: Final = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")


def normalize_mark(text: str) -> str:
    """Верхний регистр и латинские двойники кириллицы: «Ар» и «AP» → «АР»."""
    return text.upper().translate(_LOOKALIKES)


_DASHES: Final = re.compile(r"[‐-―−]")
_SPACES: Final = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """Нижний регистр, ё → е, любые тире → «-», пробелы схлопнуты."""
    lowered = text.lower().replace("ё", "е")
    return _SPACES.sub(" ", _DASHES.sub("-", lowered)).strip()


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Целое слово или фраза; пробел и дефис внутри фразы взаимозаменяемы."""
    pieces = [re.escape(piece) for piece in re.split(r"[\s\-]+", phrase) if piece]
    return re.compile(rf"(?<!\w){r'[\s\-]+'.join(pieces)}(?!\w)")


# --------------------------------------------------------------------------- разделы

SECTION_MARKS_VERSION: Final = "consistency.dict.sections.v3"


class SectionGroup(StrEnum):
    GENERAL = "general"
    ARCHITECTURE = "architecture"
    STRUCTURE = "structure"
    MEP = "mep"
    FIRE = "fire"
    ORGANIZATION = "organization"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SectionMark:
    """Марка раздела проектной документации."""

    mark: str
    title: str
    group: SectionGroup
    aliases: tuple[str, ...] = ()


_G = SectionGroup

SECTION_MARKS: Final[tuple[SectionMark, ...]] = (
    SectionMark("ПЗ", "Пояснительная записка", _G.GENERAL),
    SectionMark("СП", "Состав проекта", _G.GENERAL),
    SectionMark("ПЗУ", "Схема планировочной организации земельного участка", _G.ARCHITECTURE),
    SectionMark("АР", "Архитектурные решения", _G.ARCHITECTURE),
    SectionMark("КР", "Конструктивные решения", _G.STRUCTURE),
    SectionMark("КЖ", "Конструкции железобетонные", _G.STRUCTURE),
    SectionMark("КМ", "Конструкции металлические", _G.STRUCTURE),
    SectionMark("ИОС1", "Система электроснабжения", _G.MEP),
    SectionMark("ИОС2", "Система водоснабжения", _G.MEP),
    SectionMark("ИОС3", "Система водоотведения", _G.MEP),
    SectionMark(
        "ИОС4",
        "Отопление, вентиляция и кондиционирование воздуха, тепловые сети",
        _G.MEP,
        ("ОВиК",),
    ),
    SectionMark("ИОС5", "Сети связи", _G.MEP),
    SectionMark("ИОС6", "Система газоснабжения", _G.MEP),
    SectionMark("ИОС7", "Технологические решения", _G.MEP),
    SectionMark("ЭОМ", "Электрооборудование и электроосвещение", _G.MEP),
    SectionMark("ЭС", "Электроснабжение", _G.MEP),
    SectionMark("ЭМ", "Силовое электрооборудование", _G.MEP),
    SectionMark("ЭО", "Электрическое освещение", _G.MEP),
    SectionMark("ВК", "Водопровод и канализация", _G.MEP),
    SectionMark("НВК", "Наружные сети водоснабжения и канализации", _G.MEP),
    SectionMark("ВС", "Водоснабжение", _G.MEP),
    SectionMark("ВО", "Водоотведение", _G.MEP),
    SectionMark("ОВ", "Отопление и вентиляция", _G.MEP),
    SectionMark("ТС", "Тепловые сети", _G.MEP),
    SectionMark("ИТП", "Индивидуальный тепловой пункт", _G.MEP),
    SectionMark("СС", "Сети связи", _G.MEP),
    SectionMark("ГС", "Газоснабжение", _G.MEP),
    SectionMark("ТХ", "Технологические решения", _G.MEP),
    SectionMark("ПОС", "Проект организации строительства", _G.ORGANIZATION),
    SectionMark("ПОД", "Проект организации работ по сносу или демонтажу", _G.ORGANIZATION),
    SectionMark("ООС", "Охрана окружающей среды", _G.OTHER),
    SectionMark("ПБ", "Мероприятия по обеспечению пожарной безопасности", _G.FIRE),
    SectionMark("АПТ", "Автоматическое пожаротушение", _G.FIRE),
    SectionMark("АУПТ", "Автоматические установки пожаротушения", _G.FIRE),
    SectionMark("ПС", "Пожарная сигнализация", _G.FIRE),
    SectionMark("ОДИ", "Мероприятия по обеспечению доступа инвалидов", _G.OTHER),
    SectionMark("ГОЧС", "Мероприятия по гражданской обороне и предупреждению ЧС", _G.OTHER),
    SectionMark("ТБЭ", "Требования к обеспечению безопасной эксплуатации", _G.OTHER),
    SectionMark("ПКР", "Сведения о периодичности капитального ремонта", _G.OTHER),
    SectionMark("ИРД", "Исходно-разрешительная документация", _G.GENERAL),
    SectionMark("ЭЭ", "Энергетическая эффективность", _G.OTHER),
    SectionMark("СМ", "Смета на строительство", _G.ORGANIZATION),
    SectionMark("ГП", "Генеральный план", _G.ARCHITECTURE),
    SectionMark("ДП", "Дендроплан", _G.ARCHITECTURE),
    SectionMark("АИ", "Архитектурные решения интерьеров", _G.ARCHITECTURE),
    SectionMark("ИО", "Интерьеры общих зон", _G.ARCHITECTURE),
    SectionMark("ЕОИ", "Единое оформление интерьеров", _G.ARCHITECTURE),
    SectionMark("ГИ", "Гидроизоляция", _G.STRUCTURE),
    SectionMark("ЗМ", "Заземление и молниезащита", _G.MEP),
    SectionMark("ДР", "Дренаж", _G.MEP),
    SectionMark("АИТ", "Автоматизация индивидуального теплового пункта", _G.MEP),
    SectionMark("ЛВС", "Локальная вычислительная сеть", _G.MEP),
    SectionMark("ДЛ", "Диспетчеризация лифтов", _G.MEP),
    SectionMark("ОЗДС", "Охранно-защитная дератизационная система", _G.MEP),
    SectionMark("ГПТ", "Газовое пожаротушение", _G.FIRE),
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    mark: str
    is_alias: bool


def _build_candidates() -> tuple[_Candidate, ...]:
    items = [_Candidate(normalize_mark(m.mark), m.mark, False) for m in SECTION_MARKS]
    items += [
        _Candidate(normalize_mark(alias), section.mark, True)
        for section in SECTION_MARKS
        for alias in section.aliases
    ]
    # Сначала длинные («ИОС2» раньше «ИОС»); сортировка устойчива.
    return tuple(sorted(items, key=lambda item: -len(item.key)))


_MARK_CANDIDATES: Final = _build_candidates()
_TOKEN_SPLIT: Final = re.compile(r"[-_.\s/,]+")


def match_section_mark(
    code: str, allowed: Collection[str] | None = None, *, with_aliases: bool = True
) -> str | None:
    """Марка раздела по шифру: «ПД-00000000-АР.С-КОР1» → «АР»; «…-ОВ0-1» → «ОВ».

    Токен шифра подходит, если начинается с марки и остаток пуст или состоит из цифр.
    `allowed` ограничивает набор основных марок; алиас возвращает основную марку.
    """
    permitted = None if allowed is None else {normalize_mark(item) for item in allowed}
    for token in _TOKEN_SPLIT.split(normalize_mark(code)):
        for candidate in _MARK_CANDIDATES:
            if candidate.is_alias and not with_aliases:
                continue
            if permitted is not None and normalize_mark(candidate.mark) not in permitted:
                continue
            rest = token[len(candidate.key) :]
            if token.startswith(candidate.key) and (not rest or rest.isdigit()):
                return candidate.mark
    return None


# --------------------------------------------------------------------------- типы листов

SHEET_KINDS_VERSION: Final = "consistency.dict.sheet_kinds.v2"


class SheetKind(StrEnum):
    FLOOR_PLAN = "floor_plan"
    SECTION = "section"
    FACADE = "facade"
    SCHEME = "scheme"
    TABLE = "table"
    TEXT = "text"
    GENERAL_DATA = "general_data"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SheetKindKeywords:
    kind: SheetKind
    keywords: tuple[str, ...]


SHEET_KIND_KEYWORDS: Final[tuple[SheetKindKeywords, ...]] = (
    SheetKindKeywords(
        SheetKind.GENERAL_DATA, ("общие данные", "общие указания", "условные обозначения")
    ),
    SheetKindKeywords(SheetKind.FLOOR_PLAN, ("план", "планы", "плана")),
    SheetKindKeywords(SheetKind.SECTION, ("разрез", "разрезы")),
    SheetKindKeywords(SheetKind.FACADE, ("фасад", "фасады")),
    SheetKindKeywords(
        SheetKind.SCHEME, ("схема", "схемы", "аксонометрическая схема", "аксонометрия")
    ),
    SheetKindKeywords(
        SheetKind.TABLE,
        (
            "экспликация",
            "экспликации",
            "спецификация",
            "спецификации",
            "ведомость",
            "ведомости",
            "таблица",
            "таблицы",
        ),
    ),
    SheetKindKeywords(SheetKind.TEXT, ("пояснительная записка", "текстовая часть")),
)

_SHEET_KIND_PATTERNS: Final = tuple(
    (entry.kind, tuple(_phrase_pattern(_normalize_text(word)) for word in entry.keywords))
    for entry in SHEET_KIND_KEYWORDS
)


def sheet_kind_match(title: str) -> tuple[SheetKind, int] | None:
    """Тип листа по заголовку и позиция ключевого слова в нормализованном тексте.

    Совпадение по целому слову, побеждает слово, стоящее в заголовке раньше.
    """
    text = _normalize_text(title)
    best: tuple[int, SheetKind] | None = None
    for kind, patterns in _SHEET_KIND_PATTERNS:
        for pattern in patterns:
            found = pattern.search(text)
            if found is not None and (best is None or found.start() < best[0]):
                best = (found.start(), kind)
    return None if best is None else (best[1], best[0])


def sheet_kind_from_title(title: str) -> SheetKind | None:
    """Тип листа по заголовку: совпадение по целому слову, побеждает раннее в заголовке."""
    match = sheet_kind_match(title)
    return None if match is None else match[0]


# --------------------------------------------------------------------------- коды систем

SYSTEM_CODES_VERSION: Final = "consistency.dict.systems.v1"


@dataclass(frozen=True, slots=True)
class SystemCode:
    """Код трубопроводной системы по СП 30 и ГОСТ 21.601."""

    code: str
    title: str
    default_section: str


SYSTEM_CODES: Final[tuple[SystemCode, ...]] = (
    SystemCode("В1", "Хозяйственно-питьевой водопровод", "ИОС2"),
    SystemCode("В2", "Противопожарный водопровод", "ИОС2"),
    SystemCode("Т3", "Горячее водоснабжение, подача", "ИОС2"),
    SystemCode("Т4", "Горячее водоснабжение, циркуляция", "ИОС2"),
    SystemCode("К1", "Бытовая канализация", "ИОС3"),
    SystemCode("К2", "Внутренние водостоки", "ИОС3"),
    SystemCode("К3", "Производственная канализация", "ИОС3"),
    SystemCode("ВПВ", "Внутренний противопожарный водопровод", "ИОС2"),
    SystemCode("АУП", "Автоматическая установка пожаротушения", "ИОС2"),
)

_SYSTEMS_BY_CODE: Final = {normalize_mark(item.code): item for item in SYSTEM_CODES}


def system_from_code(code: str) -> SystemCode | None:
    """Система по коду: нормализация и точное совпадение («т3» → Т3)."""
    return _SYSTEMS_BY_CODE.get(normalize_mark(code.strip()))


# --------------------------------------------------------------------------- типы помещений

ROOM_TYPES_VERSION: Final = "consistency.dict.rooms.v1"


class RoomType(StrEnum):
    APARTMENT = "apartment"
    LIVING_ROOM = "living_room"
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    TOILET = "toilet"
    CORRIDOR_COMMON = "corridor_common"
    STAIR = "stair"
    ELEVATOR_HALL = "elevator_hall"
    ELEVATOR_SHAFT = "elevator_shaft"
    UTILITY_SHAFT = "utility_shaft"
    CLEANING_ROOM = "cleaning_room"
    TECHNICAL = "technical"
    STORAGE = "storage"
    VESTIBULE = "vestibule"
    LOBBY = "lobby"
    COMMERCIAL = "commercial"
    PARKING = "parking"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RoomSynonyms:
    room_type: RoomType
    phrases: tuple[str, ...]


# «Кухня-гостиная» — кухня: для связи с ИОС важна мокрая точка, а она на кухонной зоне.
ROOM_SYNONYMS: Final[tuple[RoomSynonyms, ...]] = (
    RoomSynonyms(RoomType.APARTMENT, ("квартира", "студия")),
    RoomSynonyms(
        RoomType.LIVING_ROOM, ("гостиная", "жилая комната", "комната", "спальня", "детская")
    ),
    RoomSynonyms(
        RoomType.KITCHEN,
        ("кухня", "кухня-ниша", "кухня-гостиная", "кухня-столовая", "кухня-студия"),
    ),
    RoomSynonyms(
        RoomType.BATHROOM,
        ("ванная", "ванная комната", "санузел", "совмещенный санузел", "санитарный узел", "с/у"),
    ),
    RoomSynonyms(RoomType.TOILET, ("туалет", "уборная", "wc")),
    RoomSynonyms(
        RoomType.CORRIDOR_COMMON,
        ("коридор", "общий коридор", "межквартирный коридор", "внеквартирный коридор"),
    ),
    RoomSynonyms(RoomType.STAIR, ("лестница", "лестничная клетка", "лестничная площадка", "лк")),
    RoomSynonyms(
        RoomType.ELEVATOR_HALL, ("лифтовой холл", "лифтовый холл", "лифтовой холл-тамбур")
    ),
    RoomSynonyms(RoomType.ELEVATOR_SHAFT, ("лифт", "лифтовая шахта", "шахта лифта")),
    RoomSynonyms(
        RoomType.UTILITY_SHAFT,
        (
            "шахта",
            "инженерная шахта",
            "сантехническая шахта",
            "вентиляционная шахта",
            "вентшахта",
            "мусоропровод",
        ),
    ),
    RoomSynonyms(
        RoomType.CLEANING_ROOM,
        (
            "пуи",
            "уборочная",
            "помещение уборочного инвентаря",
            "помещение для уборочного инвентаря",
            "комната уборочного инвентаря",
            "кладовая уборочного инвентаря",
        ),
    ),
    RoomSynonyms(
        RoomType.TECHNICAL,
        (
            "техническое помещение",
            "технический этаж",
            "техпомещение",
            "итп",
            "индивидуальный тепловой пункт",
            "насосная",
            "венткамера",
            "электрощитовая",
            "слаботочная",
        ),
    ),
    RoomSynonyms(RoomType.STORAGE, ("кладовая", "кладовка", "колясочная", "склад")),
    RoomSynonyms(RoomType.VESTIBULE, ("тамбур", "входной тамбур", "тамбур-шлюз")),
    RoomSynonyms(RoomType.LOBBY, ("вестибюль", "холл", "лобби", "входная группа")),
    RoomSynonyms(
        RoomType.COMMERCIAL,
        (
            "коммерческое помещение",
            "торговое помещение",
            "торговый зал",
            "магазин",
            "офис",
            "кафе",
            "ресторан",
            "аптека",
            "помещение свободного назначения",
            "псн",
        ),
    ),
    RoomSynonyms(
        RoomType.PARKING, ("парковка", "паркинг", "автостоянка", "стоянка", "гараж", "машино-место")
    ),
)

_ROOM_PATTERNS: Final = tuple(
    (entry.room_type, phrase, _phrase_pattern(_normalize_text(phrase)))
    for entry in ROOM_SYNONYMS
    for phrase in entry.phrases
)


def room_type_from_name(name: str) -> RoomType | None:
    """Тип помещения по названию: целое слово или фраза; длиннее фраза — выше приоритет."""
    text = _normalize_text(name)
    best: tuple[int, int, RoomType] | None = None
    for room_type, phrase, pattern in _ROOM_PATTERNS:
        found = pattern.search(text)
        if found is None:
            continue
        rank = (len(phrase), -found.start())
        if best is None or rank > (best[0], best[1]):
            best = (rank[0], rank[1], room_type)
    return None if best is None else best[2]
