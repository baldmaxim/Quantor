# PROMPT 24 — Live acceptance Stage 2B + handoff

Не выполнять acceptance только на mocks.

## A. Baseline regression

Свежий полный стенд:

- lint/typecheck/api-client/build;
- all API/web/admin tests with required DB tests actually executed;
- measurement benchmark;
- viewer @266% live pan check.

## B. Private PlanSwift benchmark

На замороженном holdout ещё раз воспроизвести selected model metrics из Prompt 18 и убедиться,
что hashes/config совпадают.

## C. Real Quantor end-to-end

На одном реальном PDF sheet:

1. page geometry exists;
2. manual ScaleCalibration exists (если хотим physical preview);
3. создать/выбрать compatible TakeoffItem;
4. запустить AI job;
5. job реально взял vision worker;
6. raw mask artifact сохранён;
7. candidate vectors видны и совпадают с drawing;
8. pending candidates не изменили working total;
9. accept one candidate;
10. появился Measurement(source=ai);
11. Quantity рассчитан существующим rule;
12. edit+accept another — correction сохраняет original prediction;
13. reject third — Measurement не появился;
14. refresh/restart — состояние воспроизводимо;
15. cross-tenant attempts fail;
16. feature OFF — AI UI/runtime entry hidden/forbidden.

## D. Acceptance gates

Сверить все 28 gate из reference. `PASS` только с evidence. `BLOCKED` не считать PASS.

## E. Feature flags

Если production integration gates зелёные:

- `takeoff.ai` сделать admin-editable + workspace-scoped, default **OFF**;
- включение только pilot workspace делает владелец;
- `models.gateway` не включать, если generic gateway по факту не реализован/не нужен этому pilot.

## F. Handoff

Создай:

```text
docs/stage2b/21-acceptance.md
docs/stage2b/HANDOFF_TO_STAGE2C.md
```

В handoff отдельно написать:

- что доказано только within-project;
- model/weights hashes;
- current dataset counts;
- где нужны новые independent PlanSwift projects;
- error taxonomy;
- что делать следующим: больше datasets, semantic classification/VLM, additional construction classes;
- чего НЕ делать: Revit generation / automatic scale / full VOR без отдельного этапа.

STOP. Следующий Stage 2C автоматически не начинать.
