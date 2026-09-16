# PROMPT 01 — Аудит репозитория и каркас эксперимента

На базе PROMPT 00 проведи реальный аудит текущего репозитория Quantor и создай минимальный изолированный каркас эксперимента.

Требуется:
1. Найти текущий ingest PDF, page/view classification, source transforms, OCR/text extraction, vector path extraction, overlay/render, JSON schema validation, experiment/result storage и frontend/router.
2. Составить карту переиспользования: `существующий компонент → роль в MEP эксперименте → нужен ли adapter`.
3. Создать модуль/namespace эксперимента без копирования всего существующего pipeline.
4. Добавить feature flag `mep_rd_hypothesis_v1`, выключенный по умолчанию.
5. Добавить пустой endpoint/service contract для трёх стадий:
   - `recognize_floor`
   - `generate_rd_network`
   - `build_and_price_boq`
6. Добавить experiment manifest с hash исходного PDF, page index, discipline, floor, model/build ids, timestamps, stage statuses.
7. Добавить тест, подтверждающий, что при выключенном feature flag существующий продукт работает без изменений.

Не реализуй ML и не придумывай данные. В конце выведи:
- изменённые файлы;
- схему вызовов;
- команды тестов;
- blockers.
