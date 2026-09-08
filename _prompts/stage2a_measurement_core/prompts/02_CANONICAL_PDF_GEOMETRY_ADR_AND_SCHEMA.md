# PROMPT 02 — Canonical PDF Page Geometry: ADR + schema design

Пока не делай UI measurement. Цель — спроектировать единственный серверный источник
геометрии страницы.

## Прочитай

- ADR-0003, 0004, 0007, 0008;
- importer legacy-v1;
- `Sheet`, `DocumentRevision`;
- pdf.js backend и `usePageGeometry`;
- reference/COORDINATE_AND_SCALE_INVARIANTS.md.

## Архитектурное решение

Создай ADR с явным определением пространства:

```text
pdf_display_points_top_left
```

Для каждой страницы должны быть доступны минимум:

- displayed width/height in PDF points;
- PDF rotation/provenance;
- MediaBox/CropBox (для диагностики/provenance, не как shortcut измерения);
- parser name/version;
- source revision SHA-256;
- geometry fingerprint;
- timestamp/status.

Выбери `PageGeometry` 1:1 с Sheet или эквивалент. Не забивай эти данные в legacy
`width_px/height_px`.

## Критические случаи

1. direct PDF upload без recognition package: geometry extraction должна уметь создать Sheet rows;
2. legacy package: существующие Sheet rows должны быть обогащены, а не продублированы;
3. page-count mismatch: никакой частично доверенной геометрии;
4. rotation: сравнивать фактическую display geometry backend parser с pdf.js на fixture;
5. повторный job: идемпотентность по revision SHA/parser version;
6. PDF большой: не загружать 500 МБ в RAM целиком.

## Dependency

Разрешается добавить PyMuPDF как серверный PDF geometry parser, если после оценки это
лучший вариант. Закрепить точную версию. Не добавлять внешние SaaS/CLI без необходимости.

## Результат промта

- ADR;
- schema/migration design;
- API contract design (`GET /sheets/{id}/geometry` или обоснованная альтернатива);
- job design `pdf_geometry_extract`;
- error codes/statuses;
- test matrix.

На этом промте можно создать migration/model/schemas, но **не реализовывать parser handler**,
если это смешает review архитектуры и реализацию. Предпочтительно закончить schema+ADR и STOP.

STOP.
