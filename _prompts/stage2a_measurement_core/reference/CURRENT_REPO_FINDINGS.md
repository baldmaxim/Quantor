# Актуальные наблюдения перед Stage 2A

Основание: архив Quantor после Stage 1.5, переданный 2026-09-08. Два последних ZIP
`Quantor-main(1).zip` и `Quantor-main(2).zip` были байт-в-байт одинаковы.

## Подтверждено

- `apps/api`, `apps/web`, `apps/admin`, `packages/api-client` существуют.
- OIDC/RBAC/workspaces/control plane/worker уже реализованы.
- `Region ≠ Measurement ≠ Quantity` закреплено ADR-0008.
- будущие типы в `apps/api/app/contracts/quantities.py` ещё не превращены в таблицы.
- viewer использует `pdf.js` + отдельный Canvas2D recognition overlay.
- нормализованные legacy-координаты относятся к **уже отображённой/повёрнутой странице**.
- `width_px/height_px` в `Sheet` — размер растра распознавалки, не физическая геометрия PDF.

## Что нельзя перенести в Stage 2 без исправления

### 1. Старый ScaleCalibration

В контракте есть:

```python
units_per_normalized: float
```

Один коэффициент для нормализованных координат математически неверен на прямоугольной
странице. `0.1` по X и `0.1` по Y — разные расстояния, если ширина и высота листа различны.
Этот контракт должен быть superseded **до создания таблиц**.

### 2. Canonical PDF geometry отсутствует на сервере

Frontend знает размер страницы через pdf.js, но серверный QTO не может зависеть от браузера.
Нужно хранить каноническую геометрию страницы в PDF display points/top-left coordinate space.

### 3. Job без project_id

Текущий обычный jobs-query допускает условие `Job.project_id IS NULL`. До появления новых
системных/геометрических jobs нужен явный scope, чтобы system job не стал виден любому workspace.

### 4. ADR-0004 расходится с кодом

ADR говорит WebGL, рабочий `overlay.ts` осознанно использует Canvas2D. На Stage 2A не надо
переписывать это ради документации. ADR нужно уточнить: Canvas2D остаётся до измеренного
performance threshold.

### 5. CLAUDE.md всё ещё Stage 1

Корневой файл запрещает scale/length/area/QTO. Prompt 01 должен официально переключить
границы на Stage 2A до реализации.

## Что проверить, а не предполагать

- наличие последнего regression-теста viewer на отсутствие двух одновременных render по одному canvas;
- свежий полный test-run после Stage 1.5 на живой БД;
- platform_admin без membership: system-admin endpoints не должны требовать случайный workspace;
- актуальность `HANDOFF_TO_STAGE2.md` относительно фактического live viewer PASS.

Если архив в рабочем репозитории уже новее и пункт исправлен — не переделывать второй раз,
а показать доказательство тестом/кодом.
