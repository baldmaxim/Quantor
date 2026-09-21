# PROMPT 01 — Raw PDF Workspace (рабочая область для обычного PDF)

**Модель:** Opus 5  
**Режим мышления:** высокий  
**Цель:** обычный PDF с готовой геометрией должен открываться в существующем workspace без обязательного распознанного ZIP.

Это самый важный быстрый продуктовый фикс.

## 1. Фактическая проблема

Сейчас обычный PDF:

- хранится;
- получает `PageGeometry`;
- после job `pdf_geometry_extract` может иметь `geometry_status=ready`;
- при этом `processing_status` остаётся `unprocessed`, потому что legacy recognition (старое распознавание) не запускалось.

Карточка проекта в `apps/web/src/app/(portal)/projects/[projectId]/page.tsx` считает ревизию открываемой только при `processing_status === 'ready'`.

Это неверный продуктовый гейт для viewer (просмотрщика).

## 2. Требуемое поведение

После этого промта:

### Обычный PDF

Если:

- тип документа поддерживает PDF viewer;
- source PDF доступен;
- `geometry_status == ready`;
- есть sheets/PageGeometry;

то пользователь может открыть workspace независимо от recognition status (статуса распознавания).

### Распознанный legacy package

Существующий сценарий продолжает работать без регрессий.

### Recognition tab (вкладка распознавания)

Если regions (областей распознавания) нет:

- viewer всё равно работает;
- вкладка показывает честный empty state (пустое состояние) вроде «Для этого PDF нет импортированной разметки распознавания»;
- не показывать ошибку и не требовать ZIP.

### Geometry failure

Если `geometry_status=failed/pending/extracting`, открыть лист как готовый нельзя. UI должен объяснять причину/состояние.

## 3. Не ограничивайся первой найденной ревизией

Проверь текущую логику:

```text
documents.items.find(isRenderable)
→ useDocumentRevisions(только одного документа)
→ find(processing_status === ready)
```

Она может выбрать первый PDF и проигнорировать другой действительно готовый документ.

Исправь выбор так, чтобы:

- каждый документ/ревизия имели понятный статус открываемости;
- top-level кнопка (верхняя кнопка) не зависела от случайного порядка списка;
- если готово несколько PDF, результат детерминирован (например, последняя готовая ревизия по явному правилу);
- по возможности у строки документа есть явное действие «Открыть», чтобы пользователь сам выбирал документ.

Не делай большой redesign (переработку интерфейса).

## 4. Server-side guard (серверная защита)

Проверь API выдачи sheets/content/page geometry. Если там есть скрытое условие `processing_status=ready`, исправь его минимально: viewer должен зависеть от готовности PDF geometry, а recognition API — от наличия recognition data.

Не ослабляй workspace/project permissions (права доступа).

## 5. Тесты

Добавь/обнови тесты минимум на:

1. raw PDF: processing=`unprocessed`, geometry=`ready` → workspace openable;
2. raw PDF: geometry=`pending` → не openable;
3. raw PDF: geometry=`failed` → не openable + понятный статус;
4. recognized package → поведение осталось рабочим;
5. проект с несколькими PDF: готовый документ не теряется из-за порядка;
6. raw PDF без regions → viewer рендерится, recognition empty state;
7. доступ по чужому workspace/project не расширился.

Если есть Playwright/E2E (сквозной браузерный тест) подходящего уровня — добавь короткий сценарий открытия обычного PDF.

## 6. UX (интерфейс)

Убери устаревший текст:

> «Нужен распознанный PDF: загрузите пакет…»

Новый смысл:

- PDF готовится к просмотру по геометрии;
- распознавание — отдельный необязательный слой.

## 7. Что запрещено

- не менять base recognition;
- не добавлять raster/OCR;
- не трогать MEP MOCK fixtures;
- не начинать MEP editor;
- не менять Quantity Engine.

## 8. Проверки

Запусти минимум:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm api-client:check
```

Если полный тест слишком дорог из-за известной среды, сначала релевантные, затем максимально полный доступный набор и честный отчёт.

## 9. Review ZIP

Создай `review/QUANTOR_FASTSTART_P01_REVIEW.zip`.

В отчёте покажи один конкретный путь:

`upload raw PDF → geometry ready → project card → workspace → лист виден → regions empty`.

После отчёта остановись. Не выполняй PROMPT 02.
