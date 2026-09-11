# PROMPT 11 — SAM2 / MobileSAM baselines и refinement

SAM не должен получить unfair GT prompt на test.

## Эксперименты

Минимум:

1. SAM2 automatic/promptable baseline с prompt policy, доступной в production.
2. MobileSAM promptable baseline, если dependency/runtime стабилен.
3. Coarse mask baseline из Prompt 10 → connected-component bbox/points → SAM refiner.

### Запрещено

На validation/test брать bbox/point непосредственно из PlanSwift GT — это leakage. Prompt для
SAM генерируется только из source image, coarse model prediction или deterministic heuristic,
которая не видит GT.

## Fine-tuning

SAM2 умеет training/fine-tuning, но не начинай его автоматически. Сначала сравни zero/refiner
baseline. Fine-tune только если отчёт показывает, какую конкретно ошибку он должен исправить и
владелец продолжает этот эксперимент.

## Compare

Одинаковый frozen split и metrics с Prompt 10. Отдельно измерь стоимость/latency/VRAM.

Не объявлять победителя по IoU без QTO metrics — финальный выбор Prompt 18.

Документ `docs/stage2b/11-sam-baselines.md`.

STOP.


## Важная граница

Не делать вывод о SAM до Qwen→SAM эксперимента Prompt 14. Этот prompt устанавливает SAM-only и coarse-small-model→SAM baselines; Qwen prompts появятся позже и сравниваются на том же split.
