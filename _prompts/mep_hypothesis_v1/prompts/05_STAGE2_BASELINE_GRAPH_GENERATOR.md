# PROMPT 05 — Stage 2 baseline без тяжёлого обучения

До нейросетевого генератора сделай проверяемый baseline P→RD, чтобы проверить данные, contracts, портал и метрики.

Input: `MepEvidenceGraph` или `oracle_stage1.json`.
Output: `MepNetworkGraph candidate`.

Baseline должен состоять из:
1. Retrieval: найти несколько наиболее похожих TRAIN-кейсов РД по типологии этажа, расположению стояков/приборов, площади и room graph. Никогда не искать в held-out project.
2. Logical graph completion: предложить connectivity между стояками и terminal nodes на основе retrieved patterns.
3. Deterministic router: построить полилинии по допустимому пространству, избегая запрещённых областей; стоимость маршрута = длина + повороты + crossing penalties + shaft/zone constraints.
4. Parameter fill: переносить размер/материал только когда есть подтверждённое правило/retrieval evidence; иначе unresolved.
5. Topology validator: нет dangling required endpoints, incompatible ports, cross-system contamination.

Важно: baseline нужен не как production решение, а как нижняя граница. Если он уже даёт близкий ВОР, это экономит месяцы обучения.

Сравни:
- retrieval-only;
- retrieval + deterministic routing;
- actual RD.

Сохрани каждое решение и его provenance.
