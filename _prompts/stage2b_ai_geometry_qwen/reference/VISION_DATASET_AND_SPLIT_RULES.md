# Dataset и split rules

## Нельзя считать 5 000 геометрий пятью тысячами независимых проектов

Сейчас по каждому пилотному домену фактически один project source. Типовые этажи очень
похожи. Random split по annotation создаст leakage и нарисует ложную точность.

## Первичный split

1. Группировать все annotations одной страницы вместе.
2. Посчитать visual fingerprint страниц (pHash/другой устойчивый fingerprint).
3. Сгруппировать near-duplicate/типовые страницы.
4. Целый cluster попадает только в один из train/val/test.
5. Зафиксировать split manifest до обучения модели.
6. Не менять test split по результатам эксперимента.

Такой test называется **within-project grouped holdout**, а не доказательством generalization.

## Production-generalization gate появится позже

До заявления «работает на новых объектах» нужен project-level holdout минимум на нескольких
новых независимых PlanSwift проектах того же домена.

## Raster contract

Каждый training/inference tile обязан хранить transform:

```text
sheet normalized ↔ source raster pixels ↔ tile pixels
```

Tile может иметь padding/overlap, поэтому одного `x_offset/y_offset` без размера source image
недостаточно.

## Leakage rules

- никакие GT masks/boxes/points test split не используются как prompt SAM в evaluation;
- threshold/simplification/pruning параметры выбираются только по train/val;
- test metrics считаются один раз после freeze experiment config;
- raw filename/section name не используется как shortcut feature модели;
- audit должен уметь доказать, какие pages попали в каждый split.


## VLM-specific leakage rules

- training positive crop mining may use GT, but evaluation crop/tiling cannot;
- Qwen output coordinates are relative to model input image and must be transformed by recorded image transform;
- no GT-derived object count in test prompt text;
- no section/file names that directly encode class/answer as model input metadata;
- if page is too large, production-like tiling strategy is frozen before final test.
