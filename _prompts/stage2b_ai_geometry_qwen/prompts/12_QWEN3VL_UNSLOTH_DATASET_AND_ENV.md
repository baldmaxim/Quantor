# PROMPT 12 — Qwen3-VL + Unsloth: SFT dataset contract и isolated training environment

Цель — добавить VLM-ветку как **исследовательский конкурент**, не превращая production API в LLM runtime.

## 1. Модели-кандидаты

Зафиксируй exact model IDs/model-card revisions до скачивания:

- primary: `Qwen/Qwen3-VL-4B-Instruct`;
- efficiency lower bound: `Qwen/Qwen3-VL-2B-Instruct`;
- conditional upper bound: `Qwen/Qwen3-VL-8B-Instruct` только если hardware позволяет и 4B оставляет meaningful ambiguity.

Thinking editions на этом этапе не нужны. Нужен стабильный structured output, а не chain-of-thought.

## 2. Licensing/provenance

Обнови `docs/stage2b/model-license-matrix.md`:

- exact Qwen model card URL, revision/hash, license;
- Unsloth core exact version/commit/license;
- явно не использовать/не vendor-ить Unsloth Studio UI;
- Transformers/PEFT/TRL/PyTorch/CUDA components и notices;
- trained adapter/merged-weight SHA-256 и parent model hash.

Не считать license Python package автоматически license model weights.

## 3. Environment

Создай отдельный reproducible training extra/environment внутри `vision/` или рядом, не в `apps/api`:

- pinned lock/requirements;
- GPU capability probe;
- BF16 support probe;
- Unsloth/Qwen3-VL load smoke test;
- inference smoke on synthetic/public image;
- no client data in logs/W&B/cloud by default.

Если Unsloth/Qwen3-VL combination фактически не запускается в текущем окружении — отметить BLOCKED с точной версией/stacktrace, не писать workaround наугад.

## 4. SFT schema

Реализуй dataset adapter из frozen Prompt 08 manifest.

### `qwen_slab_localization_v1`

Input: production-like tile/page image + concise instruction.

Target: strict compact JSON only, например:

```json
{
  "schema":"qwen_slab_localization_v1",
  "objects":[{
    "class":"slab",
    "bbox":[120,180,870,820],
    "positive_points":[[350,420],[710,550]],
    "negative_points":[[470,350]]
  }]
}
```

Coordinates integer 0..1000 relative to exact model input image. No physical units.

Target generation from PlanSwift GT разрешён **только для train labels**. Validation/test inputs/crops/prompts не используют GT.

### `qwen_slab_polygon_v0`

Experimental only: simplified outer/holes with bounded vertices. If target requires too many vertices/tokens, sample is marked unsupported for this branch; не truncate silently.

### Masonry

На Stage 2B VLM minimum = rough ROI/contains-masonry/localization helper. Не заставляй Qwen генерировать километры centerline tokens как основной путь.

## 5. Parser

Strict schema parser:

- reject prose/fences/extra keys if contract says strict;
- coordinates bounds check;
- bbox order/area validation;
- bounded object/point count;
- parse failures are a metric, not silently repaired by another LLM.

Создай `docs/stage2b/12-qwen-unsloth-dataset-env.md` и synthetic tests. **Не обучай модель в этом prompt.**

STOP.
