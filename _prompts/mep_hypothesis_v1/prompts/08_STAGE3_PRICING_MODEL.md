# PROMPT 08 — Stage 3B. Расценивание ВОР отдельной моделью

Реализуй pricing как отдельный слой поверх нормализованного `MepBoq`.

Data contract исторической строки:
- normalized work code / canonical description;
- original description;
- system;
- unit;
- quantity;
- work rate;
- material rate;
- total;
- date;
- region;
- currency;
- building class;
- brand/manufacturer tier if known;
- contractor/customer/project ids;
- source document hash;
- confidence/review status.

Архитектура v1: retrieval + normalization + robust regression/LLM ranker, а не чистая генерация числа из текста. Показывай nearest historical analogs и дату цены.

Обязательные guards:
- unit compatibility;
- date/currency normalization;
- region factor separated;
- no rate when training support is insufficient → review;
- no leakage по project/customer в test where relevant.

Метрики:
- top-k mapping accuracy to canonical work code;
- work/material rate MAPE/median APE;
- total estimate error;
- calibration by confidence;
- coverage at confidence threshold.

UI должен показывать: quantity, unit rate, work/material split, analogs, provenance, confidence.
