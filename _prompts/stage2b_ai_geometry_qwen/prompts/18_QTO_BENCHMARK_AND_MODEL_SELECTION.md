# PROMPT 18 — Unified QTO benchmark и решение «интегрировать или остановиться»

Это главная контрольная точка Stage 2B. До этого момента ни один AI pipeline не считается production candidate.

## Freeze

Перед test freeze для каждого pipeline:

- dataset fingerprint + split hash;
- model/base/adapters/checkpoint hashes;
- precision/quantization;
- preprocessing + image resolution/tiling;
- decoding/schema version для Qwen;
- prompt policy для SAM;
- thresholds/vectorization config;
- metric tolerance;
- benchmark code version.

После freeze test не используется для настройки.

## Обязательные кандидаты в таблице

### Slab / area

1. small semantic segmentation;
2. SAM2/MobileSAM production-like baseline;
3. small segmentation → SAM refinement;
4. Qwen3-VL-4B zero-shot localization → SAM;
5. best Qwen3-VL-4B SFT → SAM;
6. Qwen3-VL-2B SFT → SAM, если experiment выполним;
7. Qwen direct polygon — research row;
8. 8B только если был запущен по правилам Prompt 13.

Oracle GT→SAM показывать отдельно и **никогда не ранжировать как candidate**.

### Masonry

Минимум small centerline model. Qwen может участвовать как ROI/semantic helper только если pipeline заранее описан и не использует GT на test.

## Metrics slab

- IoU/Dice/Boundary F1 diagnostic;
- vector net-area absolute error % (primary);
- median/p90 area error;
- outer recall;
- hole recall + hole-area error;
- invalid topology rate;
- false components;
- schema/parse failure rate для VLM;
- latency/page or tile, throughput;
- peak RAM/VRAM;
- model/runtime size.

## Metrics masonry

- centerline F1 with frozen tolerance;
- total-length error % (primary);
- missed/false branch length;
- endpoint error;
- latency/memory.

Физические метры не обязательны для offline model benchmark, если нет trusted Quantor calibration; сравнивай GT/pred в одной source coordinate system. Pilot physical quantity идёт только через ScaleCalibration.

## Selection

Применить `reference/BENCHMARK_GATES.md` без ослабления задним числом.

Выбирать Pareto по:

```text
QTO accuracy
+ geometry validity
+ latency/throughput
+ VRAM/RAM
+ model size
+ operational complexity
+ license/deployment fit
```

Не выбирать Qwen только потому, что он «умнее», и не выбирать tiny segmentation только потому, что он быстрее.

Отдельно ответить:

- дала ли SFT измеримый прирост над zero-shot Qwen;
- дала ли vision-LoRA прирост над language-only LoRA;
- выигрывает ли Qwen→SAM у small-seg→SAM настолько, чтобы оправдать VLM runtime;
- насколько 2B уступает/не уступает 4B;
- есть ли direct-polygon ветка, пригодная хоть для bounded cases;
- что является основной причиной ошибок каждого family.

## Hard gate

Если ни slab, ни masonry pipeline не проходит POC gate:

- failure report;
- error buckets;
- STOP STAGE 2B;
- **не выполнять Prompts 19–24**.

Если проходит хотя бы один task — promotion proposal включает **ровно один или несколько конкретных pipeline IDs/checkpoint hashes**, но Prompt 19 начинается только после explicit owner approval.

Создай:

```text
docs/stage2b/18-model-selection.md
benchmarks/stage2b/model-selection.json
```

STOP. Запросить решение владельца перед Prompt 19.
