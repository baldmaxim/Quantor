# PROMPT 10 — Отдельная страница эксперимента в портале Quantor

Создай отдельную страницу под feature flag `mep_rd_hypothesis_v1`. Не встраивай MVP в основной производственный takeoff flow.

Страница должна визуально проводить пользователя через 3 шага:

### 1. Распознавание документации
- upload/select stage P PDF;
- выбор page/floor/system;
- original plan + Stage1 overlay;
- detected entities table;
- scale/conflicts/unresolved;
- кнопка `Зафиксировать Stage 1`.

### 2. Отрисовка системы
- generated network overlay на исходном плане;
- layer toggles: observed / inferred / rule-derived / unresolved;
- node/edge inspector;
- topology validation panel;
- summary lengths/counts;
- кнопка `Зафиксировать Stage 2`.

### 3. ВОР и расценивание
- normalized BOQ table;
- columns: work item, unit, quantity, quantity source, work rate, material rate, total, rate source, confidence;
- STRICT / ESTIMATE toggle;
- export JSON/XLSX if existing portal export utility supports it.

Отдельный panel `Evaluation` показывать только в experiment mode:
- metrics by stage;
- run/model ids;
- reference RD reveal button disabled until output fixed;
- diff overlay after reveal.

Добавь mock/demo mode, чтобы UI можно было проверить без ML weights.
