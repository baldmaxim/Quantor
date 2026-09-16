# Quantor MEP P→RD→ВОР — MASTER PROMPTS v3

> Для уже запущенного v2 сначала используйте секцию MIGRATION. Для нового запуска используйте PROMPT 00 и далее.


---

# MIGRATION PATCH — v2 → v3 без перезапуска проекта

Используй этот промт, если работа уже начата по `Quantor_MEP_P_to_RD_Prompt_Pack_v2`.

---

Ты продолжаешь текущую работу Quantor MEP. **Не начинай проект заново, не откатывай выполненные изменения и не повторяй уже завершённые шаги.**

## Корректировка scope

Предыдущее правило `recognition is solved/frozen` было слишком широким.

С этого момента действует:

> **Base document recognition is solved and frozen.**  
> **MEP semantic recognition is NOT solved and IS IN SCOPE.**

### Frozen / read-only

Не менять без отдельного разрешения:
- PDF ingest;
- page rendering/rasterization;
- существующий vector extraction;
- OCR/text extraction;
- source coordinate transforms;
- общую инфраструктуру masks/points/polylines, если она уже существует;
- существующие модели/веса/датасеты монолита, кладки, дверей;
- production behavior существующего recognition flow.

### Новый разрешённый scope

Разрешено и требуется разработать поверх существующих артефактов:

`MEP Semantic Extraction Layer`

Для первого ВК PoC он должен уметь извлекать минимум те MEP-сущности и связи, которые реально нужны генератору: стояки/source anchors, приборы/terminals, оборудование, видимые инженерные линии, марки/диаметры/подписи и relations — точный минимальный taxonomy определить по реальным П-листам.

Цепочка:

```text
existing Quantor base recognition [FROZEN]
→ MEP semantic extraction [NEW]
→ MEP Evidence Graph
→ P→RD Generator
→ MEP Network Graph
→ Quantity Engine
→ Pricing
```

## Критически важно

1. Не создавать новый общий recognizer документов.
2. Не считать MEP-сущности уже существующими, пока это не подтверждено реальными output-файлами.
3. Если MEP semantic layer использует изображение, брать уже подготовленный page raster/crop из существующего pipeline; не строить второй PDF renderer.
4. Если использует текст — брать существующий OCR/text layer; не создавать второй OCR.
5. Ручная MEP-разметка допустима и нужна для GT/train/validation, но не должна становиться production-входом.
6. Не путать **Detection** и **Generation**:
   - detector отвечает «что реально показано на П?»;
   - generator отвечает «какая полноценная РД-система должна быть построена?».
7. `inferred` никогда не маркировать как `observed`.

## Что сделать сейчас

1. Зафиксируй, какие шаги v2 уже реально выполнены и какие файлы созданы/изменены.
2. Ничего не отменяй автоматически.
3. Перечитай текущий repository state.
4. Построй таблицу:

`Required MEP entity | already available | exact source | missing | proposed extraction method | GT needed`

5. Зафиксируй существующий base recognition boundary как read-only.
6. Вставь новый MEP semantic layer между base recognition и прежним `MepGenerationInput`/P→RD.
7. Если ранее созданный adapter полезен — переиспользуй его как base-artifact adapter; не удаляй только из-за смены терминологии.
8. Обнови state/plan документов так, чтобы последующие шаги использовали `MepEvidenceGraph`, а не предполагали готовые MEP anchors в legacy output.
9. Составь migration receipt:
   - что из v2 остаётся;
   - что меняется;
   - какие артефакты признаны устаревшими;
   - что делать следующим промтом v3.

## STOP

Не запускай обучение и не делай большой рефакторинг. Покажи migration receipt и дождись подтверждения, если требуется существенное изменение уже написанного кода.


---

# PROMPT 00 — Master context: Base Recognition frozen, MEP Semantic in scope

Ты работаешь в реальном репозитории Quantor.

## Бизнес-гипотеза

На одном этаже стадии П:

1. Quantor базово обрабатывает документ существующим pipeline.
2. Новый MEP semantic layer распознаёт инженерные сущности, реально присутствующие на П.
3. P→RD Generator достраивает полноценную инженерную систему уровня РД на основе опыта пар П↔РД.
4. Quantity Engine формирует полный ВОР из построенной сети.
5. Pricing Model сопоставляет позиции и расценивает работы/материалы по историческим данным.

Первый узкий scope: **ВК / горизонтальная разводка типового жилого этажа**.

## Неподвижная граница

### Base Recognition = FROZEN

Не трогать:
- PDF ingest/rendering;
- существующий OCR/text layer;
- существующий vector/raster extraction;
- source-space transforms;
- существующие общие primitives Count/Point/Polyline/Mask и их production behavior;
- модели/веса/датасеты монолита, кладки, дверей;
- существующие production routes, если не требуется минимальный read-only hook.

### MEP Semantic Recognition = IN SCOPE

Новый слой имеет право использовать **готовые** page raster/vector/OCR/geometry artifacts и распознавать недостающую инженерную семантику.

Он не должен заменять base recognition.

## Не смешивать три ответственности

### A. MEP Semantic Extraction

Отвечает только: **что действительно видно/написано на стадии П?**

### B. P→RD Generation

Отвечает: **как из evidence стадии П построить полную систему уровня РД?**

### C. BOQ/Pricing

Отвечает: **что получилось в количестве и сколько это стоит?**

## Что сделать

1. Прочитать handoff, README, run state, реальные contracts и текущую ветку/рабочее дерево.
2. Найти точную границу существующего base recognition.
3. Зафиксировать reusable artifacts: raster, tiles/crops, vector primitives, OCR, page transforms, scale, overlays, annotation utilities.
4. Определить новый namespace для MEP semantic extraction и downstream генерации.
5. Создать/обновить `MEP_P_TO_RD_STATE.md`:
   - Goal;
   - Base recognition frozen boundary;
   - Reusable artifacts;
   - MEP semantic gap;
   - Allowed new modules;
   - Forbidden modules/files;
   - Existing v2 artifacts that can be reused;
   - Risks;
   - Next prompt.
6. Добавить guards/feature flags OFF by default.

## Не делать сейчас

- не обучать модели;
- не создавать taxonomy на глаз без просмотра реальных листов;
- не писать P→RD generator;
- не рефакторить старый recognition;
- не делать commit/push/merge.

## Выход

Покажи:
- exact base recognition boundary;
- exact reusable files/APIs;
- список MEP-semantic данных, которых реально нет;
- список новых файлов/модулей, которые предлагаешь;
- blockers.

STOP.


---

# PROMPT 01 — Audit существующего output и MEP semantic gap

Продолжай после PROMPT 00.

## Цель

Не строить новый recognizer, а понять, что Quantor уже даёт бесплатно и что именно нужно добавить для инженерных систем.

## 1. Инвентаризация реального base output

По коду и реальным артефактам зафиксируй:
- canonical page/document result;
- page raster/tiles/crops;
- vector primitives/paths, если есть;
- OCR/text spans + bbox;
- source coordinate system/transforms;
- scale status;
- room/architecture geometry, если реально есть;
- existing point/polyline/count/mask entities;
- ids/hashes/provenance/confidence;
- annotation UI/storage, если есть.

Никаких предположений по названиям API.

## 2. Определить minimum MEP evidence для первого ВК PoC

Просмотри реальные П-листы/fixtures из доступного корпуса и составь таблицу:

`entity/relation | нужен generator? | уже есть? | exact source | representation | missing? | proposed extractor | GT type`

Проверить как минимум кандидаты:
- riser/source anchor;
- fixture/terminal;
- equipment;
- shaft/zone;
- visible pipe/route segment;
- system label;
- diameter/size text;
- mark/name;
- connection marker;
- text↔symbol relation;
- symbol↔route relation;
- route↔riser relation.

Не включай класс, если он не нужен первому PoC.

## 3. Reuse map

Для каждого нового MEP extraction шага укажи, что переиспользуется:
- existing page image;
- OCR spans;
- vector geometry;
- coordinate transforms;
- annotation primitives;
- overlay renderer;
- dataset storage;
- inference runner.

Если предлагается дублирование существующей функции — обосновать.

## 4. Freeze contract

Создай `BASE_RECOGNITION_REUSE_CONTRACT.md`:
- что можно читать;
- что нельзя менять;
- какие artifacts являются immutable input;
- как MEP layer ссылается на source ids/hashes;
- как проверяется отсутствие side effects.

## 5. Gate

Создай `MEP_SEMANTIC_GAP_GATE.md` с verdict:
- `READY_TO_DEFINE_LABELS`;
- `BLOCKED_NO_BASE_ARTIFACT` — только если нет даже пригодного page/image/coords input;
- `NEEDS_OWNER_DECISION` — если нужен change в frozen base pipeline.

STOP. Не писать detector в этом промте.


---

# PROMPT 02 — MEP label schema и ground truth

Запускать при `READY_TO_DEFINE_LABELS`.

## Цель

Создать минимальную, не раздутую схему разметки для MEP semantic extraction первого ВК PoC.

## Принцип

Размечаем **только то, что реально присутствует на стадии П**. Нельзя размечать предполагаемую РД-разводку как observed evidence.

## 1. Taxonomy

По реальным листам определить minimal label set. Предпочитать иерархию:

- `entity_type`: riser / terminal / equipment / device / route_visible / shaft / label ...
- `system/subsystem`: отдельный атрибут, а не десятки визуально похожих классов, если это повышает переносимость;
- attributes: mark, diameter, material, system code — only if visible/linked.

Не кодировать проектную организацию или конкретный шрифт/символ как семантический класс.

## 2. Geometry types

Для каждого label определить один canonical GT primitive:
- point;
- bbox;
- polygon/mask;
- polyline;
- text span ref;
- relation edge.

Не требовать mask там, где point/bbox достаточно.

## 3. Relations

Отдельно размечать relation GT, где это критично:
- text → symbol;
- diameter → route/riser;
- fixture → visible connection;
- route → riser;
- symbol → system label.

Relation не выводить автоматически в GT без provenance.

## 4. Unknown / ambiguous

Статусы:
- `CONFIRMED`;
- `AMBIGUOUS`;
- `IGNORE_FOR_TRAIN`;
- `NOT_VISIBLE`.

`UNKNOWN_NOT_NEGATIVE`: неразмеченная область не считается доказанным отсутствием объекта.

## 5. Annotation workflow

Сначала проверить существующий Quantor annotation UI/primitives.

Если можно — расширить минимально новыми MEP label types под feature flag. Не создавать новый annotation portal без необходимости.

Нужны:
- project/document/page ids;
- source image hash;
- annotator id;
- review status;
- label schema version;
- source coordinate preservation;
- inter-annotator review на subset.

## 6. Dataset builder

Подготовить builder для crops/tiles/full-page representations с обязательным сохранением обратного transform в source coordinates.

Защита от leakage: split по project/family, не по crop.

## 7. QA

Создать annotation QA:
- orphan text relation;
- invalid geometry;
- duplicate entity;
- impossible cross-page relation;
- label outside source bounds;
- class/system conflicts;
- missing source hash.

## 8. Deliverables

Создать:
- `MEP_LABEL_SCHEMA_V1.md`;
- machine-readable schema/config;
- 3–5 example annotated fixtures;
- `MEP_ANNOTATION_GUIDE.md`;
- dataset manifest builder;
- tests.

Не запускать массовую разметку и обучение. STOP с количеством листов/instances, которые нужны для первого labeling batch.


---

# PROMPT 03 — MEP semantic baseline без тяжёлого обучения

## Цель

До trainable detector получить измеримый baseline, максимально используя уже существующие Quantor artifacts.

Input:
- frozen base recognition artifacts;
- page raster/vector/OCR;
- schema из PROMPT 02.

Output:
- candidate MEP entities/relations с source coordinates, confidence и provenance.

## Допустимые baseline-компоненты

Используй только то, что оправдано реальным repository/data:
- OCR regex/lexicon для систем/диаметров/марок;
- vector line candidates;
- symbol/template matching на ограниченном наборе;
- connected components;
- geometric linking text↔symbol;
- lightweight existing vision embeddings, если уже доступны без нового тяжёлого pipeline.

Не превращай baseline в сотни хрупких проектно-специфичных правил.

## Метрики

На project-heldout validation:
- entity precision/recall/F1 by type;
- localization accuracy;
- relation F1;
- attribute accuracy known-only;
- confidence calibration;
- unresolved rate;
- source-coordinate integrity.

Отдельно показать metrics для объектов, критичных P→RD Generator.

## Downstream metric

Дополнительно измерить `generator_input_coverage`: какую долю обязательных anchors/relations baseline реально даёт.

## Deliverables

- code/tests;
- machine-readable metrics;
- `MEP_SEMANTIC_BASELINE_RESULT.md`;
- список ошибок по типам;
- verdict `BASELINE_SUFFICIENT_FOR_GENERATION_TEST | NEED_TRAINABLE_EXTRACTOR`.

Не запускать P→RD и не обучать тяжёлую модель. STOP.


---

# PROMPT 04 — Trainable MEP Semantic Extractor

Запускать после PROMPT 02 и измеренного baseline PROMPT 03.

## Цель

Разработать обучаемый слой, который извлекает MEP evidence, отсутствующий в legacy Quantor, при этом использует существующий base recognition как инфраструктуру входа.

## Жёсткие ограничения

- Не менять PDF renderer/OCR/vector base pipeline.
- Входное изображение брать из существующего page raster/crop API.
- OCR брать существующий.
- Source transforms брать существующие.
- Не обучать модели монолита/кладки/дверей.
- Новый model namespace/weights/configs — отдельные.

## Архитектура

Не фиксируй конкретный backbone заранее. Сначала сравни требования данных и baseline.

Допустимая декомпозиция:

1. **Entity detector** — точки/bbox/masks/polylines по schema.
2. **Text/attribute linker** — использует existing OCR + geometry.
3. **Relation head/linker** — text↔symbol, symbol↔route, route↔riser where supervised.
4. **Postprocessor** — перевод в source coordinates, deduplication, confidence/abstention.

Если часть задачи надёжнее решается детерминированно поверх model output — использовать hybrid approach.

## Training protocol

- split строго по project/family;
- fixed val/test;
- no crops from same page across folds;
- class imbalance audit;
- augmentation не должна ломать engineering semantics/text;
- `AMBIGUOUS/IGNORE` не использовать как negatives;
- learning curve 10/25/50/75/100%;
- no checkpoint selection on test.

## Tiny-overfit gate

До большого run:
- overfit tiny TRAIN-only subset;
- проверить coordinate roundtrip;
- проверить relation serialization;
- проверить deterministic inference receipt.

## Heavy GPU guard

Подготовить:
- dataloader;
- model interface;
- losses;
- metrics;
- config;
- exact training command;
- VRAM/runtime measurement plan.

**Не запускать тяжёлое обучение без явной команды владельца.**

## Acceptance relative to baseline

Trainable extractor должен улучшать не только visual F1, но и критичные downstream показатели:
- required MEP anchor coverage;
- relation coverage;
- P→RD generation success on validation fixture subset.

Создать `MEP_SEMANTIC_MODEL_PLAN.md` и STOP.


---

# PROMPT 05 — MEP Evidence Graph и MEP Network Graph contracts

## Цель

Жёстко разделить **наблюдаемое на П** и **сгенерированное как РД**.

## A. `MepEvidenceGraph v0.3`

Это output Stage 1 MEP semantic extraction.

### Identity
- graph_id/schema_version;
- project/document/page/floor;
- discipline/subsystem;
- base recognition snapshot/hash;
- semantic extractor version/model id;
- coordinate system/scale status.

### Evidence entities
Минимальные поля:
- stable evidence id;
- type;
- geometry/source coordinates;
- text/attribute refs;
- system/subsystem where observed;
- source artifact refs;
- confidence;
- provenance;
- review status.

### Evidence relations
- from/to evidence ids;
- relation type;
- confidence;
- provenance.

### Provenance
Например:
- `base_recognition_observed`;
- `mep_model_observed`;
- `deterministic_extracted`;
- `human_ground_truth`;
- `unresolved`.

**Никаких `rd_prior_inferred` в EvidenceGraph.**

## B. `MepNetworkGraph v0.3`

Это output Stage 2 P→RD Generator.

### Nodes
Для ВК минимум:
- riser/source;
- fixture/terminal;
- junction/tee;
- equipment;
- valve/device;
- transition;
- unresolved anchor.

### Edges
- ports;
- system/subsystem;
- polyline;
- metric length only when scale resolved;
- diameter/size/material/elevation/slope where available/inferred;
- route class;
- constraints;
- per-field provenance/confidence.

### Generation provenance
- `evidence_observed`;
- `rd_prior_inferred`;
- `retrieved_pattern`;
- `deterministic_rule`;
- `human_confirmed`;
- `unresolved`.

Нельзя повышать inferred до observed.

## C. Validators

EvidenceGraph:
- invalid source refs;
- geometry outside page;
- relation to missing entity;
- impossible duplicate;
- missing provenance;
- metric claim without scale.

NetworkGraph:
- disconnected required terminal;
- incompatible ports;
- cross-system contamination;
- orphan edge;
- invalid loop where prohibited by explicit rule;
- obstacle violation;
- duplicate id;
- unsupported attribute;
- missing provenance.

## D. Minimal fixtures

1. Small MEP EvidenceGraph: два прибора + стояк + видимая подпись/диаметр.
2. Small NetworkGraph: стояк → магистраль → tee → два ответвления → два прибора.

Никаких ML calls. Contracts/tests/docs only.


---

# PROMPT 06 — Парный датасет П↔РД для P→RD Generator

## Цель

Подготовить supervision для задачи:

`MepEvidenceGraph(stage P) → MepNetworkGraph(reference RD)`

Единица:

`(project_id, building/section, floor_id, discipline, subsystem, P_evidence_graph, RD_reference_network)`

## Ключевой принцип

Нужны **парные П↔РД одного объекта**, а не просто коллекция РД.

## 1. Pair discovery

- stage P и RD;
- корпус/секция/этаж/система;
- revisions/hashes;
- pairing confidence;
- неоднозначные пары → HOLD.

## 2. P input side

Основной production-like input: `MepEvidenceGraph`, полученный Stage 1.

Для изолированного теста генератора также поддержать `human_ground_truth EvidenceGraph`, чтобы отделить detector error от generator error.

Хранить `input_mode`:
- `MODEL_EXTRACTED`;
- `HUMAN_GT`;
- `HYBRID_REVIEWED`.

## 3. RD target side

Привести reference RD к `MepNetworkGraph`.

Если target создаётся parser-assisted/manual:
- хранить provenance;
- review status;
- не выдавать автоматический parser target за verified GT.

## 4. Alignment

- common source coordinate frame;
- transform;
- residual error;
- `AUTO_OK|REVIEW|HOLD`;
- no silent warp.

## 5. Delta labels

По возможности:
- retained anchor;
- added branch/route;
- moved route;
- connectivity change;
- diameter/material change;
- device/accessory added;
- elevation/slope change;
- unresolved supervision.

## 6. Leakage guard

Split строго по `project_id/project_family`. Этажи, revisions, crops одного объекта не могут расползаться по folds.

## 7. Dataset manifest

Считать:
- projects;
- paired album sets;
- usable floor-system pairs;
- network complexity;
- design organizations;
- typologies;
- nodes/edges;
- route meters where scale known;
- HOLD reasons;
- alignment quality;
- input_mode distribution.

## 8. Learning curve

Frozen val/test; train subsets 10/25/50/75/100%.

## Gate

`MEP_P_RD_DATASET_GATE.md`:
- `READY_FOR_BASELINE`;
- `HOLD_DATA`;
- `HOLD_ALIGNMENT`.

Не тренировать P→RD model в этом промте.


---

# PROMPT 07 — P→RD baseline: retrieval + topology + deterministic routing

## Цель

До deep generator собрать дешёвый измеримый baseline.

Input: `MepEvidenceGraph`.
Output: candidate `MepNetworkGraph`.

## A. Retrieval

Искать похожие TRAIN cases по доступным evidence/architecture признакам:
- typology;
- room/shaft geometry where available;
- riser positions;
- terminals/equipment;
- visible route hints;
- subsystem;
- building type.

Никогда не искать в held-out project family.

## B. Logical topology completion

Сначала предсказать/подобрать:
- terminal ↔ source/riser assignment;
- tree/branch structure;
- junctions;
- system assignment.

## C. Deterministic router

После topology построить route по допустимым зонам.

Cost function может учитывать только доказанные/конфигурируемые факторы:
- length;
- turns;
- crossings;
- obstacles;
- shaft/corridor/zone preferences, если они поддержаны данными/правилом.

Не вшивать придуманные нормы.

## D. Attributes

- observed → evidence provenance;
- deterministic approved rule → rule provenance;
- retrieved prior → prior provenance + confidence;
- insufficient evidence → unresolved.

## E. Два evaluation режима

1. `HUMAN_GT evidence` → измеряет собственно generation quality.
2. `MODEL_EXTRACTED evidence` → end-to-end quality.

Разницу между ними вывести отдельно как semantic-extraction penalty.

## Метрики

- terminal connectivity;
- network validity;
- topology edge F1;
- branch/junction accuracy;
- route coverage/distance;
- total route length error;
- known-only attributes;
- downstream quantity error;
- unresolved share;
- valid-alternative review.

Сравнить:
1. nearest-RD retrieval-only;
2. retrieval + topology;
3. retrieval + topology + router;
4. reference RD.

Создать `MEP_P_TO_RD_BASELINE_RESULT.md`. Не обучать deep model.


---

# PROMPT 08 — Trainable P→RD Generator

Запускать после dataset gate и baseline.

## Цель

Обучаемая модель получает `MepEvidenceGraph` стадии П и предсказывает инженерную систему уровня РД.

## Не использовать image-to-image RD как canonical output

Canonical output — typed `MepNetworkGraph`.

## Рекомендуемая декомпозиция

### 1. Evidence/context encoder

Потребляет:
- observed MEP entities;
- observed relations;
- architecture constraints;
- text/attributes;
- coordinate/scale state;
- optional base features only if explicitly contracted.

### 2. Connectivity head

- source/riser ↔ terminal;
- branches;
- junctions;
- topology.

### 3. Routing head / cost field

Модель может предсказывать waypoints/cost field/constraints, но финальная polyline желательно валидируется/строится deterministic router-ом.

### 4. Attribute heads

Только при наличии supervision:
- diameter/size;
- material;
- elevation;
- slope;
- devices/accessories;
- route class.

### 5. Uncertainty / abstention

Нужен `unresolved`, а не уверенная выдумка.

## Training

- project-heldout split;
- 10/25/50/75/100% learning curve;
- HUMAN_GT и MODEL_EXTRACTED inputs оценивать раздельно;
- no checkpoint selection on test;
- `UNKNOWN_NOT_NEGATIVE`;
- valid alternative review.

## Loss/metrics

- edge/connectivity;
- terminal coverage;
- junction;
- route geometry/validity;
- known-only attributes;
- downstream quantity metric;
- calibration/abstention.

## Work order

1. code/config/dataloader/model interfaces/tests;
2. tiny overfit TRAIN-only;
3. baseline comparison harness;
4. exact GPU command + preflight;
5. **не запускать тяжёлое обучение без команды владельца**;
6. STOP с отчётом.

Base recognition regression должен остаться неизменным.


---

# PROMPT 09 — MepNetworkGraph → полный ВОР: deterministic Quantity Engine

## Цель

Количество должно вычисляться из валидированного NetworkGraph и утверждённых правил, а не генерироваться LLM.

Input: validated `MepNetworkGraph`.
Output: quantity-only `MepBoq`.

## Для первого ВК scope

Минимум:
- трубы по system/material/diameter — length;
- fittings по topology/turns/branches/transitions;
- valves/devices по graph objects;
- fixtures/equipment counts;
- insulation — только при достаточных attributes + approved rule;
- supports — только при утверждённом spacing rule, иначе unresolved/estimate lane;
- penetrations — только при доказанном пересечении;
- firestopping — только по доказуемому penetration + approved mapping;
- demolition/existing works — только explicit source.

## STRICT vs ESTIMATE

### STRICT
Только quantities, выводимые из geometry/topology/evidence/approved deterministic rules.

### ESTIMATE
Rule-derived allowances, всегда отдельно маркированные.

## Traceability

Каждая строка:
- source node/edge ids;
- formula/rule id;
- unit;
- quantity;
- provenance;
- unresolved/review flags.

## Tests

- repeatability;
- route length consistency;
- diameter splits;
- tee/elbow/reducer counts;
- no metric quantity without scale;
- no duplicate count;
- graph delta → expected BOQ delta;
- pricing fields null.

## Evaluation

- line/item coverage;
- missing/extra;
- quantity WAPE;
- error by system/diameter/material;
- fitting/device error;
- unresolved share.

Создать `MEP_QUANTITY_ENGINE_RESULT.md`.


---

# PROMPT 10 — Отдельная модель item mapping и расценивания ВОР

## Цель

Расценить уже рассчитанный `MepBoq` по историческим ВОР Заказчика, КП, сметным/договорным строкам и другим разрешённым источникам.

Не смешивать ошибку количества с ошибкой цены.

## Input

Quantity-only BOQ:
- normalized description;
- system/subsystem;
- unit;
- quantity;
- attributes;
- source graph refs;
- region/date/class context where available.

## Historical corpus

Для каждой строки сохранять:
- customer/project;
- date/base date;
- region;
- currency;
- unit;
- work/material split;
- manufacturer/tier where relevant;
- source document;
- review/quality status.

## Декомпозиция

1. canonical item normalization;
2. candidate retrieval/matching;
3. work/material rate estimation;
4. uncertainty/abstention;
5. deterministic multiplication by quantity.

## Leakage

Запрещён leakage того же проекта/объекта в test через дубликаты ВОР/КП/revisions.

Для temporal pricing evaluation — источники после target date не должны попадать в inference, если тестируется историческое прогнозирование.

## Baseline before model

Сначала:
- exact/normalized match;
- nearest historical rows;
- robust median/weighted rate baseline.

Только потом learned mapper/estimator.

## Metrics

- item mapping accuracy;
- supported row coverage;
- work rate error;
- material rate error;
- total supported amount APE/WAPE;
- calibration/abstention;
- unsupported share.

## Guard

Подготовить code/config/tests/commands. Не запускать тяжёлое обучение без команды владельца.

Создать `MEP_PRICING_MODEL_PLAN.md`.


---

# PROMPT 11 — Отдельная 3-этапная MEP experiment page в Quantor

## Цель

Реализовать именно пользовательскую 3-этапную гипотезу, изолированно под feature flags.

## Этап 1 — Распознавание документации / MEP semantic extraction

Base recognition не переписывается.

UI должен:
- выбрать уже загруженный план одного этажа стадии П;
- использовать существующий base page/image/vector/OCR result;
- запустить/показать новый MEP semantic extractor;
- overlay по MEP entities;
- переключатели типов: risers, terminals, equipment, visible routes, labels/attributes;
- confidence/provenance;
- unresolved/ambiguous;
- source hash/model version;
- кнопку `Зафиксировать распознанный вход`.

Для benchmark/dev режима можно показать human GT overlay отдельно, но production mode не должен требовать ручных anchors.

## Этап 2 — Отрисовка системы уровня РД

Показать:
- исходный план;
- EvidenceGraph anchors;
- generated NetworkGraph;
- observed vs inferred layers;
- topology inspector;
- validation issues;
- lengths/counts;
- confidence/provenance;
- generator version/hash;
- кнопку `Зафиксировать систему`.

Reference RD скрыта до blind reveal.

## Этап 3 — ВОР + расценивание

Таблица:
- item;
- system;
- unit;
- quantity;
- quantity provenance;
- work rate;
- material rate;
- total;
- historical analog/source;
- date/region/currency;
- confidence;
- review flag.

Controls:
- STRICT / ESTIMATE;
- quantity-only / priced;
- export через существующие utilities, если есть.

## Experiment panel

- run id;
- base recognition hash;
- MEP semantic model version;
- EvidenceGraph hash;
- P→RD model/version;
- NetworkGraph hash;
- quantity/pricing versions;
- frozen output hashes;
- blind-test status.

## Mock mode

UI должен работать на schema fixtures без GPU weights.

## Isolation

- flags OFF → production unchanged;
- no base model training;
- no source mutation;
- no blind reference reveal before freeze;
- existing regressions pass.


---

# PROMPT 12 — Слепой тест одного этажа: isolated + end-to-end

## Цель

Проверить три этапа и локализовать источник ошибки.

Выбрать held-out проект/этаж/subsystem, отсутствующий во всех train/val corpora MEP detector, P→RD generator и Pricing.

## До запуска зафиксировать

- project/floor/subsystem;
- stage P source hash;
- base recognition snapshot hash;
- hidden human GT MEP EvidenceGraph hash;
- hidden/reference RD hash;
- hidden reference VOR hash;
- hidden price reference/date where available;
- model/code versions;
- thresholds;
- split proof.

## Track A — Generation-isolated

1. Открыть **human GT EvidenceGraph** только как вход генератора; RD/VOR/prices остаются скрыты.
2. P→RD generation.
3. Freeze NetworkGraph.
4. Quantity STRICT.
5. Freeze BOQ.
6. Pricing supported rows.
7. Freeze final output.
8. Reveal RD/VOR/prices.

Track A отвечает: способен ли generator+BOQ+pricing решить задачу при идеальном Stage 1 evidence.

## Track B — End-to-end

1. Base recognition frozen input.
2. MEP semantic extraction.
3. Freeze EvidenceGraph.
4. P→RD generation.
5. Freeze NetworkGraph.
6. Quantity STRICT.
7. Pricing.
8. Freeze.
9. Reveal all references.

## Score vector

### Stage 1 MEP semantic
- critical entity precision/recall/F1;
- relation F1;
- attribute known-only accuracy;
- critical anchor coverage;
- unresolved share.

### Stage 2 engineering
- terminal connectivity;
- network validity;
- topology edge F1;
- branch/junction correctness;
- route coverage/distance;
- total route length error;
- attribute accuracy;
- valid alternatives;
- unresolved.

### Stage 3 quantities
- line coverage;
- quantity WAPE;
- missing/extra;
- pipe/fitting/device breakdown.

### Pricing
- supported coverage;
- mapping accuracy;
- work/material rate error;
- final supported total error;
- confidence calibration.

## Error attribution

Посчитать разницу Track A vs Track B.

Verdict может быть:
- `PASS_TO_MORE_FLOORS`;
- `HOLD_MEP_SEMANTIC`;
- `HOLD_GENERATION`;
- `HOLD_QUANTITY`;
- `HOLD_PRICING`;
- `HOLD_DATA`.

Создать immutable receipts JSON + `MEP_ONE_FLOOR_BLIND_REPORT.md`.


---

# PROMPT 13 — Финальная приёмка гипотезы v3

## Цель

Собрать объективный итог без расползания scope.

Создать `MEP_P_TO_RD_HYPOTHESIS_RESULT.md`.

## Проверить

### Base isolation
- base recognition behavior/regressions unchanged;
- existing weights/datasets untouched;
- no duplicate PDF/OCR pipeline;
- feature flags isolation.

### MEP semantic extraction
- label schema/data quality;
- project-heldout split;
- baseline vs learned;
- critical anchor coverage;
- relation quality;
- calibration/unresolved;
- Track B degradation relative Track A.

### P→RD
- paired P/RD evidence;
- HUMAN_GT vs MODEL_EXTRACTED input performance;
- baseline vs learned;
- connectivity/validity/topology/geometry;
- valid alternatives;
- learning curve.

### BOQ
- deterministic reproducibility;
- coverage/WAPE;
- STRICT/ESTIMATE separation;
- source traceability.

### Pricing
- historical coverage;
- leakage/temporal checks;
- mapping/rate/total errors;
- abstention.

### Portal
- exactly 3 user stages;
- Stage 1 = base reuse + MEP semantic extraction;
- Stage 2 = generated RD network;
- Stage 3 = BOQ/pricing;
- blind reveal and hashes work.

## Final verdict — один основной

- `GO_NARROW` — гипотеза доказана для текущего ВК scope;
- `HOLD_MEP_SEMANTIC`;
- `HOLD_DATA`;
- `HOLD_GENERATION`;
- `HOLD_QUANTITY`;
- `HOLD_PRICING`;
- `NO_GO`.

Если GO_NARROW — не расширять сразу на все ВИС. Предложить следующий ближайший subsystem и конкретный data target.

Owner-facing summary на 1 страницу:
- что проверили;
- данные;
- Track A vs Track B;
- точные метрики;
- где основной error budget;
- сколько данных нужно дальше;
- следующий безопасный шаг.


---

# DATA REQUIREMENTS v3 — три разных набора данных

Это planning targets для эксперимента, **не обещание точности**. Финальный объём определяется learning curve на фиксированном project-heldout test.

## A. MEP Semantic Extraction dataset

Считать не «альбомы», а:
- независимые projects;
- annotated sheets/floors;
- instances по каждому critical entity type;
- relation instances;
- design organizations/symbol styles;
- negative/hard-negative pages;
- review quality.

### Первый feasibility batch

Ориентир для одного узкого ВК scope:
- **15–30 независимых проектов**;
- **80–200 размеченных планов/листов**;
- желательно сотни подтверждённых instances для каждого критичного редкого класса и тысячи суммарно по частым классам;
- отдельный project-heldout test минимум из нескольких независимых проектов.

Если символика сильно различается между проектировщиками, приоритет — diversity, а не число однотипных этажей.

### Working pilot

Ориентир:
- **50–100+ независимых проектов**;
- **400–1 000+ размеченных планов/листов**;
- достаточное покрытие редких классов/relations.

Реальный stop определяется per-class learning curve и downstream `critical_anchor_coverage`.

## B. P→RD Generator dataset — нужны именно парные П↔РД

### Feasibility / PoC одного subsystem
- **20–30 независимых проектов**;
- **40–60 парных комплектов/альбомов П↔РД**;
- примерно **150–300 usable floor-system pairs**.

### Working pilot
- **80–150 независимых проектов**;
- **150–250 парных комплектов**;
- **700–1 500 floor-system pairs**.

### Устойчивый контур одной дисциплины
- **200–400+ независимых проектов**;
- **400–700+ парных комплектов**;
- **2 000–5 000+ floor-system pairs**.

Эти диапазоны — стартовое планирование. Не собирать 700 альбомов «на веру»: строить learning curve.

## C. Pricing dataset

Считать очищенные исторические строки, а не Excel-файлы.

Для первого узкого PoC:
- ориентир **5k–10k+ reviewable historical rows**;
- unit/date/currency обязательны;
- work/material split where required;
- project/customer ids для leakage control.

Более устойчивый pilot:
- **25k–50k+** разнообразных качественных строк.

## Learning curves

Для каждого обучаемого слоя отдельно:
- 10%;
- 25%;
- 50%;
- 75%;
- 100% train corpus;

при неизменных validation/test projects.

## Почему два теста обязательны

`HUMAN_GT EvidenceGraph → P→RD` показывает ceiling генератора без detector noise.

`MODEL_EXTRACTED EvidenceGraph → P→RD` показывает production-like end-to-end.

Если первый тест слабый — больше MEP annotations не исправят генератор. Если первый сильный, второй слабый — инвестировать в semantic extractor.

## Stop/gate

Не переходить к широкому training, если:
- label taxonomy нестабилен;
- rare critical classes почти отсутствуют;
- project leakage;
- pairing P↔RD ненадёжный;
- RD target graph неточный;
- alignment систематически HOLD;
- pricing rows без unit/date/currency;
- ошибки baseline не классифицированы.


---

# ONE FLOOR RUNBOOK v3 — ВК / типовой жилой этаж

## Цель

За controlled run доказать/опровергнуть:

**base Quantor → MEP semantic → P→RD network → BOQ → pricing**

и отдельно проверить генератор без detector noise.

## Подготовка

Выбрать held-out project/floor/subsystem.

Подготовить и захешировать:
- stage P source;
- base recognition result;
- human GT MEP annotations/EvidenceGraph;
- reference RD — скрыт от generation;
- reference VOR — скрыт;
- reference prices — скрыты if available.

## Run A — Generation isolated

1. Human GT → `MepEvidenceGraph`.
2. Freeze evidence hash.
3. P→RD baseline/learned model.
4. Validate/freeze NetworkGraph.
5. STRICT BOQ.
6. Freeze quantity BOQ.
7. Pricing supported rows.
8. Freeze final result.
9. Reveal RD/VOR/prices.
10. Score.

## Run B — End-to-end

1. Existing Quantor base artifacts.
2. MEP semantic extractor.
3. Freeze `MepEvidenceGraph`.
4. P→RD.
5. Freeze NetworkGraph.
6. STRICT BOQ.
7. Pricing.
8. Freeze final.
9. Reveal refs.
10. Score.

## Suggested PoC engineering gates

Стартовые, не production SLA:
- critical Stage 1 anchor recall/coverage: target определить после class audit, но показывать per-class;
- required terminal connectivity ≥ 0.95;
- valid network rate = 1.00 для выбранного кейса;
- topology edge F1 ≥ 0.85 с valid-alternative review;
- total route length error ≤ 15%;
- quantity WAPE ≤ 15%;
- BOQ line coverage ≥ 90%;
- supported pricing total APE ≤ 15%;
- unresolved share всегда явно.

Не превращать эти стартовые gates в обещание production accuracy.

## Error budget

Обязательно вывести:
- Stage 1 semantic loss;
- Stage 2 generation loss при human GT;
- дополнительную generation loss от model-extracted evidence;
- BOQ loss;
- pricing loss.

Это должно отвечать владельцу, куда вкладывать следующий бюджет разработки/разметки.
