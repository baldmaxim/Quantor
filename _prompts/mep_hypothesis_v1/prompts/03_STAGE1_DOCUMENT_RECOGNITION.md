# PROMPT 03 — Stage 1. Распознавание стадии П одного этажа

Реализуй Stage 1 для одного выбранного листа/плана этажа. Цель — `MepEvidenceGraph`, а не финальная РД.

Переиспользуй существующий Quantor ingest и source-space pipeline. Для vector PDF используй native paths/text where available; для raster/mixed — vision fallback. Сохраняй оба канала раздельно.

Для первого scope `ВК / типовой жилой этаж` распознавай:
- границу/контекст этажа и основные архитектурные препятствия;
- помещения/санузлы, если доступны;
- стояки ВК;
- сантехнические приборы и точки подключения;
- явно показанные трубопроводы/фрагменты трасс;
- марки/подписи/диаметры/отметки;
- legend/schedule references, если они на том же комплекте;
- scale и координатное преобразование.

Не достраивай отсутствующие трубы в Stage 1.

UI/результат:
- overlay с разными слоями `observed vector`, `observed vision`, `text`, `unresolved`;
- JSON graph;
- таблица распознанных сущностей и confidence;
- явный статус scale.

Метрики на labelled validation:
- node/entity precision/recall/F1;
- route-fragment precision/recall в геометрическом tolerance;
- OCR exact/normalized accuracy для марок и диаметров;
- scale resolution success;
- topology of observed connections.

Добавь режим `oracle_stage1.json`, чтобы Stage 2 можно было тестировать независимо от ошибок Stage 1.
