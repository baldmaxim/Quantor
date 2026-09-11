# Актуальные находки по Quantor-main(3).zip

Срез проверен перед созданием Stage 2B.

## Подтверждено в коде

- `apps/api` / `apps/web` / `apps/admin` / `packages/api-client` существуют.
- Head schema Stage 2A в документации: `0010_takeoff_domain`.
- `PageGeometry`, `ScaleCalibration`, `TakeoffItem`, `Measurement` уже реализованы.
- `MeasurementSource = manual | ai | imported` уже объявлен, но HTTP-сервис ручного обмера
  не позволяет подделать `source=ai` — это правильно.
- Quantity Engine детерминированный: `count.v1`, `length.v1`, `area.v1`.
- `jobs.workspace_id` уже исправляет прежнюю дыру system jobs.
- Viewer использует четыре full-page Canvas2D слоя: PDF, regions, scale, measurements.
- Hit-test Measurement пока линейный.
- `takeoff.manual`, `takeoff.ai`, `models.gateway` остаются Stage-2 flags с default=false и
  `admin_editable=false`.
- model registry/provider-neutral contracts существуют, runtime inference не реализован.
- `CLAUDE.md` всё ещё описывает Stage 2A и запрещает runtime AI.

## Документация требует синхронизации

`docs/stage2a/16-acceptance.md` содержит позднее обновление `PASS 15 / FAIL 0`, но
`HANDOFF_TO_STAGE2B.md` в начале всё ещё говорит, что Stage 2A не закрыт, а ниже содержит
устаревшие PARTIAL-формулировки. Prompt 01 должен привести документы к одному факту, не
подменяя измеренные значения.

## Известные технические долги, важные именно для Stage 2B

1. Full-page canvases дают очень высокий расход памяти на A1 при ~266% и повышенном DPR.
2. Hit-test перебирает все фигуры; AI может создать тысячи кандидатов.
3. Self-intersecting polygon («бантик») не имеет выбранной политики.
4. Текущий polygon хранит только один ring; PlanSwift slab ground truth требует holes.
5. Server-side raster renderer для model input отсутствует: pypdf читает геометрию, но не
   является raster engine.
6. Measurement не хранит происхождение конкретной модели/веса/маски.
7. Prediction до human acceptance нельзя молча включать в рабочие totals.

## Решение владельца

- `takeoff.manual`: сделать готовым, но default OFF; разрешить workspace override и включать
  только для pilot workspace через Admin после live-pan проверки.
- AI не должен считать величину. Модель строит маску/геометрию, Quantor считает существующим
  Measurement/Quantity Core.
