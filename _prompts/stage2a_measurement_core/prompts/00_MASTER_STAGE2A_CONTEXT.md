# PROMPT 00 — Master context Stage 2A

Ты работаешь в существующем Quantor после закрытого Stage 1.5.

## Сначала прочитай полностью

- корневой `CLAUDE.md`;
- все `docs/adr/*`;
- `docs/stage1_5/HANDOFF_TO_STAGE2.md` и acceptance report;
- `apps/api/app/contracts/quantities.py`;
- viewer backend/coordinates/overlay и их тесты;
- модели Sheet/DocumentRevision/Job;
- auth permissions/resolver;
- worker registry;
- все reference-файлы этого пакета.

## Repository identity gate

Ожидается минимум:

```text
apps/api/app/
apps/web/src/
apps/admin/src/
packages/api-client/
docs/adr/
CLAUDE.md
```

Если открыт другой репозиторий — STOP без изменений.

## Цель Stage 2A

Построить ручное измерительное ядро:

```text
PDF revision
  → canonical page geometry
  → normalized↔PDF coordinate transforms
  → manual scale calibration
  → TakeoffItem
  → Measurement
  → deterministic count/length/area
  → benchmark + live acceptance
```

## Жёсткие инварианты

1. `Region != Measurement != Quantity`.
2. `DocumentRevision` immutable.
3. `Sheet.width_px/height_px` никогда не являются физической геометрией QTO.
4. Нормализованные legacy-v1 coordinates относятся к уже отображённой странице; rotation второй раз не применять.
5. Физическая длина/площадь считаются только через canonical PDF display geometry.
6. Старый `units_per_normalized` нельзя превращать в рабочую схему.
7. ScaleCalibration должна быть воспроизводимой/версионной; старый результат не меняется молча.
8. Один лист может содержать несколько масштабов.
9. Measurement для length/area явно знает calibration, по которой рассчитан.
10. Модель/LLM/VLM никогда не считает количество на Stage 2A — моделей вообще не вызываем.
11. Calculation service детерминированный и versioned.
12. OpenAPI — единственный API contract; generated TS client руками не редактировать.
13. Object-level authorization обязательна для всех новых сущностей.
14. Canvas2D не заменять на WebGL без benchmark.
15. Pointermove не делает API write и не перерендеривает PDF base.
16. Feature flag `takeoff.manual` не включать до финального acceptance.
17. Не создавать ВОР/цены/сметный движок.
18. Не начинать Stage 2B автоматически.

## Этот промт ничего не реализует

Выведи:

- подтверждение репозитория;
- фактическую head migration;
- актуальный список ADR;
- что в текущем коде конфликтует с Stage 2A;
- найден ли regression test viewer, описанный в Stage 1.5 отчёте;
- какие пункты reference/CURRENT_REPO_FINDINGS.md уже исправлены, а какие ещё актуальны.

STOP. Не переходи к Prompt 01.
