# PlanSwift Ground Truth — контракт импорта

Это частный benchmark/training контур. Он не является production import проекта.

## Факты, найденные при предварительном разборе двух архивов

Ожидаемые значения используются только как sanity check — importer обязан пересчитать их
сам и выдать расхождение, а не hardcode.

### ЖК Stories — кладка

- 16 страниц;
- примерно 2 540 валидных Linear Section;
- координаты `DigitizerData` визуально совпали с исходными TIFF;
- разметка удобна как centerline ground truth.

### Мосфильмовская 31А — монолит

- 32 страницы;
- около 2 903 валидных геометрий суммарно;
- встречаются wall/beam line geometries;
- outer Area polygons;
- Area Subtract sections / holes;
- Count sections и несколько count points в одном section.

Предварительно для slab/foundation особенно ценны сотни outer polygons и сотни holes.

## Особенности PlanSwift, которые importer обязан учитывать

- XML может объявлять UTF-8, но фактически быть Windows-1251. Парсер: BOM/declaration →
  strict UTF-8 → controlled cp1251 fallback с метрикой fallback_count.
- `PageGUID` связывает takeoff с конкретной страницей.
- `ScaleX` и `ScaleY` хранить как evidence, но не превращать в Quantor ScaleCalibration.
- `Area Subtract Section` иногда требует наследовать page identity от parent Area Section.
- Count Section может содержать несколько реальных точек: section count != object count.
- `(-1,-1)` и аналогичные placeholder coordinates исключать с explicit rejection reason.
- Имена каталогов/файлов могут быть усечены; семантическое имя брать из XML, если оно есть.
- Raw TIFF/PDF/XML остаются private artifacts; в git не попадают.

## Canonical GroundTruth v1

Минимум:

```json
{
  "dataset_id": "...",
  "source": "planswift",
  "project_key": "...",
  "page": {
    "page_guid": "...",
    "image_sha256": "...",
    "width_px": 0,
    "height_px": 0
  },
  "annotation": {
    "id": "...",
    "kind": "polyline|polygon|polygon_hole|count",
    "label_raw": "...",
    "points_normalized": [[0.0, 0.0]],
    "parent_annotation_id": null,
    "source_xml_sha256": "..."
  }
}
```

Ground truth coordinates храним нормализованными относительно source image, плюс сохраняем
исходные координаты/evidence для воспроизводимости.
