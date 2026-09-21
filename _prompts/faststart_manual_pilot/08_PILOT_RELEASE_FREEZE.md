# PROMPT 08 — Pilot Release Freeze (фиксация ручного пилота)

**Модель:** Opus 5  
**Режим мышления:** средне-высокий  
**Запускать только если PROMPT 07 дал `READY_FOR_MANUAL_PILOT = YES`.**

Цель — превратить прошедший приёмку код в понятную контрольную точку, не добавляя функций.

## 1. Обнови состояние продукта

Обнови только актуальные документы:

- `README.md` — убрать ложное впечатление, что проект только Stage 1;
- `docs/pilot/MANUAL_PILOT_READINESS.md`;
- `docs/mep/MEP_EXPERIMENT_STATE.md` — добавить отдельный раздел про manual pilot, не менять Р-MEP-16;
- при необходимости `CLAUDE.md` — коротко зафиксировать новую рабочую границу.

## 2. Зафиксируй две независимые линии

### Рабочий manual pilot (ручной пилот)

```text
raw PDF
→ manual takeoff / HUMAN_GT
→ manual network
→ Quantity Engine
→ physical BOQ
→ export
```

### Будущий AI track (контур ИИ)

```text
MEP semantic extraction
→ EvidenceGraph MODEL_EXTRACTED
→ P→RD generation
→ тот же NetworkGraph
→ тот же Quantity Engine
```

Не смешивать статусы готовности этих двух линий.

## 3. Freeze (заморозка) пилотной контрольной точки

Запиши решение вида `R-MEP-MANUAL-1` (или по принятой нумерации проекта):

- manual pilot принят;
- какие flags должны быть OFF по умолчанию;
- что разрешено пилотным пользователям;
- известные ограничения;
- какие функции всё ещё запрещены без отдельного решения (AI training, pricing, Customer VOR, BIM, fitting rules).

Не переиспользуй номер существующего решения.

## 4. Финальный regression run (регрессионный прогон)

Ещё раз:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm lint:licenses
pnpm api-client:check
```

Проверь, что A/B/C/D MEP regression fixtures сохранены.

## 5. Release notes (заметки о версии)

Создай `docs/pilot/MANUAL_PILOT_V0_1_RELEASE.md`:

- что пользователь уже может делать;
- 10-шаговый рабочий сценарий;
- что пока делается вручную;
- что автоматически;
- какие ограничения;
- как включить `takeoff.manual` и `mep.manual_pilot_v1`;
- как выключить пилот без потери данных.

## 6. Review ZIP

Создай `review/QUANTOR_FASTSTART_P08_REVIEW.zip`.

Коммит не делай. В конце предложи один русский commit message (сообщение коммита) для владельца, но не выполняй commit.

После отчёта остановись.
