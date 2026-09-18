# MEP: контракты EvidenceGraph и NetworkGraph v0.3

v3 PROMPT 05, 2026-09-15. Решения — [ADR-0027](../adr/0027-mep-gipoteza-p-rd-vor-izolirovannyj-eksperiment.md),
[ADR-0028](../adr/0028-mep-semanticheskoe-raspoznavanie-v-scope.md), Р-MEP-11, 14, 15.
Только типы, проверки, синтетические примеры и тесты. Ни модели, ни эндпоинта, ни таблицы.

## 1. Архитектура

```text
MepSystemProfile (profile_id + version)      классы, атрибуты, связи, системы — специфика дисциплины
        │ ключи
        ▼
MepEvidenceGraph   input_mode: MODEL_EXTRACTED | HUMAN_GT | HYBRID_REVIEWED
  EvidenceElement  kind (symbol/route/zone/text) · sheet · geometry · class_key · attributes
                   confidence · provenance · status · review · sources[] · unresolved[]
  EvidenceRelation relation_key · from/to · provenance · status · sources[]
  source_availability · gaps
        │ canonical_sha256 + evidence_ids / relation_ids
        ▼
InferenceStep      kind · tool · evidence_ids · relation_ids · input_step_ids (только ранее)
                   retrieved_case_ids · rule_ids · confidence · alternatives · rationale
        │ step_ids
        ▼
MepNetworkGraph
  NetworkSystem · NetworkNode(role, class_key, position, ports[]) · NetworkSegment(start/end port,
  path[Vertex], orientation, parameters[]) · UnresolvedDecision
  у каждого элемента и каждого параметра — Derivation(provenance, step_ids, evidence_ids, confidence)
```

Где лежит:

| Файл                                               | Содержание                                                  |
| -------------------------------------------------- | ----------------------------------------------------------- |
| `apps/api/app/contracts/mep/common.py`             | версия, идентификаторы, лист, уровень, документ, инструмент |
| `apps/api/app/contracts/mep/profile.py`            | `MepSystemProfile`, общие `EvidenceKind`, `NodeRole`        |
| `apps/api/app/contracts/mep/evidence.py`           | `MepEvidenceGraph`                                          |
| `apps/api/app/contracts/mep/network.py`            | `MepNetworkGraph`, `InferenceStep`, `Derivation`, `Vertex`  |
| `apps/api/app/contracts/mep/validation.py`         | проверки профиля и evidence, `canonical_sha256`             |
| `apps/api/app/contracts/mep/network_validation.py` | проверки сети                                               |
| `apps/api/app/contracts/mep/schemas.py`            | выгрузка JSON Schema                                        |
| `docs/mep/schemas/*.v0.3.schema.json`              | JSON Schema для `vision/` и внешних производителей          |
| `apps/api/app/services/mep/fixtures/*.v0.3.json`   | синтетические профиль, evidence и сеть                      |
| `apps/api/tests/test_mep_contracts.py`             | 44 теста                                                    |

Модели Pydantic живут рядом с остальными контрактами портала (`app/contracts/`) — будущий роутер `mep`
получит их в OpenAPI без ручных DTO. `vision/` в `apps/api` не зависит: он пишет JSON и проверяется по
опубликованной JSON Schema; смысловые проверки выполняет доверенная сторона портала.

Схемы v0.1 (`_prompts/mep_hypothesis_v1/schemas/`) — история, не мигрируются и не удаляются.

## 2. Observed и generated не смешиваются

- В `EvidenceProvenance` и `EvidenceStatus` нет значения для вывода РД: `rd_prior_inferred` в evidence
  не разбирается (тест `test_generator_origin_cannot_enter_evidence`).
- `extraction_inferred` — только вывод в пределах листа (подпись отнесена к символу).
- Описания IMAGE-блоков распознавалки не имеют канала-источника: `base_region_text` — только тело TEXT-блока.
- `MODEL_EXTRACTED` не содержит разметки человека; `HUMAN_GT` — только её; `human_confirmed` требует
  `review=confirmed`.
- Сеть ссылается на evidence по хешу графа: изменённый evidence ломает ссылку (`EVIDENCE_GRAPH_MISMATCH`).
- `evidence_observed` в сети требует `evidence_ids`; `rd_prior_inferred`, `retrieved_pattern`,
  `deterministic_rule` — `step_ids`; `retrieved_pattern` — случай корпуса; `deterministic_rule` — правило.
- Параметр без значения обязан быть `unresolved`, и наоборот.

## 3. Цепочка происхождения на примере

Из [evidence_graph.v0.3.json](../../apps/api/app/services/mep/fixtures/evidence_graph.v0.3.json) в [network_graph.v0.3.json](../../apps/api/app/services/mep/fixtures/network_graph.v0.3.json):

```text
П, лист sheet-p3
  ev-route-1  route, polyline, mep_model_observed, source page_raster(det)
  ev-txt-2    text "d50", deterministic_extracted, source pdf_text_layer(txt)
  rel-2       syn.rel.labels ev-txt-2 → ev-route-1, extraction_inferred
      │ evidence_graph.sha256 = de632a3c…
      ▼
st-3  topology   evidence [ev-route-1], relation [rel-3], case train-case-017, 2 альтернативы
st-5  attribute  evidence [ev-route-1, ev-txt-2], relation [rel-2], input [st-3]
st-4  routing    rule syn.routing.min_length.v0, input [st-3]
st-6  attribute  case train-case-017, input [st-3]
      ▼
РД
  seg-main          derivation evidence_observed  [ev-route-1] via st-3
    nominal_size=50 derivation evidence_observed  [ev-route-1, ev-txt-2] via st-5
    material=null   derivation unresolved → ud-1 missing_attribute, blocks_quantity
  n-j1 junction     derivation rd_prior_inferred  via st-3            (на листе не показан)
  seg-b1            derivation deterministic_rule via st-3, st-4       (трасса построена роутером)
    nominal_size=32 derivation rd_prior_inferred  via st-6, confidence 0.55
```

Любой элемент РД разворачивается обратно: `derivation.step_ids` → `InferenceStep` → `evidence_ids`,
`relation_ids`, `retrieved_case_ids`, `rule_ids`, `tool_id` с версией и хешами.

## 4. Минимальные примеры

`MepEvidenceGraph` (сокращено, полный — в `apps/api/app/services/mep/fixtures/`):

```json
{
  "schema_version": "0.3.0",
  "graph_id": "eg-demo-001",
  "input_mode": "MODEL_EXTRACTED",
  "profile": { "profile_id": "synthetic.demo", "profile_version": "0.3.0" },
  "document": {
    "project_id": "proj-demo",
    "revision_id": "rev-demo",
    "source_pdf_sha256": "1111…"
  },
  "sheets": [
    {
      "sheet_id": "sheet-p3",
      "page_index": 3,
      "geometry_fingerprint": "2222…",
      "level_id": "L01",
      "scale_status": "calibrated",
      "scale_calibration_id": "scale-001"
    }
  ],
  "tools": [{ "tool_id": "det", "name": "synthetic-symbol-detector", "version": "0.0.0" }],
  "source_availability": [
    { "source_type": "page_raster", "sheet_id": "sheet-p3", "availability": "available" }
  ],
  "elements": [
    {
      "id": "ev-term-1",
      "kind": "symbol",
      "sheet_id": "sheet-p3",
      "geometry": { "kind": "point", "point": [0.6, 0.3] },
      "class_key": "syn.ev.terminal_symbol",
      "confidence": 0.88,
      "provenance": "mep_model_observed",
      "status": "observed",
      "sources": [{ "source_type": "page_raster", "ref_id": "raster-p3-150dpi", "tool_id": "det" }]
    }
  ],
  "gaps": [
    {
      "code": "no_visible_route_to_terminals",
      "sheet_id": "sheet-p3",
      "subject_ids": ["ev-term-1"]
    }
  ]
}
```

`MepNetworkGraph` (сокращено):

```json
{
  "schema_version": "0.3.0",
  "graph_id": "ng-demo-001",
  "evidence_graph": {
    "graph_id": "eg-demo-001",
    "sha256": "de632a3c…",
    "input_mode": "MODEL_EXTRACTED"
  },
  "tools": [{ "tool_id": "gen", "name": "synthetic-retrieval-baseline", "version": "0.0.0" }],
  "inference_steps": [
    {
      "id": "st-1",
      "kind": "evidence_adoption",
      "tool_id": "gen",
      "evidence_ids": ["ev-src-1", "ev-term-1"]
    },
    {
      "id": "st-3",
      "kind": "topology",
      "tool_id": "gen",
      "input_step_ids": ["st-1"],
      "retrieved_case_ids": ["train-case-017"],
      "alternatives_considered": 2
    }
  ],
  "systems": [
    {
      "id": "sys-1",
      "system_key": "syn.sys_a",
      "derivation": { "provenance": "retrieved_pattern", "step_ids": ["st-3"] }
    }
  ],
  "nodes": [
    {
      "id": "n-src",
      "role": "source",
      "class_key": "syn.net.source",
      "system_ids": ["sys-1"],
      "position": { "sheet_id": "sheet-p3", "x": 0.2, "y": 0.5, "level_id": "L01" },
      "ports": [{ "id": "p-src-out", "direction": "out", "system_id": "sys-1" }],
      "derivation": {
        "provenance": "evidence_observed",
        "step_ids": ["st-1"],
        "evidence_ids": ["ev-src-1"]
      }
    },
    {
      "id": "n-t1",
      "role": "terminal",
      "class_key": "syn.net.terminal",
      "system_ids": ["sys-1"],
      "position": { "sheet_id": "sheet-p3", "x": 0.6, "y": 0.3, "level_id": "L01" },
      "ports": [{ "id": "p-t1-in", "direction": "in", "system_id": "sys-1" }],
      "derivation": {
        "provenance": "evidence_observed",
        "step_ids": ["st-1"],
        "evidence_ids": ["ev-term-1"]
      }
    }
  ],
  "segments": [
    {
      "id": "seg-1",
      "class_key": "syn.net.segment",
      "system_id": "sys-1",
      "start": { "node_id": "n-src", "port_id": "p-src-out" },
      "end": { "node_id": "n-t1", "port_id": "p-t1-in" },
      "path": [
        { "sheet_id": "sheet-p3", "x": 0.2, "y": 0.5 },
        { "sheet_id": "sheet-p3", "x": 0.2, "y": 0.3 },
        { "sheet_id": "sheet-p3", "x": 0.6, "y": 0.3 }
      ],
      "orientation": "horizontal",
      "parameters": [
        { "key": "syn.material", "value": null, "derivation": { "provenance": "unresolved" } }
      ],
      "derivation": { "provenance": "rd_prior_inferred", "step_ids": ["st-3"], "confidence": 0.6 }
    }
  ],
  "unresolved": [
    { "id": "ud-1", "code": "missing_attribute", "subject_ids": ["seg-1"], "blocks_quantity": true }
  ]
}
```

## 5. Размерности

- `Vertex`: плановая точка листа `(sheet_id, x, y)` и/или `z_mm` и/или `level_id`; хотя бы одно задано.
- `Level.elevation_mm` может быть неизвестна (`null`), а не ноль.
- Вертикальный переход — `NetworkSegment(orientation="vertical")` между разными отметками или уровнями;
  без них — `VERTICAL_WITHOUT_ELEVATION`. Связь этажей — такой участок между узлами разных уровней
  (тест `test_vertical_transition_between_levels`). Межэтажного solver нет.
- Evidence остаётся 2D на листе; отметка с листа — атрибут профиля, уровень — `level_id`.

## 6. Достаточность для Quantity Engine (PROMPT 09)

Без повторного анализа изображения движок получает:

| Величина                        | Откуда в графе                                                                 |
| ------------------------------- | ------------------------------------------------------------------------------ |
| длина участка в плане           | `path` (нормализованные точки) + `sheets[].scale_calibration_id` → `length.v1` |
| длина вертикали                 | разность `z_mm` или `Level.elevation_mm`                                       |
| разбивка по системе/размеру     | `system_id`, `class_key`, `parameters` по ключам профиля                       |
| повороты                        | промежуточные вершины `path`                                                   |
| разветвления                    | узел `junction` и число подключённых портов                                    |
| переходы размера                | разные значения параметра размера у участков одного узла, узел `transition`    |
| приборы, оборудование, арматура | узлы с ролями `terminal`, `equipment`, `device` и их `class_key`               |
| что считать нельзя              | `UnresolvedDecision.blocks_quantity`, `QUANTITY_BLOCKED_NO_SCALE`              |

Граф длин и количеств не хранит — только основания для их расчёта.

## 7. Намеренно зависит от профиля

- классы evidence и сети (`class_key`), их вид, допустимая геометрия и роли узлов;
- атрибуты и параметры: ключ, тип, единица, допустимые значения (размер, материал, марка, уклон…);
- типы связей evidence и допустимые виды на концах;
- системы и правило топологии (`tree` запрещает циклы);
- коды пробелов `EvidenceGap.code`, id правил и случаев корпуса — строки, которые толкует профиль правил
  или датасет.

В ядре остаются только общие виды evidence (`symbol`, `route`, `zone`, `text`) и топологические роли
(`source`, `terminal`, `junction`, `equipment`, `device`, `transition`, `endpoint`, `unresolved_anchor`).
Тест `TestCoreIsDisciplineAgnostic` не пускает в перечисления ядра названия приборов и элементов систем.

Реальный профиль ВК/ОВ — PROMPT 02, по настоящему комплекту П. `synthetic.demo` ничего реального не описывает.

## 8. Проверки

| Граф     | Коды ошибок                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| профиль  | `DUPLICATE_ID`, `UNKNOWN_ATTRIBUTE`; структура классов — при разборе                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| evidence | `DUPLICATE_ID`, `UNKNOWN_SHEET/LEVEL/TOOL/SUBJECT`, `RELATION_MISSING_ENDPOINT`, `RELATION_SELF`, `INPUT_MODE_CONFLICT`, `PROVENANCE_STATUS_MISMATCH`, `HUMAN_CONFIRMED_NOT_REVIEWED`, `PROVENANCE_SOURCE_MISMATCH`, `MISSING_TOOL`, `SOURCE_UNAVAILABLE`, `TEXT_WITHOUT_CONTENT`, `CLASS_UNRESOLVED_WITHOUT_REASON`, `UNRESOLVED_WITHOUT_REASON`, `ATTRIBUTE_SOURCE_NOT_TEXT`, `METRIC_WITHOUT_SCALE`, профиль: `PROFILE_MISMATCH`, `UNKNOWN_CLASS/SYSTEM/ATTRIBUTE/RELATION`, `CLASS_KIND_MISMATCH`, `GEOMETRY_NOT_ALLOWED`, `ATTRIBUTE_TYPE_MISMATCH`, `RELATION_KIND_MISMATCH`; предупреждение `DUPLICATE_ELEMENT` |
| сеть     | `DUPLICATE_ID`, `EVIDENCE_GRAPH_MISMATCH`, `UNKNOWN_TOOL/STEP/EVIDENCE/SHEET/LEVEL/SYSTEM/SUBJECT`, `STEP_ORDER`, `OBSERVED_WITHOUT_EVIDENCE`, `INFERRED_WITHOUT_STEP`, `MISSING_RULE_OR_CASE`, `EVIDENCE_REJECTED`, `SEGMENT_MISSING_ENDPOINT`, `SEGMENT_SELF_LOOP`, `CROSS_SYSTEM_CONNECTION`, `PORT_OVER_CONNECTED`, `DISCONNECTED_NODE`, `CLASS_UNRESOLVED_WITHOUT_DECISION`, `VERTICAL_WITHOUT_ELEVATION`, профиль: `CYCLE_IN_TREE_SYSTEM`, `UNKNOWN_CLASS`, `ROLE_NOT_ALLOWED`, `ATTRIBUTE_TYPE_MISMATCH`; предупреждения `UNUSED_PORT`, `JUNCTION_DEGREE`, `QUANTITY_BLOCKED_NO_SCALE`                          |

Не входит в v0.3: проверка препятствий (нет контракта архитектурной геометрии), межэтажный solver.
`MepBoq` — [09-quantity-engine](09-quantity-engine.md).

## 9. Выгрузка схем

```bash
cd apps/api && python -m app.contracts.mep.schemas ../../docs/mep/schemas && cd ../.. && pnpm exec prettier --write docs/mep/schemas
```

Тест `test_published_schema_matches_models` сравнивает опубликованные схемы с моделями.

## 10. Hardening

Добавлено совместимо (новые необязательные поля и проверки), тесты — `apps/api/tests/test_mep_provenance.py`.

| Требование                           | В контракте                                                                                                                                                                    | Проверки                                                                                                                                                                                                                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| неизменяемый снимок калибровки       | `SheetRef.calibration: CalibrationSnapshot` — id, отпечаток страницы, размер pt, мм/pt, статус, `fingerprint` (`calibration_fingerprint`, по нормализованным десятичным)       | `CALIBRATION_SNAPSHOT_MISSING` при `calibrated`, `…_FINGERPRINT_MISMATCH`, `…_GEOMETRY_MISMATCH`, `…_ID_MISMATCH`, `…_STATUS_MISMATCH`                                                                                                                                                       |
| отпечаток профиля                    | `ProfileRef.profile_sha256` = `canonical_sha256(profile)`                                                                                                                      | при переданном профиле: `PROFILE_NOT_PINNED`, `PROFILE_FINGERPRINT_MISMATCH`                                                                                                                                                                                                                 |
| генератор / модель / прогон / конфиг | `MepNetworkGraph.run: GenerationRun` (run_id, git_commit, dirty, config_sha256, seed); `InferenceStep.run_id`, `config_sha256`; `Tool.model_id` + хеши                         | `RUN_PROVENANCE_MISSING`, `STEP_RUN_MISMATCH`, `MODEL_PROVENANCE_INCOMPLETE` (модель без хешей весов/конфига, и в evidence)                                                                                                                                                                  |
| корпус retrieval                     | `MepNetworkGraph.corpora: CorpusRef` (dataset_fingerprint, split_sha256, `split` только `train`); `InferenceStep.corpus_id`                                                    | `CORPUS_NOT_PINNED`, `UNKNOWN_CORPUS`; `split≠train` не разбирается                                                                                                                                                                                                                          |
| HYBRID_REVIEWED: исходное и история  | `EvidenceElement.original: OriginalPrediction` (выход модели/экстрактора как был); `review_history: ReviewEvent[]` (действие, проверяющий, время с поясом); у связей — история | `ORIGINAL_PREDICTION_MISSING`, `UNRECORDED_CORRECTION` (поле отличается без записи), `REVIEW_HISTORY_MISSING`, `REVIEW_HISTORY_ORDER`, `REVIEW_STATUS_UNSUPPORTED`, `CORRECTION_NOT_REFLECTED`, `ORIGINAL_PREDICTION_CONFLICT`; в `MODEL_EXTRACTED` истории нет, в `HUMAN_GT` нет `original` |

Профиль получил правило количества класса: `ClassDef.quantity` (`length` у участка, `count` у узла,
`none`) и `quantity_group_keys` ⊆ `attribute_keys`. Примеры переподписаны: хеш профиля, снимок калибровки,
прогон и корпус.

## 11. Дополнение 2026-09-18

`SourceType.pdf_vector_path` — векторные пути исходного PDF как канал evidence (Р-MEP-19). Совместимое
добавление значения перечисления; существующие графы и фикстуры A/B/C/D не меняются.
