"""Контракты обмена Quantor ↔ TENDER (ADR-0051, формат `docs/tender-exchange/01-format.md`).

Два пакета: «База объекта» `quantor.object_base.v1` (Quantor → TENDER) и «Расчёт»
`quantor.tender_calc.v1` (TENDER → Quantor). Все файлы пакетов описаны моделями с
`extra="forbid"`: лишнее поле — нарушение, а не молчаливо принятые данные. Координаты — целые мм
кадра вида (`view_dxf_mm`: X вправо, Y вверх), Z — мм от чистого пола этажа. Цен в пакетах нет:
запрет стоимости проверяет приём расчёта (`services/tender_calc_import.py`).

JSON Schema всех файлов выгружается `python -m app.tender_schemas_export`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# --------------------------------------------------------------------------- общее

BASE_SCHEMA: Final = "quantor.object_base.v1"
BASE_VIEW_SCHEMA: Final = "quantor.object_base.view.v1"
BASE_AXES_SCHEMA: Final = "quantor.object_base.axes.v1"
BASE_ZONES_SCHEMA: Final = "quantor.object_base.zones.v1"
BASE_CONSTRUCTIONS_SCHEMA: Final = "quantor.object_base.constructions.v1"
BASE_RISERS_SCHEMA: Final = "quantor.object_base.risers.v1"
BASE_BUILDING_SCHEMA: Final = "quantor.object_base.building.v1"

CALC_SCHEMA: Final = "quantor.tender_calc.v1"
CALC_VIEW_SCHEMA: Final = "quantor.tender_calc.view.v1"
CALC_QUANTITIES_SCHEMA: Final = "quantor.tender_calc.quantities.v1"
CALC_QUESTIONS_SCHEMA: Final = "quantor.tender_calc.questions.v1"

# Пределы пакета расчёта (формат, раздел «Пакет «Расчёт»» и «Проверки портала»).
MAX_CALC_PACKAGE_BYTES: Final = 50 * 1024 * 1024
MAX_CALC_PACKAGE_FILES: Final = 2000
MAX_CALC_UNPACKED_BYTES: Final = 200 * 1024 * 1024
MAX_CALC_COMPRESSION_RATIO: Final = 100
MAX_CALC_FILE_BYTES: Final = 64 * 1024 * 1024
MAX_QUANTITY_ROWS: Final = 5000
MAX_QUESTION_ROWS: Final = 2000
MAX_POLYLINES_PER_VIEW: Final = 100_000
MAX_ELEMENTS_PER_VIEW: Final = 100_000
MAX_POLYLINE_POINTS: Final = 20_000
MAX_BASE_VIEWS: Final = 400

# Привязка к осям: больше — предупреждение, больше второго — отказ.
FIT_WARNING_MM: Final = 100.0
FIT_REFUSAL_MM: Final = 500.0

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# `<revision_id>:<page_index>:<view>`
ViewKey = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}:\d{1,4}:\d{1,3}$")
]
Point2 = Annotated[list[int], Field(min_length=2, max_length=2)]
Point3 = Annotated[list[int], Field(min_length=3, max_length=3)]
Ring = Annotated[list[Point2], Field(min_length=3, max_length=100_000)]

CalcDiscipline = Literal["mech", "eom", "ss"]
VersionStatus = Literal["active", "superseded", "withdrawn"]
DiffStatus = Literal["added", "removed", "changed", "same"]
SYSTEMS_BY_DISCIPLINE: Final[dict[str, tuple[str, ...]]] = {
    "mech": (
        "heating",
        "water_supply",
        "sewage",
        "storm_drain",
        "fire_sprinkler",
        "fire_hydrant",
        "dry_pipe",
        "ventilation",
        "smoke_control",
        "conditioning",
        "cooling",
        "itp",
        "mech_other",
    ),
    "eom": ("power", "lighting", "grounding", "lightning", "eom_other"),
    "ss": ("ss_network", "ss_security", "ss_fire_alarm", "ss_dispatch", "ss_other"),
}
QUANTITY_UNITS: Final = ("м", "м2", "м3", "шт", "компл", "т", "кг", "точка")


class _Strict(BaseModel):
    """Файл пакета: неизвестное поле — нарушение формата."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def parse_view_key(key: str) -> tuple[UUID, int, int]:
    """`<revision_id>:<page_index>:<view>` -> (ревизия, страница, вид)."""
    revision, page, view = key.split(":")
    return UUID(revision), int(page), int(view)


def make_view_key(revision_id: UUID, page_index: int, view: int) -> str:
    return f"{revision_id}:{page_index}:{view}"


# ------------------------------------------------------------- база: пакет Quantor → TENDER


class ObjectBaseRelease(_Strict):
    id: UUID
    number: int = Field(ge=1)
    released_at: datetime
    released_by: str
    comment: str


class ObjectBaseProject(_Strict):
    id: UUID
    name: str


class ObjectBaseEngine(_Strict):
    version: str
    cad_walls: str | None = None
    cad_mep: str | None = None


class ObjectBaseManifestView(_Strict):
    key: ViewKey
    dir: str
    revision_id: UUID
    document_id: UUID | None = None
    document_title: str
    page_index: int = Field(ge=0)
    view: int = Field(ge=0)
    sheet_label: str
    dxf_sha256: Sha256
    corps: str | None = None
    section: str | None = None
    floors: list[str]


class ObjectBaseManifest(_Strict):
    schema_name: Literal["quantor.object_base.v1"] = Field(alias="schema")
    release: ObjectBaseRelease
    project: ObjectBaseProject
    engine: ObjectBaseEngine
    units: Literal["mm"]
    frame: Literal["view_dxf_mm"]
    z_reference: Literal["finished_floor"]
    views: list[ObjectBaseManifestView]
    files: dict[str, Sha256]


class ObjectBaseFrame(_Strict):
    mm_per_pdf_point: float = Field(gt=0)
    origin_pt: Annotated[list[float], Field(min_length=2, max_length=2)]
    page_size_pt: Annotated[list[float], Field(min_length=2, max_length=2)]
    confirmed: bool


class ObjectBaseLevel(_Strict):
    floor_elevation_mm: int
    floor_height_mm: int
    slab_thickness_mm: int
    elevation_known: bool
    floor_height_known: bool
    slab_thickness_known: bool


class ObjectBasePlacement(_Strict):
    group_key: str
    group_label: str
    offset_mm: Point2
    alignment: Literal["reference", "axes", "none"]
    alignment_axes: list[str]


class ObjectBaseView(_Strict):
    schema_name: Literal["quantor.object_base.view.v1"] = Field(alias="schema")
    key: ViewKey
    frame: ObjectBaseFrame
    level: ObjectBaseLevel
    placement: ObjectBasePlacement
    bbox: Annotated[list[int], Field(min_length=4, max_length=4)] | None = None


class ObjectBaseAxis(_Strict):
    label: str
    orient: Literal["vertical", "horizontal"]
    pos_mm: int


class ObjectBaseAxes(_Strict):
    schema_name: Literal["quantor.object_base.axes.v1"] = Field(alias="schema")
    axes: list[ObjectBaseAxis]


class ObjectBaseZone(_Strict):
    id: UUID
    kind: Literal["room_apartment", "room_mop", "parking_space"]
    apartment_no: str | None = None
    room_mark: str | None = None
    name: str | None = None
    room_type: str | None = None
    area_m2: float
    points: Ring


class ObjectBaseZones(_Strict):
    schema_name: Literal["quantor.object_base.zones.v1"] = Field(alias="schema")
    zones: list[ObjectBaseZone]


class ObjectBaseConstruction(_Strict):
    id: str
    kind: str
    material: str | None = None
    thickness_mm: int | None = None
    shell: Ring
    holes: list[Ring]


class ObjectBaseOpening(_Strict):
    id: str
    kind: str
    host_id: str | None = None
    width_mm: int
    center: Point2
    direction: Point2 | None = None


class ObjectBaseSlab(_Strict):
    shell: Ring


class ObjectBaseConstructions(_Strict):
    schema_name: Literal["quantor.object_base.constructions.v1"] = Field(alias="schema")
    constructions: list[ObjectBaseConstruction]
    openings: list[ObjectBaseOpening]
    slab: ObjectBaseSlab | None = None


class ObjectBaseRiser(_Strict):
    system: str
    mark: str
    dn_mm: int | None = None
    role: str
    count: int
    shaft_id: str | None = None
    source: str | None = None
    note: str | None = None


class ObjectBaseRisers(_Strict):
    schema_name: Literal["quantor.object_base.risers.v1"] = Field(alias="schema")
    risers: list[ObjectBaseRiser]


class ObjectBaseBuildingFloor(_Strict):
    view_key: ViewKey
    label: str
    group_key: str
    base_z_mm: int
    floor_height_mm: int
    offset_mm: Point2
    alignment: Literal["reference", "axes", "none"]


class ObjectBaseBuilding(_Strict):
    schema_name: Literal["quantor.object_base.building.v1"] = Field(alias="schema")
    floors: list[ObjectBaseBuildingFloor]


# ------------------------------------------------------------- расчёт: пакет TENDER → Quantor


class CalcBaseRef(_Strict):
    release_id: UUID
    manifest_sha256: Sha256


class CalcRef(_Strict):
    discipline: CalcDiscipline
    system: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)


class CalcVersionInfo(_Strict):
    label: str = Field(min_length=1, max_length=64)
    message: str = Field(default="", max_length=4000)
    author: str = Field(min_length=1, max_length=200)
    created_at: datetime


class CalcProducer(_Strict):
    skill: str = Field(min_length=1, max_length=100)
    skill_ref: str = Field(min_length=1, max_length=100)
    tool: str = Field(min_length=1, max_length=100)


class CalcFit(_Strict):
    view_key: ViewKey
    method: Literal["axes_affine", "identity"]
    axes: list[str] = Field(default_factory=list, max_length=200)
    rms_mm: float = Field(ge=0)
    max_mm: float = Field(ge=0)


class CalcManifest(_Strict):
    schema_name: Literal["quantor.tender_calc.v1"] = Field(alias="schema")
    project_id: UUID
    base: CalcBaseRef
    calc: CalcRef
    version: CalcVersionInfo
    producer: CalcProducer
    fit: list[CalcFit]
    files: dict[str, Sha256]

    @model_validator(mode="after")
    def _system_matches_discipline(self) -> CalcManifest:
        if self.calc.system not in SYSTEMS_BY_DISCIPLINE[self.calc.discipline]:
            raise ValueError(
                f"calc.system: «{self.calc.system}» нет в списке раздела {self.calc.discipline}"
            )
        return self


PolylineKind = Literal["route", "jumper", "riser", "leadin", "cable", "tray", "duct"]
ElementType = Literal["fitting", "valve", "sleeve", "terminal", "equipment"]
# `T-<РАЗДЕЛ>-<СИСТЕМА>`: префикс отличает расчёт от трасс движка (`M-`).
LayerName = Annotated[
    str, StringConstraints(pattern=r"^T-[A-Z0-9_]+(-[A-Z0-9_]+)+$", max_length=64)
]


class CalcPolyline(_Strict):
    id: str = Field(min_length=1, max_length=128)
    system: str = Field(min_length=1, max_length=32)
    layer: LayerName
    kind: PolylineKind
    shape: Literal["round", "rect"] | None = None
    dn_mm: float | None = Field(default=None, ge=0)
    w_mm: float | None = Field(default=None, ge=0)
    h_mm: float | None = Field(default=None, ge=0)
    pts: Annotated[list[Point3], Field(min_length=2, max_length=MAX_POLYLINE_POINTS)]
    insulation_mm: float | None = Field(default=None, ge=0)
    slope: float | None = None
    mark: str | None = Field(default=None, max_length=64)
    apt: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=500)


class CalcElement(_Strict):
    id: str = Field(min_length=1, max_length=128)
    system: str = Field(min_length=1, max_length=32)
    type: ElementType
    subtype: str | None = Field(default=None, max_length=32)
    layer: LayerName
    pos: Point3
    axis: Point3 | None = None
    w_mm: float | None = Field(default=None, ge=0)
    length_mm: float | None = Field(default=None, ge=0)
    h_mm: float | None = Field(default=None, ge=0)
    dn_mm: float | None = Field(default=None, ge=0)
    mark: str | None = Field(default=None, max_length=64)
    apt: str | None = Field(default=None, max_length=32)


class CalcViewFile(_Strict):
    """Геометрия одного вида: надмножество `routes3d.v2` движка (портал рисует тем же кодом)."""

    schema_name: Literal["quantor.tender_calc.view.v1"] = Field(alias="schema")
    view_key: ViewKey
    dxf_sha256: Sha256
    floors: list[str] = Field(max_length=500)
    polylines: Annotated[list[CalcPolyline], Field(max_length=MAX_POLYLINES_PER_VIEW)]
    elements: Annotated[list[CalcElement], Field(max_length=MAX_ELEMENTS_PER_VIEW)]

    @model_validator(mode="after")
    def _unique_ids(self) -> CalcViewFile:
        seen: set[str] = set()
        for item_id in [p.id for p in self.polylines] + [e.id for e in self.elements]:
            if item_id in seen:
                raise ValueError(f"id «{item_id}» повторяется: id уникален внутри файла")
            seen.add(item_id)
        return self


CalcBasis = Literal["geometry", "schedule", "rule", "assumption"]
CalcUnit = Literal["м", "м2", "м3", "шт", "компл", "т", "кг", "точка"]


class CalcPerFloor(_Strict):
    floor: str = Field(max_length=64)
    qty: float


class CalcQuantityRow(_Strict):
    code: str = Field(min_length=1, max_length=64)
    group: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    unit: CalcUnit
    qty: float
    basis: CalcBasis
    per_floor: list[CalcPerFloor] = Field(default_factory=list, max_length=500)
    view_keys: list[ViewKey] = Field(default_factory=list, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class CalcQuantitiesFile(_Strict):
    schema_name: Literal["quantor.tender_calc.quantities.v1"] = Field(alias="schema")
    rows: Annotated[list[CalcQuantityRow], Field(max_length=MAX_QUANTITY_ROWS)]

    @model_validator(mode="after")
    def _unique_codes(self) -> CalcQuantitiesFile:
        seen: set[str] = set()
        for row in self.rows:
            if row.code in seen:
                raise ValueError(
                    f"code «{row.code}» повторяется: строка объёмов определяется кодом"
                )
            seen.add(row.code)
        return self


class CalcQuestionRow(_Strict):
    text: str = Field(min_length=1, max_length=2000)
    ref: str | None = Field(default=None, max_length=200)
    ids: list[str] = Field(default_factory=list, max_length=1000)


class CalcQuestionsFile(_Strict):
    schema_name: Literal["quantor.tender_calc.questions.v1"] = Field(alias="schema")
    rows: Annotated[list[CalcQuestionRow], Field(max_length=MAX_QUESTION_ROWS)]


# Все файлы пакетов для выгрузки JSON Schema: идентификатор схемы -> модель.
PACKAGE_MODELS: Final[dict[str, type[BaseModel]]] = {
    BASE_SCHEMA: ObjectBaseManifest,
    BASE_VIEW_SCHEMA: ObjectBaseView,
    BASE_AXES_SCHEMA: ObjectBaseAxes,
    BASE_ZONES_SCHEMA: ObjectBaseZones,
    BASE_CONSTRUCTIONS_SCHEMA: ObjectBaseConstructions,
    BASE_RISERS_SCHEMA: ObjectBaseRisers,
    BASE_BUILDING_SCHEMA: ObjectBaseBuilding,
    CALC_SCHEMA: CalcManifest,
    CALC_VIEW_SCHEMA: CalcViewFile,
    CALC_QUANTITIES_SCHEMA: CalcQuantitiesFile,
    CALC_QUESTIONS_SCHEMA: CalcQuestionsFile,
}


# --------------------------------------------------------------------------- ответы API


class TenderViolationRead(BaseModel):
    """Нарушение пакета: файл (и путь внутри него), код ошибки и пояснение."""

    path: str
    code: str
    message: str


class TenderWarningRead(BaseModel):
    code: str
    message: str
    view_key: str | None = None


class TenderBaseViewRead(BaseModel):
    """Вид в выпуске базы."""

    key: str
    dir: str
    revision_id: UUID
    page_index: int
    view: int
    job_id: UUID
    dxf_sha256: str
    document_title: str
    label: str
    corps: str | None
    section: str | None
    floors: list[str]


class TenderBaseCandidateRead(BaseModel):
    """Этаж здания, который можно включить в выпуск базы."""

    view_key: str
    dir: str
    revision_id: UUID
    document_id: UUID | None
    document_title: str
    page_index: int
    view: int
    label: str
    corps: str | None
    section: str | None
    group_key: str
    group_label: str
    floors: list[str]
    base_z_mm: int
    offset_mm: tuple[float, float]
    alignment: Literal["reference", "axes", "none"]
    dxf_sha256: str | None
    # Вид готов к выпуску: кадр подтверждён, DXF и конструкции есть.
    ready: bool
    problems: list[str]


class TenderBaseCandidatesRead(BaseModel):
    candidates: list[TenderBaseCandidateRead]
    warnings: list[str]


class TenderBaseReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_keys: list[ViewKey] | None = Field(
        default=None,
        max_length=MAX_BASE_VIEWS,
        description="Виды выпуска; не заданы — все готовые виды проекта",
    )
    include_dxf: bool = Field(default=False, description="Положить в пакет DXF каждого вида")
    comment: str = Field(default="", max_length=1000)


class TenderBaseReleaseRead(BaseModel):
    id: UUID
    project_id: UUID
    number: int
    comment: str
    released_by_name: str | None
    released_at: datetime
    include_dxf: bool
    views: list[TenderBaseViewRead]
    package_sha256: str
    manifest_sha256: str
    size_bytes: int
    revoked_at: datetime | None
    revoked_by_name: str | None


class TenderViewInfoRead(BaseModel):
    """Вид в версии расчёта: адрес, этажи, объём геометрии и признак устаревшей базы."""

    view_key: str
    revision_id: UUID
    page_index: int
    view: int
    floors: list[str]
    dxf_sha256: str
    polylines: int
    elements: int
    base_stale: bool


class TenderCalcVersionSummaryRead(BaseModel):
    id: UUID
    calc_id: UUID
    number: int
    label: str
    message: str
    author: str
    uploaded_by_name: str | None
    uploaded_at: datetime
    status: VersionStatus
    base_release_id: UUID
    base_release_number: int
    quantity_rows: int
    question_count: int
    warning_count: int
    view_count: int


class TenderCalcRead(BaseModel):
    """Репозиторий расчёта и его последняя действующая версия (`null` — действующей нет)."""

    id: UUID
    project_id: UUID
    discipline: CalcDiscipline
    system: str
    title: str
    created_at: datetime
    version_count: int
    active_version: TenderCalcVersionSummaryRead | None


class TenderCalcsRead(BaseModel):
    calcs: list[TenderCalcRead]


class TenderCalcVersionsRead(BaseModel):
    versions: list[TenderCalcVersionSummaryRead]


class TenderQuantityRowRead(BaseModel):
    code: str
    group: str | None
    name: str
    unit: str
    qty: float
    basis: CalcBasis
    per_floor: list[CalcPerFloor]
    view_keys: list[str]
    note: str | None


class TenderQuestionRead(BaseModel):
    text: str
    ref: str | None
    ids: list[str]


class TenderQuantityDiffRead(BaseModel):
    """Разница объёмов версии с прошлой по `code`."""

    code: str
    name: str
    unit: str
    qty_prev: float | None
    qty: float | None
    delta: float
    status: DiffStatus


class TenderCalcVersionRead(TenderCalcVersionSummaryRead):
    discipline: CalcDiscipline
    system: str
    title: str
    producer: dict[str, str]
    fit: list[dict[str, Any]]
    quantities: list[TenderQuantityRowRead]
    questions: list[TenderQuestionRead]
    views: list[TenderViewInfoRead]
    warnings: list[TenderWarningRead]
    package_sha256: str
    prev_version_id: UUID | None
    diff: list[TenderQuantityDiffRead]


class TenderCalcViewRead(BaseModel):
    """Геометрия расчёта на одном виде (файл версии из хранилища)."""

    version_id: UUID
    view_key: str
    floors: list[str]
    polylines: list[CalcPolyline]
    elements: list[CalcElement]
    base_stale: bool


class TenderViewLayerRead(BaseModel):
    """Слой «Расчёты»: действующая версия расчёта на заданном виде."""

    version_id: UUID
    calc_id: UUID
    discipline: CalcDiscipline
    system: str
    title: str
    number: int
    label: str
    floors: list[str]
    polylines: list[CalcPolyline]
    elements: list[CalcElement]
    base_stale: bool


class TenderViewLayersRead(BaseModel):
    layers: list[TenderViewLayerRead]


class TenderBuildingLayerRead(BaseModel):
    version_id: UUID
    calc_id: UUID
    discipline: CalcDiscipline
    system: str
    title: str
    number: int
    label: str
    view_keys: list[str]


class TenderBuildingLayersRead(BaseModel):
    layers: list[TenderBuildingLayerRead]


# --------------------------------------------------------------------------- токены
#
# Имена типов без «api token»: контракт и клиент не должны содержать таких слов (тест 9
# матрицы безопасности); смысл — персональный токен пользователя.


# Имена типов без слов «api token»: контракт и клиент их не содержат (тест 9 матрицы
# безопасности), смысл тот же - персональный токен пользователя.
class PersonalTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class PersonalTokenRead(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    active: bool


class PersonalTokenCreated(PersonalTokenRead):
    """Ответ создания: полный токен показывается один раз, в базе его нет."""

    token: str
