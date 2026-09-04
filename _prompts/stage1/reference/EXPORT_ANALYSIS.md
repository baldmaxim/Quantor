# Анализ текущего экспортного архива распознавалки

Исследованный пример: `01-03-00-01-12_ПД-00260560-АР.zip`.

## Состав

Архив содержит 4 файла:

- исходный PDF: ~49.9 MB;
- `*_results.md`: ~0.99 MB;
- `*_results.html`: ~1.37 MB;
- `*_blocks.json`: ~0.21 MB.

PDF содержит 77 страниц.

`blocks.json`:

- `schema_version: 1`;
- `coordinate_space: normalized_page_top_left`;
- 77 записей pages;
- 383 block records;
- 230 `text`;
- 90 `image`;
- 63 `stamp`;
- 380 прямоугольных областей и 3 polygon;
- 320 блоков имеют `crop_url`;
- 63 stamp-блока не имеют ordinal и crop URL.

Пример page record:

```json
{
  "page_index": 0,
  "width_px": 2481,
  "height_px": 3509,
  "rotation": 0
}
```

Пример block record:

```json
{
  "block_id": "blk_...",
  "ordinal": 27,
  "page_index": 26,
  "page_label": 27,
  "block_type": "image",
  "shape_type": "rectangle",
  "status": "recognized",
  "export_status": "recognized",
  "coords_norm": [0.10, 0.04, 0.92, 0.88],
  "polygon_points": null,
  "crop_url": "https://..."
}
```

`results.md` содержит 320 секций вида:

```md
### BLOCK #27 [IMAGE]: blk_<id>
...
**Summary:** ...
**Description:** ...
**Entities:** ...
```

То есть `results.md` соответствует `text + image` блокам, но stamp-блоки отдельно как секции не экспортируются. Штамповая информация повторяется в metadata распознанных блоков.

## Архитектурные выводы

1. `blocks.json` — источник геометрии и page linkage.
2. `results.md` — legacy semantic payload; связывать по `block_id`.
3. `results.html` не считать источником истины. Хранить как исходный artifact, но не строить бизнес-логику на HTML.
4. `crop_url` считать внешней необязательной ссылкой. **Не скачивать сервером автоматически**: это делает архив несамодостаточным и создаёт SSRF/availability-риск.
5. Crop можно воспроизводить из исходного PDF по `coords_norm`, поэтому canonical source = PDF + page geometry + normalized coordinates.
6. Все исходные файлы должны храниться неизменно, с SHA-256.
7. На будущее нужен manifest-based пакет v2, чтобы не угадывать роли файлов по имени.
8. Unicode/Russian filenames и русскоязычный Markdown должны быть first-class case.

## Legacy import policy для Stage 1

Поддержать текущий ZIP как `recognized-package/legacy-v1`:

- найти PDF;
- найти `*_blocks.json`;
- найти `*_results.md`;
- `*_results.html` опционален;
- проверить schema version и coordinate space;
- создать DocumentRevision + Sheets + Regions;
- raw Markdown section можно сохранить как payload региона, но не разбирать его семантически глубже;
- stamp regions сохранить даже без recognized content;
- crop URL сохранить как legacy metadata, но не fetch'ить;
- не выполнять никакой AI-инференс.

## Future package v2 — только целевой контракт, НЕ реализовывать exporter в Stage 1

Рекомендуемый формат:

```text
recognized-package-v2.zip
  manifest.json
  source/
    document.pdf
    optional/model.rvt
    optional/model.nwd
  recognition/
    pages.json
    regions.jsonl
    content.jsonl
  optional/crops/
  checksums.sha256
```

`manifest.json` должен явно объявлять версии схем, документы, revisions, coordinate spaces и hashes.
