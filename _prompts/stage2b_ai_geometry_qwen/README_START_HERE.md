# Quantor — Stage 2B: AI Geometry Lab + Qwen/Unsloth

Это **замена предыдущего Stage 2B пакета**. Используй именно этот архив, если Stage 2B ещё не начат. Если старый пакет уже частично выполнен — не повторяй миграции: сначала Prompt 00 должен сопоставить фактическое состояние и составить continuation plan.

Цель этапа — не выбрать любимую модель заранее, а провести честное соревнование архитектур на одном PlanSwift ground truth:

```text
                         PlanSwift Ground Truth
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
        Small CV models        SAM baselines       Qwen3-VL
        semantic/centerline       │                + Unsloth SFT
              │                   │                   │
              │                   │          localization / direct geometry
              │                   │                   │
              └──────────────┬────┴──────────────┬────┘
                             │                   │
                             │             Qwen → SAM
                             │                   │
                             └─────────┬─────────┘
                                       ▼
                                Mask / Vector
                                       ▼
                              Quantor Measurement
                                       ▼
                              Quantity Engine
```

## Primary hypotheses

- Small specialized segmentation may be fastest and sufficient.
- Qwen3-VL-4B fine-tuned through Unsloth may be better at understanding **what/where** on dense drawings.
- Qwen→SAM may combine semantic localization with precise masks.
- Qwen direct polygon generation is tested, but is not assumed to be accurate enough.

## Model ladder

- `Qwen3-VL-2B-Instruct` — efficiency lower bound;
- **`Qwen3-VL-4B-Instruct` — primary VLM candidate**;
- `Qwen3-VL-8B-Instruct` — optional upper bound only.

No model outputs physical quantity as truth. Meters/m² are always calculated by Quantor's existing deterministic Measurement/Quantity Core.

## Execution order

Put under:

```text
_prompts/stage2b_ai_geometry_qwen/
```

Start:

```text
Прочитай полностью и выполни:
_prompts/stage2b_ai_geometry_qwen/prompts/00_MASTER_STAGE2B_CONTEXT.md

Не переходи к следующему промту самостоятельно.
```

Then `01 → ... → 18`. **STOP after Prompt 18.** Send the model-selection report to the owner. Prompts `19–24` execute only after explicit promotion of concrete pipeline/checkpoint IDs.

Recommended owner review points: `01, 05, 08, 09, 12, 14, 18, 21, 24`.

## Data policy

Client PlanSwift archives/TIFF/PDF, generated training tiles and weights are private artifacts and are not committed. No client drawings are sent to remote inference/training services by default.

## Important license boundary

Official Qwen3-VL model cards checked during package preparation list Apache-2.0 for 2B/4B candidates. Unsloth core and Unsloth Studio have different licensing boundaries; use the core training stack only after exact-version audit and do **not** embed Studio UI in Quantor. Ultralytics remains blocked unless the owner separately approves an appropriate commercial license.
