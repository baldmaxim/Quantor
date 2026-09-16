# PROMPT 09 — Слепой end-to-end протокол на одном этаже

Подготовь blind experiment для одного held-out этажа.

До запуска зафиксируй:
- project/floor/system id;
- hash стадии П;
- hash reference РД;
- hash reference ВОР/расчёта;
- versions моделей и кода;
- acceptance thresholds.

Reference РД/ВОР не должен быть доступен inference процессу до завершения и фиксации output hash.

Run A: oracle Stage1 → Stage2 → Quantity → Pricing.
Run B: predicted Stage1 → Stage2 → Quantity → Pricing.
Run C: baseline PROMPT 05.

После фиксации outputs открой reference и посчитай три независимых score:
1. **Recognition score** — насколько правильно прочитана П.
2. **Engineering score** — topology/connectivity/validity/route/attributes vs RD + rule validation.
3. **Commercial score** — item coverage, quantity error, rate error, total error.

Не использовать одну “точность 95%”. Показывать metric vector.

Отдельно посчитай `valid_alternative_score`: если generated route отличается от reference RD, но проходит constraints и даёт сопоставимый quantity, не считать его автоматически ошибкой.

Сгенерируй immutable `blind_test_receipt.json`.
