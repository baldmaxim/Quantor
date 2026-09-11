# PROMPT 13 — Qwen3-VL localization baseline + Unsloth LoRA/SFT

Цель — проверить, способен ли маленький VLM локализовать инженерный объект достаточно хорошо, чтобы передать prompt сегментатору.

Используй только frozen split Prompt 08 и dataset contract Prompt 12.

## A. Zero-shot baseline

Минимум `Qwen3-VL-4B-Instruct` **до fine-tuning**:

- strict localization prompt;
- deterministic decoding where possible;
- JSON parse rate;
- object recall;
- bbox IoU / center error;
- positive point inside-GT rate;
- negative point outside-GT rate;
- latency/VRAM.

Это обязательно: иначе нельзя доказать, что SFT что-то улучшил.

## B. SFT recipes

Основной model = 4B Instruct.

Сравни минимум две LoRA recipes через Unsloth, если hardware позволяет:

### QW4-LORA-LANG
- vision layers frozen;
- language/attention/MLP LoRA;
- цель — понять, хватает ли обучения output semantics/format.

### QW4-LORA-VISION
- vision layers LoRA enabled;
- language/attention/MLP LoRA enabled;
- same data/split/seed family;
- цель — измерить пользу domain adaptation visual encoder на строительных чертежах.

LoRA rank/alpha и max image resolution выбираются на train/val и фиксируются до test.

## C. 2B efficiency branch

Если 2B реально поддерживается текущим Unsloth stack и помещается в hardware — обучи сопоставимый SFT lower-bound. Не трать недели на hyperparameter search; задача — quality/latency tradeoff.

## D. 8B conditional

8B запускать только если:

- owner/hardware budget позволяет; и
- 4B близок к нужной точности, но видно model-capacity limitation; либо нужен upper-bound benchmark.

Не считать 8B обязательным для PASS Stage 2B.

## E. Precision policy

Где позволяет GPU, сначала зафиксировать BF16/FP16 inference baseline. QLoRA/4-bit разрешён как resource experiment, но нельзя считать его эквивалентом без измерения QTO/localization delta. Сохрани precision/quantization в run provenance.

## F. Evaluation

Test запускать только после freeze best recipe по validation.

Machine-readable metrics + examples of:

- correct localization;
- missed object;
- false object;
- schema failure;
- text/dimension-line confusion;
- crop/tile edge failure.

Создай `docs/stage2b/13-qwen-localization-sft.md`.

STOP.
