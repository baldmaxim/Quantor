# Stage 2B benchmark

## Метрики монолита / area segmentation

Pixel metrics — вспомогательные:

- IoU / Dice;
- Boundary F1.

QTO metrics — основные:

- absolute net area error %;
- median / p90 area error;
- outer contour recall;
- hole recall;
- hole area error %;
- invalid topology rate;
- false component count;
- inference time / page and peak memory.

## Метрики кладки / centerline

- centerline precision/recall/F1 с фиксированной tolerance;
- total length error %;
- missed branch length %;
- false branch length %;
- endpoint distance;
- inference time / page and peak memory.

## POC gates (within-project grouped holdout)

Эти гейты нужны, чтобы решить «интегрировать ли эксперимент в pilot UI», а не чтобы заявить
универсальную точность на рынке.

### Slab candidate

- median absolute net-area error <= 5%;
- p90 <= 10%;
- invalid topology after vectorization <= 2%;
- hole recall >= 85% для holes выше минимального размера, определённого до test;
- reproducible metrics при повторном inference с fixed seed/config.

### Masonry candidate

- median page total-length error <= 5%;
- p90 <= 10%;
- centerline F1 >= 0.85 при tolerance, объявленной до test;
- false branch length <= 5% от GT length.

Если ни одна модель не проходит — STOP после Prompt 15. Не ослаблять gate задним числом.
Можно открыть новый эксперимент с новой заранее объявленной версией гейтов.

## Generalization gate

Не существует на текущих двух проектах. Нужны новые независимые projects. Любой отчёт Stage
2B обязан писать `within-project proof of feasibility`, а не `production accuracy`.


## Qwen localization diagnostic gates

Эти метрики не заменяют QTO gate, но помогают понять failure source:

- strict JSON parse rate >= 99% для promoted SFT checkpoint;
- bbox/object recall и seed-point validity фиксируются до SAM;
- hybrid считается успешным только по downstream mask/vector/QTO metrics; хороший bbox IoU сам по себе не PASS.

## Runtime-complexity rule

Если два pipeline статистически/практически эквивалентны по QTO quality в пределах заранее объявленного tolerance, предпочесть более простой/дешёвый runtime (меньше VRAM, latency, components). Qwen→SAM должен показать measurable benefit, чтобы оправдать VLM в production geometry path.
