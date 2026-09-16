# PROMPT 06 — Обучаемая модель P→RD (запускать после gate данных)

Не запускай обучение, пока dataset gate из PROMPT 04 и baseline из PROMPT 05 не приняты.

Спроектируй обучаемый P→RD модуль как **graph/topology completion + route geometry**, а не image-to-image generator.

Рекомендуемая декомпозиция:
A. Visual/document encoder — переиспользовать существующие full-sheet/high-res features и P EvidenceGraph.
B. Graph encoder — nodes/rooms/shafts/observed routes/attributes.
C. Connectivity head — предсказывает logical edges и тип связи.
D. Route head — предсказывает polyline/waypoints либо route cost field, после чего deterministic router даёт валидную трассу.
E. Attribute heads — size/material/elevation/accessory only when supervision exists.
F. Uncertainty head / abstention.

Losses/metrics должны быть typed:
- node match;
- edge/connectivity F1;
- terminal coverage;
- route distance / geometric coverage;
- branch/junction correctness;
- size/material exact on known-only targets;
- quantity error derived from predicted graph.

Не штрафуй модель за `UNKNOWN_NOT_NEGATIVE`.

Обязательный experimental protocol:
- frozen project-heldout split;
- learning curves 10/25/50/75/100%;
- compare against PROMPT 05 baseline;
- oracle Stage1 vs predicted Stage1;
- no checkpoint selection on test;
- report per project and per system, not only global micro average.

До GPU run подготовь code/config/tests/command and STOP. GPU training — только после явной команды владельца.
