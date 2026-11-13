"""Контракты контура «Конструкции CAD» (ADR-0038): параметры конструкций, высоты листа, расчёт.

Здесь три группы моделей:

- вход скрипта `cad_walls` — разбор `walls.json` (схема `quantor.cad_walls.v1`), лишние поля
  игнорируются, нужные проверяются; исполнитель и API разбирают файл одной и той же схемой;
- данные человека — параметры конструкции и переопределения высот листа;
- ответы API — конструкции с вычисленными величинами, проёмы и итоги.

Величины контура не входят в итоги обмера и не пишутся в таблицы обмера, MEP и calc. Не
определено — `None`, а не 0.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import JobStatus

WALLS_SCHEMA: Final = "quantor.cad_walls.v1"
MAX_BULK_KEYS: Final = 2000

# Происхождение величины: observed - прочитано из документации; derived - выведено из неё;
# assumption - допущение параметров скрипта; manual - ввод человека.
CadValueSource = Literal["observed", "derived", "assumption", "manual"]
# Основание высоты конструкции: sheet - высота стены листа; manual - ввод человека;
# apartment_partition - высота маячного ряда внутриквартирных перегородок из «Вопросов к
# документации»; bathroom_wall - стена санузла (ПГП 80) и shaft_enclosure - обстройка шахты:
# обе на полную высоту стены листа, маячный ряд к ним не применяется.
CadHeightBasis = Literal[
    "sheet", "manual", "apartment_partition", "bathroom_wall", "shaft_enclosure"
]
# `floor_slab` — плита перекрытия листа: одна на лист, контур и отверстия — из ключа `slab`.
CadConstructionKind = Literal[
    "masonry",
    "monolith_wall",
    "monolith_pylon",
    "monolith_column",
    "frame_partition",
    "floor_slab",
]
CadComputedStatus = Literal["ok", "thickness_check", "height_missing"]
CadConstructionWarning = Literal[
    "thickness_check", "height_missing", "opening_no_data", "opening_estimate", "material_check"
]
# Материал из условных обозначений: matched - найден; not_in_legend - толщины нет в легенде;
# conflict - в легенде несколько материалов; no_legend - легенды на листе нет (ADR-0040).
CadMaterialHintStatus = Literal["matched", "not_in_legend", "conflict", "no_legend"]
CadMaterialSource = Literal["manual", "document"]

# Материал: газобетон, керамзитобетонный блок, керамический блок, кирпич полнотелый,
# кирпич пустотелый, силикатный блок, пазогребневая плита, монолитный железобетон, другое.
CadMaterial = Literal[
    "aerated_concrete",
    "expanded_clay_block",
    "ceramic_block",
    "brick_solid",
    "brick_hollow",
    "silicate_block",
    "gypsum_tongue_groove",
    "monolith_concrete",
    "other",
]
CadBrickLayout = Literal["half", "one", "one_and_half", "two"]
CadMortar = Literal["glue", "cement_sand", "other"]
# Предмет итога: конструкция листа или монолитные перемычки над проёмами (отдельная группа).
CadGroupElement = Literal["construction", "lintel"]
CadPurpose = Literal["external", "inter_apartment", "interior", "mop", "shaft", "other"]


# --------------------------------------------------------------------------- walls.json


class WallsPolygon(BaseModel):
    """Контур в мм DXF: внешнее кольцо и отверстия, без повторного замыкающего узла."""

    model_config = ConfigDict(extra="ignore")

    shell: list[list[float]]
    holes: list[list[list[float]]]


class WallsHintEvidence(BaseModel):
    """Строка условных обозначений, по которой подобран материал."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(max_length=200)
    page_index: int
    bbox: list[float] = Field(min_length=4, max_length=4)


class WallsMaterialHint(BaseModel):
    """Подсказка материала из условных обозначений листа (ADR-0040); не данные человека."""

    model_config = ConfigDict(extra="ignore")

    value: CadMaterial | None
    source: Literal["legend"]
    status: CadMaterialHintStatus
    evidence: list[WallsHintEvidence] = []


class WallsConstruction(BaseModel):
    """Конструкция из walls.json: связный участок кладки, монолита или каркасной перегородки."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=32)
    kind: CadConstructionKind
    source_layers: list[str]
    polygon: WallsPolygon
    area_plan_mm2: float
    thickness_measured_mm: float
    thickness_nominal_mm: float | None
    thickness_status: Literal["matched", "check"]
    length_axis_mm: float
    centroid: list[float]
    bbox: list[float]
    # Нет у монолита и каркасных перегородок и в старых walls.json (v1, v1.1).
    material_hint: WallsMaterialHint | None = None


class WallsWindow(BaseModel):
    """Пролёт остекления плана АР, из которого движок построил окно (cad_walls v1.12)."""

    model_config = ConfigDict(extra="ignore")

    bay_id: str


class WallsOpening(BaseModel):
    """Проём: дверь (по блоку DXF), безымянный разрыв стены (`gap`) или окно (`window`, v1.12).

    Окно: `leaf`/`block_name` пусты, `handle` - полилиния пролёта, `lintel` - прямоугольник проёма,
    высота (`opening_height_mm`) по плану не определяется (`None`, статус `unknown`).
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    kind: Literal["door", "gap", "window"]
    status: Literal["ok", "estimate", "no_data"]
    host_id: str | None
    adjacent_ids: list[str]
    width_mm: float
    width_source: str
    thickness_mm: float | None
    block_name: str | None
    handle: str | None
    center: list[float]
    # Пролёт остекления (только у `window`).
    window: WallsWindow | None = None
    # Контур перемычки в плане (4 точки) и её материал (`monolith`, `masonry`, `frame_partition`):
    # нет у дверей без разрыва и в старых walls.json.
    lintel: list[list[float]] | None = None
    lintel_material: str | None = None
    # Высота разрыва (`gap`) и её статус (cad_walls v1.9); у дверей и в старых файлах — `None`.
    opening_height_mm: int | None = None
    opening_height_status: str | None = None


class CadSheetFloorTitle(BaseModel):
    """Заголовок плана листа из текста PDF: корпус, секция, этажи (cad_walls v1.5).

    Один тип и для разбора `walls.json` (этажи там числа), и для ответов API (этажи строками).
    """

    model_config = ConfigDict(extra="ignore")

    corps: str | None = None
    section: str | None = None
    floors: list[str] = Field(default_factory=list)
    text: str | None = None

    @field_validator("floors", mode="before")
    @classmethod
    def _floors_as_text(cls, value: object) -> object:
        if isinstance(value, list):
            return [str(item) for item in value if isinstance(item, int | str)]
        return value


class WallsHeights(BaseModel):
    """Исходные величины высоты: отметки из документации и допущения параметров скрипта."""

    model_config = ConfigDict(extra="ignore")

    floor_elevation_mm: int | None
    floor_height_mm: int | None
    elevation_status: str
    height_status: str
    evidence: str | None
    message: str | None
    slab_thickness_mm: int | None
    slab_status: str
    door_height_mm: int | None
    door_height_status: str
    # Заголовок плана (cad_walls v1.5); у старого файла и без заголовка — `None`.
    title: CadSheetFloorTitle | None = None
    # cad_walls v1.9: отметка листа АР — чистый пол (`clean_floor`), верх плиты ниже на пирог пола.
    # Всех полей нет в старых файлах (v1.8 и раньше) — тогда отметка листа = верх плиты.
    floor_elevation_basis: str | None = None
    floor_finish_mm: int | None = None
    floor_finish_status: str | None = None
    # Отметка верха плиты (чистый пол минус пирог); `None` — отметки листа нет или файл старый.
    slab_top_elevation_mm: int | None = None
    # Высота проёмов-разрывов (`gap`): двери лифтов и шахт без дверного блока.
    gap_opening_height_mm: int | None = None
    gap_opening_height_status: str | None = None


class WallsWarning(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    message: str


class WallsChecks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    warnings: list[WallsWarning]


class WallsDocument(BaseModel):
    """walls.json целиком (схема `quantor.cad_walls.v1`)."""

    model_config = ConfigDict(extra="ignore")

    schema_name: str = Field(alias="schema")
    generator: str
    params_version: str
    params_sha256: str
    dxf_sha256: str
    units: Literal["mm"]
    heights: WallsHeights
    constructions: list[WallsConstruction]
    # Каркасные перегородки ГКЛ (ADR-0040): те же поля конструкции; нет в старых walls.json.
    frame_partitions: list[WallsConstruction] = []
    openings: list[WallsOpening]
    checks: WallsChecks


# --------------------------------------------------------------------------- данные человека


class CadConstructionProps(BaseModel):
    """Параметры конструкции. Все поля необязательные; пустое поле — не задано."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    material: CadMaterial | None = Field(
        default=None,
        description=(
            "Материал: aerated_concrete - газобетон; expanded_clay_block - керамзитобетонный "
            "блок; ceramic_block - керамический блок; brick_solid - кирпич полнотелый; "
            "brick_hollow - кирпич пустотелый; silicate_block - силикатный блок; "
            "gypsum_tongue_groove - пазогребневая плита; monolith_concrete - монолитный "
            "железобетон; other - другое"
        ),
    )
    material_note: str | None = Field(
        default=None, max_length=200, description="Уточнение материала (свободный текст)"
    )
    density_grade: str | None = Field(
        default=None, max_length=16, description="Марка по плотности, например D500"
    )
    strength_class: str | None = Field(
        default=None, max_length=16, description="Класс или марка по прочности: B2,5, B25, М150"
    )
    block_length_mm: int | None = Field(
        default=None, ge=10, le=2000, description="Длина блока или кирпича, мм"
    )
    block_width_mm: int | None = Field(
        default=None, ge=10, le=2000, description="Ширина (толщина по кладке) блока, мм"
    )
    block_height_mm: int | None = Field(
        default=None, ge=10, le=2000, description="Высота блока или кирпича, мм"
    )
    brick_layout: CadBrickLayout | None = Field(
        default=None,
        description=(
            "Кладка кирпича: half - в полкирпича; one - в один кирпич; one_and_half - в полтора "
            "кирпича; two - в два кирпича"
        ),
    )
    mortar: CadMortar | None = Field(
        default=None,
        description="Раствор: glue - клей; cement_sand - цементно-песчаный; other - другой",
    )
    joint_mm: int | None = Field(default=None, ge=1, le=30, description="Толщина шва, мм")
    reinforcement: str | None = Field(
        default=None, max_length=200, description="Армирование кладки или монолита"
    )
    purpose: CadPurpose | None = Field(
        default=None,
        description=(
            "Назначение: external - наружная; inter_apartment - межквартирная; "
            "interior - внутренняя; mop - стена МОП; shaft - шахта; other - другое"
        ),
    )
    fire_rating: str | None = Field(
        default=None, max_length=16, description="Предел огнестойкости, например EI 150"
    )
    sound_rw_db: int | None = Field(
        default=None, ge=0, le=90, description="Индекс звукоизоляции Rw, дБ"
    )
    height_override_mm: int | None = Field(
        default=None, ge=100, le=10000, description="Высота конструкции вместо расчётной, мм"
    )
    thickness_override_mm: int | None = Field(
        default=None, ge=30, le=1500, description="Толщина вместо номинала скрипта, мм"
    )
    count_openings: bool = Field(
        default=True,
        description="Учитывать надпроёмные части дверей в объёме и площади стены",
    )
    note: str | None = Field(default=None, max_length=1000, description="Примечание")


class CadSheetLevelsWrite(BaseModel):
    """Высоты листа, заданные человеком. Пустое поле — значение из walls.json."""

    model_config = ConfigDict(extra="forbid")

    floor_height_mm: int | None = Field(
        default=None, ge=2000, le=6000, description="Высота этажа (пол - пол), мм"
    )
    slab_thickness_mm: int | None = Field(
        default=None, ge=100, le=1000, description="Толщина плиты перекрытия, мм"
    )
    door_height_mm: int | None = Field(
        default=None, ge=1500, le=3500, description="Высота дверного проёма, мм"
    )
    floor_elevation_mm: int | None = Field(
        default=None, ge=-100000, le=500000, description="Отметка этажа = верх плиты, мм"
    )


class CadConstructionPropsPut(BaseModel):
    """Параметры одной конструкции целиком (заменяют хранимые) и признак «принято человеком»."""

    model_config = ConfigDict(extra="forbid")

    props: CadConstructionProps
    accepted: bool | None = Field(
        default=None, description="Принято человеком; не передано - прежнее значение"
    )


class CadConstructionPropsBulk(BaseModel):
    """Частичное слияние параметров в несколько конструкций («применить ко всем этой толщины»).

    В `props_patch` применяются только переданные поля; поле, переданное как null, снимает
    значение у каждой конструкции.
    """

    model_config = ConfigDict(extra="forbid")

    keys: list[str] = Field(min_length=1, max_length=MAX_BULK_KEYS)
    props_patch: CadConstructionProps
    accepted: bool | None = Field(
        default=None, description="Принято человеком; не передано - прежнее значение"
    )


# --------------------------------------------------------------------------- ответы


class CadLevelValueRead(BaseModel):
    """Величина высоты: действующее значение, происхождение и значение из walls.json."""

    value_mm: int | None
    source: CadValueSource | None
    # Значение из walls.json; у переопределённой человеком величины отличается от `value_mm`.
    default_mm: int | None


class CadPartitionHeightRead(BaseModel):
    """Высота маячного ряда перегородок: принятый ответ «Вопросов к документации»."""

    height_mm: int
    # observed - ответ из документа; manual - значение ввёл человек.
    source: CadValueSource
    answer_id: UUID
    file_name: str | None
    page_index: int | None
    quote: str | None


class CadHeightsRead(BaseModel):
    """Высоты листа с источниками. Не определилось — `None` («требует ввода»), не 0."""

    floor_elevation_mm: int | None
    floor_elevation_source: CadValueSource | None
    floor_height: CadLevelValueRead
    slab_thickness: CadLevelValueRead
    door_height: CadLevelValueRead
    # Лист разреза, если толщина плиты взята из уровня проекта (ADR-0039 п. 4).
    slab_thickness_sheet_ref: str | None = None
    # Высота стены = высота этажа - толщина плиты; None, если высота этажа не определена.
    wall_height_mm: int | None
    wall_height_source: CadValueSource | None
    evidence: str | None
    message: str | None
    # Принятая высота маячного ряда перегородок; `None` - ответа нет.
    apartment_partition_height: CadPartitionHeightRead | None = None


class CadSheetLevelsRead(BaseModel):
    """Переопределения человека (пусто — значение из walls.json)."""

    floor_height_mm: int | None
    slab_thickness_mm: int | None
    door_height_mm: int | None
    floor_elevation_mm: int | None = None


class CadComputedSourcesRead(BaseModel):
    thickness: CadValueSource | None
    height: CadValueSource | None
    door_height: CadValueSource | None
    # Происхождение высоты разрывов, чья надпроёмная часть вошла в объём (v1.9): обычно допущение.
    gap_opening_height: CadValueSource | None = None


class CadConstructionComputedRead(BaseModel):
    """Вычисленные величины конструкции. Не определено — `None`.

    У плиты перекрытия длина, высота и площадь стены не определены, `area_m2` — площадь плиты
    нетто (контур минус включённые отверстия); у стен `area_m2` — `None`.
    """

    thickness_mm: float | None
    height_mm: int | None
    length_m: float | None
    wall_area_m2: float | None
    volume_m3: float | None
    status: CadComputedStatus
    sources: CadComputedSourcesRead
    warnings: list[CadConstructionWarning]
    area_m2: float | None = None
    # Основание высоты; у плиты (высоты нет) - `None`.
    height_basis: CadHeightBasis | None = None


class CadConstructionMaterialRead(BaseModel):
    """Действующий материал: ввод человека, иначе подсказка из условных обозначений."""

    value: CadMaterial | None
    source: CadMaterialSource | None
    # Статус подсказки из walls.json; None - подсказки нет (монолит, перегородка, старый файл).
    hint_status: CadMaterialHintStatus | None
    evidence: list[WallsHintEvidence]


class CadConstructionRead(BaseModel):
    """Конструкция: геометрия из walls.json, вычисленные величины, параметры человека."""

    id: str
    kind: CadConstructionKind
    source_layers: list[str]
    polygon: WallsPolygon
    centroid: list[float]
    bbox: list[float]
    area_plan_m2: float
    thickness_measured_mm: float
    thickness_nominal_mm: float | None
    thickness_status: Literal["matched", "check"]
    computed: CadConstructionComputedRead
    props: CadConstructionProps
    material: CadConstructionMaterialRead
    accepted: bool


class CadOpeningRead(BaseModel):
    id: str
    kind: Literal["door", "gap", "window"]
    status: Literal["ok", "estimate", "no_data"]
    host_id: str | None
    adjacent_ids: list[str]
    width_mm: float
    width_source: str
    thickness_mm: float | None
    block_name: str | None
    handle: str | None
    center: list[float]
    # Проём между перегородками с маячным рядом: разрыв выкладки, не проём кладки - без полотна,
    # перемычки и надпроёмной части, из объёма не вычитается.
    marker_row_gap: bool = False


class CadConstructionGroupRead(BaseModel):
    """Итог группы «вид x толщина x материал»; в группу входят только конструкции со статусом ok.

    Материал — действующий (ввод человека или документ). У каркасной перегородки `volume_m3` —
    `None`: она меряется площадью. У плиты перекрытия `area_m2` — сумма площадей нетто, у стен —
    `None`.
    """

    kind: CadConstructionKind
    # `lintel` - монолитные перемычки над проёмами в кладке и перегородках: `count` - штуки,
    # `length_m` - сумма ширин проёмов, `thickness_mm` - толщина стены-хозяина, `wall_area_m2` - 0.
    element: CadGroupElement = "construction"
    thickness_mm: float
    material: CadMaterial | None
    count: int
    length_m: float
    wall_area_m2: float
    volume_m3: float | None
    area_m2: float | None = None


class CadConstructionsSummaryRead(BaseModel):
    """Что в итоги групп не вошло."""

    total_count: int
    thickness_check_count: int
    height_missing_count: int
    # Разрывы стен и окна без высоты проёма (порталы, окна v1.12): в объём не входят.
    unaccounted_gap_openings: int
    # Двери, у которых скрипт не нашёл несущую стену: надпроёмная часть не учтена.
    door_openings_without_host: int
    # Монолитные перемычки без определимого объёма (нет высоты, толщины, хозяина): в итоги не вошли.
    lintels_without_volume: int = 0
    # Параметры человека, чья конструкция пропала после пересчёта и не нашлась по геометрии:
    # в расчёт не входят, строки в базе сохранены.
    orphaned_props: int = 0
    # Параметры, перенесённые на новые адреса конструкций по геометрии в этом запросе.
    props_carried_over: int = 0
    # Внутриквартирные перегородки, посчитанные по высоте маячного ряда.
    apartment_partition_count: int = 0


class CadWallsWarningRead(BaseModel):
    code: str
    message: str


class CadConstructionsTotalsRead(BaseModel):
    """Итоги листа после пересчёта."""

    heights: CadHeightsRead
    sheet_levels: CadSheetLevelsRead
    totals: list[CadConstructionGroupRead]
    summary: CadConstructionsSummaryRead


class CadConstructionsBulkRead(CadConstructionsTotalsRead):
    changed: int


class CadLatestWallsJobRead(BaseModel):
    """Самое свежее задание `cad_walls` вида, в том числе незавершённое или упавшее."""

    id: UUID
    status: JobStatus
    error_code: str | None
    error_message: str | None
    created_at: datetime


class CadConstructionsRead(CadConstructionsTotalsRead):
    """Конструкции вида по последнему успешному заданию `cad_walls`."""

    job_id: UUID
    page_index: int
    view: int
    walls_job_id: UUID
    walls_sha256: str
    # Свежее задание может быть новее успешного, из которого взяты конструкции.
    latest_walls_job: CadLatestWallsJobRead | None = None
    generator: str
    params_version: str
    params_sha256: str
    dxf_sha256: str
    constructions: list[CadConstructionRead]
    openings: list[CadOpeningRead]
    warnings: list[CadWallsWarningRead]


class CadWallsJobRead(BaseModel):
    """Задание `cad_walls`, поставленное на пересчёт конструкций вида."""

    job_id: UUID
    parent_job_id: UUID
    page_index: int
    view: int
    status: JobStatus
    attempt: int
    created_at: datetime
