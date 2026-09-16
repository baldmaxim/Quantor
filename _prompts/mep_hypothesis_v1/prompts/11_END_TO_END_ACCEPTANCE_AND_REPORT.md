# PROMPT 11 — Финальная приёмка гипотезы

Проведи полную приёмку эксперимента и создай `MEP_HYPOTHESIS_RESULT.md`.

Минимум проверь:
- feature flag isolation;
- schema validation;
- deterministic reproducibility of quantity engine;
- project-heldout split and leakage audit;
- blind receipt integrity;
- Stage1 metrics;
- Stage2 topology/connectivity/route/quantity metrics;
- Stage3 BOQ/pricing metrics;
- unresolved rate;
- runtime/VRAM/latency where measured;
- portal UX with mock and real run;
- no regression in existing Quantor flows.

Verdict только один из:
- `GO_NARROW`: гипотеза доказана для выбранного узкого subsystem;
- `HOLD_DATA`: архитектура разумна, данных недостаточно;
- `HOLD_RECOGNITION`: Stage1 ломает end-to-end;
- `HOLD_GENERATION`: P→RD prior/topology недостаточны;
- `HOLD_BOQ`: сеть приемлема, quantity mapping слабый;
- `HOLD_PRICING`: quantities приемлемы, pricing слабый;
- `NO_GO`: гипотеза в выбранной постановке не подтверждается.

Не расширяй scope автоматически. Для GO_NARROW предложи следующий subsystem и конкретный data target.
