# PROMPT 22 — Kreo-like AI Geometry UX

Добавь pilot UI, не копируя визуальный бренд Kreo.

## Entry

AI action доступен только если:

- `takeoff.ai` feature enabled for workspace;
- selected project/sheet ready;
- compatible TakeoffItem selected/created;
- promoted local model task available.

## Flow

```text
[AI обводка]
  → выбрать задачу (только promoted task)
  → запустить job
  → progress/status
  → candidate layer appears
  → pending candidates list/count
  → click candidate ↔ highlight on drawing
  → preview quantity
  → accept / edit+accept / reject
```

## Layer behavior

- candidate layer отдельно от Recognition и Measurement;
- pending style visually distinct;
- accepted disappears from pending and ordinary Measurement appears without flicker/duplicate;
- rejected hidden by default, toggleable for audit;
- optional raw-mask evidence toggle only for selected candidate;
- thousands candidates use spatial index/culling from Prompt 04.

## Editing

Reuse Measurement vertex editing logic where possible, but candidate draft does not mutate
original Candidate. On accept creates final geometry.

## Accessibility/errors

Controlled messages for no scale, model unavailable, worker unavailable, failed job, no detections.
Не писать «0 найдено» при failed inference.

`takeoff.ai` остаётся default OFF. Не включать глобально.

Документ `docs/stage2b/19-ai-workspace-ux.md`.

STOP.
