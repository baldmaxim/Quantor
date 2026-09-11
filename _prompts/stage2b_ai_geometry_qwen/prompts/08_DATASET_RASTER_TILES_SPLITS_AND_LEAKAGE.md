# PROMPT 08 — Raster tiles, targets, splits, leakage

Построй reproducible dataset builder поверх `planswift-gt-v1`.

## Targets

### Slab/foundation area

Raster target — foreground mask с holes, а source vector GT остаётся главным benchmark truth.
Не уничтожай holes morphology preprocessing-ом.

### Masonry

GT — centerline polyline. Построй centerline target/heatmap с заранее фиксированной толщиной
или distance-target policy. Выбор обосновать; evaluation остаётся vector centerline/length.

## Tiling

- configurable tile size and overlap;
- each tile stores exact transform back to full page normalized coordinates;
- padding explicitly recorded;
- no full-page gigapixel arrays in RAM if можно tile-stream;
- blank-negative sampling controlled, чтобы модель не училась говорить «background всегда».

## Split

Выполни rules из reference:

- page-grouped;
- perceptual near-duplicate clustering;
- cluster never crosses split;
- manifest frozen before training;
- fixed seed;
- hash split manifest.

С текущими данными честно подписать benchmark `within-project grouped holdout`.


## Qwen/VLM training views

На базе того же frozen split построй отдельные manifest views для SFT, **не создавая второй split**:

- `qwen_slab_localization_v1`: image/tile + instruction → strict JSON bbox/seed-points/class;
- `qwen_slab_polygon_v0`: экспериментальный simplified polygon JSON, только если target укладывается в bounded vertex/token budget;
- `qwen_masonry_roi_v0`: rough ROI / contains-masonry / optional guide points, не заменяет centerline baseline.

Координаты output-контракта — целые `0..1000` относительно **ровно того image input, который увидела модель**. Transform обратно в tile/page хранится отдельно и тестируется.

Training может oversample positive crops по GT, но validation/test обязаны использовать production-like deterministic tiling/cropping, который строится только из source image/page metadata и **не знает GT geometry**. Иначе benchmark leakage.

Добавь negatives: текст/размерные линии/штампы/пустые зоны/похожие нецелевые конструкции.

## No GT leakage

Ни SAM prompts, ни crop selection test split не могут использовать GT coordinates в evaluation.

Документ `docs/stage2b/08-dataset-build.md` + dataset config examples без private paths.

STOP. Это контрольная точка владельца перед training.
