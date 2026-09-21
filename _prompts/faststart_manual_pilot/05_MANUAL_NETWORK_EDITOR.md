# PROMPT 05 — Manual Network Editor (ручная отрисовка инженерной сети)

**Модель:** Opus 5  
**Режим мышления:** высокий  
**Цель:** инженер вручную строит сеть уровня РД на реальном плане, а Quantor сохраняет валидный `MepNetworkGraph` с `HUMAN_CONFIRMED` provenance (происхождением «подтверждено человеком»).

## 1. Никакой генерации

На этом этапе нет:

- retrieval;
- P→RD model;
- routing model;
- auto-connect;
- topology inference.

Человек заменяет будущий генератор.

## 2. Минимальная модель ручной сети

Пользователь должен уметь:

1. создать node (узел) на плане;
2. выбрать node role/class/system из профиля;
3. создать/назначить ports (порты) минимально необходимым способом;
4. соединить два узла segment (участком) polyline;
5. указать system;
6. указать profile parameters (например размер/материал — только если профиль это допускает);
7. добавить промежуточные вершины трассы;
8. редактировать/удалять draft;
9. пометить unresolved decision (нерешённое решение), если данных не хватает.

Для v0.1 разреши простое правило: **сначала узлы, потом участки между явными узлами**. Не нужно автоматически создавать junction (разветвление) из пересечения линий.

## 3. Snapping (привязка)

Минимальный snapping только для удобства ручной работы:

- к существующему node/port;
- к endpoint (концу) редактируемого segment.

Не делать геометрическое распознавание пересечений/стен/шахт.

## 4. Связь с Evidence

Для выбранного node/segment пользователь может вручную указать evidence references (ссылки на evidence), если элемент основан на стадии П.

Derivation (происхождение):

- `HUMAN_CONFIRMED`;
- evidence_ids — если есть реальная опора;
- без evidence_ids допустимо только если человек явно создал элемент как проектное решение и UI это показывает как «добавлено вручную, на П не показано».

Не выдавай ручное решение за `EVIDENCE_OBSERVED`.

## 5. Контракт

Сервер собирает настоящий `MepNetworkGraph v0.3` из ручной сети и запускает существующие validators.

Используй:

- реальный `MepEvidenceGraph` текущей сессии;
- тот же profile ref/hash;
- реальные sheet/calibration snapshots;
- `GenerationProvenance.HUMAN_CONFIRMED`.

Если для контракта нужен Tool/Run, задай честный deterministic manual tool (ручной инструмент) с версией; не имитируй ML model run (прогон ML-модели).

Не менять contract v0.3 ради удобства UI без доказанного blocker (блокера). Если blocker найден — остановись и сначала отчитай его.

## 6. Validation UX (интерфейс проверки)

Показывай пользователю понятные ошибки:

- segment без start/end node;
- system mismatch;
- отсутствующий обязательный parameter;
- invalid topology по profile rule;
- calibration missing (если Quantity Engine потом требует длину);
- unresolved decisions.

Разделяй `warning` и `error`.

## 7. Не строить 3D сейчас

UI работает на одном листе/этаже в 2D.

Контракт может хранить z/level, но editor не обязан реализовывать полноценную 3D-работу.

## 8. Acceptance

На fixture/реальном листе руками построить:

- source/riser node;
- junction;
- 2 terminal nodes;
- 3+ segments;
- два разных размера/параметра;
- хотя бы один элемент с evidence link;
- хотя бы один элемент без evidence, но с честным human-confirmed provenance;
- один unresolved warning.

Reload → сеть та же. `validate_network_graph` проходит либо выдаёт только ожидаемый unresolved/warning.

## 9. Не делать

- fitting rules;
- obstacle routing;
- auto-generation;
- BIM;
- pricing.

## 10. Review ZIP

Создай `review/QUANTOR_FASTSTART_P05_REVIEW.zip`.

После отчёта остановись. Не запускай Quantity/Export prompt.
