# PROMPT 06 — Real BOQ & Export (реальный физический ВОР и экспорт)

**Модель:** Opus 5  
**Режим мышления:** высокий  
**Цель:** ручной `MepNetworkGraph` проходит через уже существующий Quantity Engine 0.3.1, а пользователь получает физический ВОР и выгружает его.

## 1. Главное правило

Не переписывай `build_boq()`.

Реальный ручной pipeline должен использовать тот же Quantity Engine, который уже проверен на A/B/C/D.

Схема:

```text
saved HUMAN_GT evidence
→ saved HUMAN_CONFIRMED network
→ validate
→ build_boq(network, profile, evidence)
→ validate_boq
→ UI + export
```

## 2. BOQ status

Сохрани существующие смыслы:

- complete;
- partial;
- refused;
- blockers/warnings;
- review_required;
- typed source refs;
- source contributions;
- group value provenance;
- participants.

Не превращай partial/refused в «0».

## 3. UI шага 3

На реальной MEP-странице показать:

- physical BOQ / calculated takeoff;
- явно: «это не финальный ВОР Заказчика»;
- rule/class/group;
- quantity/unit;
- source contributions;
- review_required;
- blockers/warnings;
- trace navigation: BOQ row → network element → evidence → location on sheet.

Переиспользуй компоненты MOCK-страницы там, где это можно сделать без изменения frozen fixtures/semantics (замороженных фикстур/смыслов). Общий UI-компонент можно вынести, если это уменьшает дублирование и не ломает regression tests.

## 4. Export

Добавь:

### CSV — обязательно

Строки физического ВОР + provenance-friendly поля (поля происхождения):

- rule key/version;
- class/group;
- quantity/unit;
- source refs;
- review_required;
- status;
- blockers code where applicable;
- network graph hash;
- evidence graph hash;
- Quantity Engine version.

### XLSX — желательно, если можно сделать без тяжёлой новой зависимости

Если в проекте уже есть безопасная библиотека/паттерн для XLSX — используй. Если нет — не добавляй новую тяжёлую зависимость ради пилота; CSV достаточно и зафиксируй `XLSX_DEFERRED`.

## 5. Determinism (детерминизм)

Один и тот же сохранённый graph/profile/evidence должен давать идентичный BOQ и экспорт после reload.

Хеши входов должны быть в export metadata (метаданных экспорта).

## 6. Acceptance

Ручной сценарий из P05 должен:

- получить длины/счёт;
- дать partial при намеренно unresolved parameter;
- после ручного заполнения параметра стать complete, если иных блокеров нет;
- строка BOQ открывает правильный segment/node;
- segment/node показывает evidence link, если он есть;
- CSV совпадает с API/экраном.

## 7. Что не делать

- Customer VOR mapping;
- pricing;
- fittings/изоляция/крепёж без утверждённых правил;
- AI inference;
- Revit/IFC.

## 8. Review ZIP

Создай `review/QUANTOR_FASTSTART_P06_REVIEW.zip`.

После отчёта остановись.
