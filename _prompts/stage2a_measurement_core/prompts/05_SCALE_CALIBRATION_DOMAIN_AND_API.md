# PROMPT 05 — Manual Scale Calibration: domain, persistence, API

Заменить устаревший `ScaleCalibration.units_per_normalized` рабочей моделью.

## Перед кодом

Создай ADR scale calibration. Зафиксируй:

- internal physical canonical unit = mm;
- factor = `mm_per_pdf_point`;
- calibration immutable/versioned;
- one sheet may have multiple scales;
- Measurement stores explicit calibration reference;
- changing default scale never silently rewrites old Measurements;
- Stage 2A source only `manual`.

## Модель

Реализуй эквивалент reference/DATA_MODEL_DRAFT.md. Обязательно хранить исходное доказательство:

```text
A_norm
B_norm
known_distance_mm
page_distance_pt
mm_per_pt
page_geometry/fingerprint provenance
created_by
```

Поддержать `scope_kind` как минимум `sheet` и schema-ready `region`. Если полноценный local-scale
UI слишком рано — data model всё равно не должен запрещать его.

Нужен понятный default/active selection для новых Measurements. Старые calibrations не удалять
каскадом так, чтобы существующий Measurement потерял доказательство.

## API

Нужны безопасные операции:

- list calibrations sheet;
- create manual calibration from two normalized points + known distance + input unit;
- set default / supersede с явной семантикой;
- read calibration;
- при необходимости verify/revoke, но не создавать бессмысленный CRUD.

Backend сам вычисляет `page_distance_pt` и `mm_per_pt`; клиент не присылает готовый коэффициент.

## Permissions

Добавь domain permissions, не role checks. Рекомендуемая гранулярность:

```text
takeoff.read
takeoff.edit
takeoff.verify
```

или эквивалент. Engineer редактирует; reviewer может verify; viewer только read.
Объясни mapping.

## Validation

- zero/near-zero segment rejected;
- nonfinite rejected;
- known distance > 0;
- units whitelist (`mm`, `cm`, `m`) → canonical mm;
- sheet/page geometry ownership;
- cross-workspace 404;
- audit только на завершённую persist operation, не pointer move.

## Tests

Обязательно horizontal, vertical, diagonal, unit conversion, immutability, multiple scales,
permission matrix, tenant isolation.

`takeoff.manual` всё ещё OFF.

STOP.
