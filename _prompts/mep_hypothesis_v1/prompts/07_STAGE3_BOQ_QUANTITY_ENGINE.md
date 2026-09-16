# PROMPT 07 — Stage 3A. Из MepNetworkGraph в полный ВОР

Сделай детерминированный Quantity Engine. Он не должен “угадывать цену” и не должен скрывать ошибки сети.

Для ВК v1 derive:
- длины труб по system + material + diameter;
- количество fittings по topology/turns/diameter changes;
- valves/accessories by graph objects;
- equipment/fixtures counts;
- insulation length/area if rule and source attributes sufficient;
- supports only если есть утверждённый rule/spacing contract; иначе отдельный unresolved/allowance lane;
- penetrations only при доказанном пересечении конструкций;
- demolition/existing works не выводить без явного source.

Каждая строка ВОР обязана ссылаться на source node/edge ids и иметь `quantity_provenance`.

Сделай два режима:
1. `STRICT`: только доказуемые quantities;
2. `ESTIMATE`: допускает rule-derived allowances, но маркирует их отдельно.

Сравни generated ВОР с reference ВОР/RD takeoff:
- item coverage;
- missing/extra items;
- WAPE/MAPE quantities;
- total route length error;
- error by diameter/material/system;
- share unresolved.

Не смешивай pricing с quantity accuracy.
