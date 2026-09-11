# PROMPT 07 — Ground Truth validation + visual QA

Importer без визуальной проверки недостаточен.

## Для каждой page

Сгенерируй deterministic QA overlay artifacts:

- source raster;
- outer polygons;
- holes отличимым стилем;
- centerlines;
- count points;
- annotation ids на выборочной debug версии.

Не встраивай эти картинки в git, только synthetic fixture output допускается.

## Validation

Проверить:

- all coordinates inside source page after normalization;
- PageGUID references resolved;
- no orphan hole unless explicit rejection;
- ring/line point counts;
- duplicate annotations;
- NaN/inf/placeholder;
- image SHA / dimensions stable;
- parse roundtrip deterministic;
- two runs produce same dataset fingerprint.

## Dataset card

Для каждого private dataset сгенерировать metadata card без клиентских изображений:

- project pseudonymous key;
- source format/version;
- pages;
- annotation counts by kind/label;
- rejection counts/reasons;
- encoding fallbacks;
- source/dataset fingerprint;
- known limitations.

Вручную визуально проверить выборку нескольких страниц обоих datasets и записать PASS/FAIL,
не подменять это unit test.

Документ `docs/stage2b/07-ground-truth-validation.md`.

STOP.
