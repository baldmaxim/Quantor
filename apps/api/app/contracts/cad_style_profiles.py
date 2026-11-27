"""Контракты профиля оформления проектировщика (ADR-0049, решения 1, 2, 5, 6).

Тело профиля - ровно те поля, которые проверяет движок (`material_profiles.check_profile_fields`):
лишние поля, пропуски и числа вне границ отклоняются; умолчание API - только
`concrete_hatch_signatures` (`[]`). Заголовок
`title` в тело не входит: он у версии. Объект `style` для движка собирает сервер.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool

from app.domain import JobStatus

STYLE_SCHEMA: Final = "cad_engine.style_profile.v1"
PROFILE_KEY_PATTERN: Final = r"^[A-Za-z0-9._-]{1,64}$"
# Пределы ниже - ограничения API против опечаток и порчи данных, а не контракт движка: движок
# проверяет только диапазон серых [0, 1], знак толщины и состав полей.
MAX_GRAYS: Final = 16
MAX_SHAFT_LABELS: Final = 50
MAX_HATCH_SIGNATURES: Final = 8
MAX_SHAFT_LABEL_LENGTH: Final = 32
MAX_TITLE_LENGTH: Final = 200
MAX_SAMPLES: Final = 200
MAX_PEN_WIDTH: Final = 5
MAX_INT32: Final = 2**31 - 1
# Верхние границы masonry_acceptance (ограничение API, не контракт движка). Они же держат числа в
# диапазоне, где PostgreSQL не меняет запись в JSONB (например, 1e16 -> 10000000000000000), иначе
# sha256 разошёлся бы с `style` из базы.
MAX_ACCEPTANCE_MM2: Final = 1e9
MAX_ACCEPTANCE_MM: Final = 1e6
MAX_ACCEPTANCE_COUNT: Final = 1e4
MAX_ACCEPTANCE_RATIO: Final = 1e6


def _reject_negative_zero(value: float) -> float:
    # PostgreSQL хранит -0.0 как 0.0: хеш и тело разошлись бы.
    if value == 0 and math.copysign(1.0, value) < 0:
        raise ValueError("отрицательный ноль не допускается")
    return value


def _reject_unstorable_text(value: str) -> str:
    # \x00 и одиночные суррогаты PostgreSQL не принимает: без проверки это 503 вместо 422.
    if "\x00" in value:
        raise ValueError("символ NUL не допускается")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("недопустимые символы") from error
    return value


# strict: ни `true`, ни строка "0.5" числом не становятся; целое для float допустимо.
Gray = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False, strict=True),
    AfterValidator(_reject_negative_zero),
]
GrayList = Annotated[list[Gray], Field(max_length=MAX_GRAYS)]


Text = Annotated[str, AfterValidator(_reject_unstorable_text)]

CadStyleSampleClass = Literal[
    "monolith", "shaft", "masonry", "door", "insulation", "dimension_tick"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CadStyleMasonryAcceptance(_Strict):
    min_area_mm2: Annotated[
        float,
        Field(ge=0, le=MAX_ACCEPTANCE_MM2, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    min_effective_width_mm: Annotated[
        float,
        Field(ge=0, le=MAX_ACCEPTANCE_MM, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    min_hatch_lines: Annotated[
        float,
        Field(ge=0, le=MAX_ACCEPTANCE_COUNT, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    min_hatch_density: Annotated[
        float,
        Field(ge=0, le=MAX_ACCEPTANCE_RATIO, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    min_boundary_fraction: Annotated[
        float,
        Field(ge=0, le=MAX_ACCEPTANCE_RATIO, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    max_effective_width_mm: (
        Annotated[
            float,
            Field(ge=0, le=MAX_ACCEPTANCE_MM, allow_inf_nan=False, strict=True),
            AfterValidator(_reject_negative_zero),
        ]
        | None
    )


Unit = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False, strict=True),
    AfterValidator(_reject_negative_zero),
]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
HatchAngle = Annotated[
    float,
    Field(ge=0, lt=180, allow_inf_nan=False, strict=True),
    AfterValidator(_reject_negative_zero),
]


class CadStyleHatchSignature(_Strict):
    """Подпись штриховки монолита: цвет RGB (0..1), перо, угол и шаг в pt."""

    color: Annotated[list[Unit], Field(min_length=3, max_length=3)]
    pen: Positive
    angle_deg: HatchAngle
    pitch_pt: Positive


class CadStyleProfileBody(_Strict):
    monolith_fill_gray: GrayList
    shaft_fill_gray: GrayList
    masonry_hatch_gray: GrayList
    concrete_hatch_gray: GrayList
    # Умолчание `[]` только на входе API: в тело для движка поле попадает всегда (model_dump).
    concrete_hatch_signatures: Annotated[
        list[CadStyleHatchSignature], Field(max_length=MAX_HATCH_SIGNATURES)
    ] = Field(default_factory=list)
    alternate_boundary_gray: GrayList
    # Верхний предел 5 - ограничение API против опечаток, движок требует только > 0.
    door_pen_max_width: Annotated[
        float,
        Field(gt=0, le=MAX_PEN_WIDTH, allow_inf_nan=False, strict=True),
    ]
    door_stitch_segments: StrictBool
    door_grid_tolerance: StrictBool
    masonry_acceptance: CadStyleMasonryAcceptance
    shaft_labels: Annotated[
        list[Annotated[Text, Field(max_length=MAX_SHAFT_LABEL_LENGTH)]],
        Field(max_length=MAX_SHAFT_LABELS),
    ]


class CadStyleSample(BaseModel):
    """Подпись человека на странице: класс, положение (доли страницы) и «это не он»."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sample_class: Annotated[CadStyleSampleClass, Field(alias="class")]
    x: Annotated[
        float,
        Field(ge=0, le=1, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    y: Annotated[
        float,
        Field(ge=0, le=1, allow_inf_nan=False, strict=True),
        AfterValidator(_reject_negative_zero),
    ]
    negative: StrictBool


class CadStyleSamplesSource(_Strict):
    """Профиль снят по подписям человека: ревизия, лист и подписи обязательны.

    `mm_per_pt` - обязательный ключ: масштаб листа может быть неизвестен, и это честный `null`,
    а не пропуск. `preview_job_id` клиент не передаёт (лишнее поле - 422): при принятии
    предпросмотра его ставит только сервер.
    """

    kind: Literal["samples"]
    revision_id: UUID
    page_index: Annotated[int, Field(ge=0, le=MAX_INT32, strict=True)]
    samples: Annotated[list[CadStyleSample], Field(min_length=1, max_length=MAX_SAMPLES)]
    mm_per_pt: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)] | None


class CadStyleManualSource(_Strict):
    """Профиль введён вручную: полей снятия по образцам нет (лишнее поле - 422)."""

    kind: Literal["manual"]


CadStyleSource = Annotated[
    CadStyleSamplesSource | CadStyleManualSource, Field(discriminator="kind")
]


class CadStyleVersionWrite(_Strict):
    title: Annotated[Text, Field(max_length=MAX_TITLE_LENGTH)] | None = None
    profile: CadStyleProfileBody
    source: CadStyleSource
    # Оптимистическая блокировка: None - профиля ещё нет, иначе номер текущей версии.
    expected_current_version: Annotated[int, Field(ge=1, le=MAX_INT32, strict=True)] | None


class CadStyleVersionRead(BaseModel):
    version: int
    title: str | None
    style: dict[str, object]
    sha256: str
    source: dict[str, object]
    created_at: datetime
    created_by: UUID | None


class CadStyleVersionBrief(BaseModel):
    version: int
    title: str | None
    created_at: datetime


class CadStyleProfileRead(BaseModel):
    id: UUID
    document_id: UUID
    profile_key: str
    current: CadStyleVersionRead
    versions: list[CadStyleVersionBrief]


# --- предпросмотр по образцам (ADR-0049, решения 3-7) ---

# calibration - калибровка листа человеком; cad_auto - масштаб последнего успешного преобразования
# листа по размерным цепочкам (`dimension_checks_passed`); none - масштаба нет, площади не
# считаются.
CadStyleScaleSource = Literal["calibration", "cad_auto", "none"]
# profile_out_of_limits - подпись снята, но тело профиля не проходит строгий контракт API
# (например, перо шире предела или слишком много серых): предпросмотр отдаётся, профиля нет.
CadStylePreviewStatus = Literal["profile", "no_signature", "profile_out_of_limits"]


class CadStylePreviewCreate(_Strict):
    revision_id: UUID
    page_index: Annotated[int, Field(ge=0, le=MAX_INT32, strict=True)]
    samples: Annotated[list[CadStyleSample], Field(min_length=1, max_length=MAX_SAMPLES)]


class CadStylePreviewCreated(BaseModel):
    job_id: UUID


class CadStylePreviewResult(BaseModel):
    """Итог исполнителя CAD: что нашёл профиль на листе. Профиль - кандидат до принятия."""

    result_status: CadStylePreviewStatus
    # Тело профиля (поля движка без обёртки `style`); при `no_signature` и
    # `profile_out_of_limits` - null.
    profile: dict[str, object] | None
    preview: dict[str, object]
    base_version: int | None
    engine_version: str | None
    mm_per_pt: float | None
    scale_source: CadStyleScaleSource
    revision_id: UUID
    page_index: int
    # Только при `profile_out_of_limits`: поля и правила, которые не прошли (без входных значений).
    reasons: list[str] = Field(default_factory=list)


class CadStylePreviewRead(BaseModel):
    job_id: UUID
    status: JobStatus
    error_code: str | None
    error_message: str | None
    result: CadStylePreviewResult | None


class CadStyleVersionFromPreview(_Strict):
    job_id: UUID
    title: Annotated[Text, Field(max_length=MAX_TITLE_LENGTH)] | None = None
    # Как в `CadStyleVersionWrite`: None - профиля ещё нет, иначе номер текущей версии.
    expected_current_version: Annotated[int, Field(ge=1, le=MAX_INT32, strict=True)] | None
