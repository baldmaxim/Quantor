# PROMPT 03 — Реализация PDF geometry extraction

Реализуй принятое в Prompt 02.

## Требования

### Worker job

Добавь реальный `JobType.PDF_GEOMETRY_EXTRACT` и handler в существующий worker registry.
Не создавать второй механизм очередей.

Поток:

```text
DocumentRevision(PDF)
→ stream object to bounded temp file
→ PDF parser
→ validate all pages
→ transaction
→ create/enrich Sheet
→ persist PageGeometry
→ succeeded
```

### Direct PDF

После загрузки обычного PDF geometry job должен ставиться автоматически. Это не AI и не
recognition. Если листов ещё нет — создать их из PDF.

### Legacy import

После того как legacy importer создаёт PDF DocumentRevision/Sheets, geometry extraction
должна быть запланирована для этого PDF revision. Не блокировать 1.5-секундный import
долгим синхронным parsing.

### Geometry consistency

Для legacy sheet:

- `page_index` должен совпасть;
- число страниц совпасть;
- legacy `rotation` сохранить как source metadata, но не применять к normalized geometry второй раз;
- `width_px/height_px` оставить нетронутыми;
- mismatch → понятный job failure, без частичного `geometry_ready`.

### Storage/memory

- binary остаётся ObjectStorage;
- временный файл удаляется даже при exception;
- stream chunks, no base64;
- лимиты/ошибки malformed/encrypted PDF;
- secret/PDF content не логировать.

## API

Добавь read endpoint geometry текущего sheet через существующую authorization chain.
Generated client regenerate, ручных TS DTO нет.

## Tests

Минимум:

- 1-page portrait;
- landscape;
- rotated PDF;
- multi-page;
- malformed;
- idempotent repeat;
- legacy enrich;
- page mismatch rollback;
- direct upload creates sheets;
- cross-workspace 404;
- worker claim/lease/retry не сломаны.

Если live fixture доступен — извлеки geometry 77 страниц и зафиксируй измеренные результаты,
но feature `takeoff.manual` пока не включай.

STOP с отчётом и test counts.
