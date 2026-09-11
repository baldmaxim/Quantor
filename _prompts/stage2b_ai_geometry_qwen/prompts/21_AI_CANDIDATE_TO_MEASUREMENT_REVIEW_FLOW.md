# PROMPT 21 — Accept / edit / reject AI candidate

## Critical invariant

Pending candidate **не входит** в существующий Sheet/Takeoff total.

## Workflow

User выбирает target TakeoffItem совместимого geometry type и candidate:

- Accept as-is → trusted server service creates Measurement(source=ai);
- Edit then accept → creates Measurement(source=ai) with edited geometry, original candidate kept;
- Reject → no Measurement;
- Re-review accepted candidate cannot create second Measurement.

Measurement metadata/reference содержит candidate id. Нельзя прислать `source=ai` через manual
create endpoint.

## Verification/audit

Добавь review actor/time/note/state на Candidate. Не заставляй менять существующую semantic
VerificationState scale calibration.

Audit:

- AI run requested;
- candidate accepted/rejected;
- geometry edit summary/hash, не мегабайты координат;
- created measurement id.

## Preview quantity

Candidate preview можно считать существующим deterministic engine in-memory, но label UI/API
явно `preview / not included`. Если нет ScaleCalibration — `unavailable`, не zero.

## Concurrency

Double click / two reviewers → one accepted Measurement. Использовать DB constraint/transaction,
не только frontend disable button.

Документ `docs/stage2b/18-review-flow.md`.

STOP. Контрольная точка владельца.
