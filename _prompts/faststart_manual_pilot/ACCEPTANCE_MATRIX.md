# Acceptance Matrix (матрица приёмки) — Quantor Manual Pilot v0.1

| Gate (гейт) | Минимальный результат | Можно работать после него |
|---|---|---|
| P00 | baseline чист/понятен | нет |
| P01 | raw PDF открывается без recognition ZIP | частично: просмотр |
| P02 | ручной обмер + калибровка + CSV | **да: обычный ручной QTO** |
| P03 | реальная MEP-страница + persistence | подготовка MEP |
| P04 | HUMAN_GT EvidenceGraph | **да: ручная MEP-разметка** |
| P05 | ручной MepNetworkGraph | **да: ручная отрисовка сети** |
| P06 | реальный physical BOQ + export | **да: полный ручной MEP-пайплайн** |
| P07 | живая E2E-приёмка, critical bugs fixed | **готово к пилоту** |
| P08 | документы/заморозка контрольной точки | стабильная версия пилота |

## Definition of Done (критерий готовности) для начала эксплуатации

Обязательные:

- raw PDF загружается и открывается;
- feature flags работают deny-by-default;
- manual takeoff сохраняется после reload;
- MEP evidence/network сохраняются после reload;
- EvidenceGraph и NetworkGraph валидируются контрактами v0.3;
- Quantity Engine считает только из NetworkGraph;
- BOQ partial/refused не маскируется под complete;
- traceability BOQ → Network → Evidence → Sheet работает;
- CSV формируется серверными данными;
- доступ между workspace не протекает;
- клиентские данные не попадают в Git;
- полный доступный lint/typecheck/test/build PASS;
- A/B/C/D остаются постоянными regression fixtures.

Необязательные для v0.1:

- AI detection (автораспознавание);
- P→RD auto generation (автогенерация П→РД);
- pricing (расценивание);
- fitting/support/insulation rules (правила фитингов/опор/изоляции);
- Customer VOR;
- Revit/IFC;
- OCR/PageRasterProvider;
- multi-floor 3D solver (межэтажный 3D-решатель).
