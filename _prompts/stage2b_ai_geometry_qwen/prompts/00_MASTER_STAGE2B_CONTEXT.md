# PROMPT 00 — Master context Stage 2B

Ты работаешь в существующем Quantor после закрытого Stage 2A.

## Прочитай полностью до любых изменений

- корневой `CLAUDE.md`;
- все `docs/adr/*`;
- `docs/stage2a/16-acceptance.md`;
- `docs/stage2a/HANDOFF_TO_STAGE2B.md`;
- `apps/api/app/models/takeoff.py`;
- `apps/api/app/services/takeoff.py` и `quantity.py`;
- `apps/api/app/contracts/models.py` и `core/model_registry.py`;
- `apps/api/app/models/job.py` и worker/job services;
- весь viewer (`DrawingViewport`, backend, camera, overlays, tool machine);
- feature flags;
- все reference-файлы `_prompts/stage2b_ai_geometry/reference/`.

## Repository identity gate

Ожидается минимум:

```text
apps/api/app/
apps/web/src/
apps/admin/src/
packages/api-client/
benchmarks/
docs/stage2a/
CLAUDE.md
```

Если это другой repo/snapshot — STOP без изменений.

## Цель Stage 2B

Проверить и затем, только при успехе benchmark, интегрировать lightweight AI geometry:

```text
PlanSwift GT → competing AI geometry branches → vector → reviewed AI Measurement → Quantity

Основные ветки эксперимента:

```text
A. small semantic/centerline segmentation
B. SAM2 / MobileSAM
C. Qwen3-VL + Unsloth SFT → localization / structured geometry
D. Qwen3-VL → SAM → precise mask
```
```

Пилоты: slab area with holes и masonry centerline.

## Жёсткие инварианты

1. AI **не выдаёт конечную физическую величину**.
2. Quantity считает только существующий deterministic engine после canonical geometry/scale.
3. Автоматическое определение масштаба и чтение размерных линий по-прежнему запрещены.
4. Prediction до human accept не входит в working Takeoff total.
5. `Region != PredictionCandidate != Measurement != Quantity`.
6. Raw masks/weights/datasets — object/private storage, не PostgreSQL blob/base64.
7. HTTP manual endpoint не может подделать `source=ai`.
8. Model/training provenance обязателен: weights hash + input hash + config/version.
9. Client PlanSwift data не уходит во внешние API без отдельного явного решения владельца.
10. Ultralytics dependency/model не добавлять без явного enterprise-license approval.
11. Training/inference torch stack не добавлять в `apps/api` process.
12. Viewer coordinate truth не зависит от raster resolution.
13. No Revit/IFC generation, no BIM parsing, no volume/mass/cost, no ProjectGraph.
14. Не менять test split по результатам модели.
15. Не начинать prompts 19+ если Prompt 18 не прошёл POC gates и владелец не подтвердил promotion.
16. Qwen/VLM не имеет права выдавать конечные метры/м² как source of truth; только localization/geometry candidates.
17. На validation/test нельзя строить crop/bbox/SAM prompt из PlanSwift GT.
18. Qwen training выполняется через отдельный ML environment; Unsloth Studio (AGPL) не встраивать в Quantor runtime.
19. Для Qwen сначала измерить BF16/FP16 baseline там, где позволяет GPU; 4-bit/QLoRA не считать эквивалентом без QTO benchmark.
20. Не commit/push/merge без команды пользователя.

## Этот промт ничего не реализует

Выведи:

- repository identity;
- фактическую head migration;
- текущие тестовые команды/счётчики;
- расхождения между `16-acceptance` и `HANDOFF_TO_STAGE2B`;
- фактическое состояние `takeoff.manual`, `takeoff.ai`, `models.gateway`;
- список current viewer bottlenecks;
- список конфликтов текущей модели Polygon с PlanSwift holes;
- что из reference-файлов уже реализовано, а что нет.

Создай `docs/stage2b/00-entry-audit.md`. Никакого кода.

STOP. Не переходи к Prompt 01.
