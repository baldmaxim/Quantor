# PROMPT 06 — Scale calibration UI in viewer

Реализуй первый пользовательский инструмент Stage 2A — ручной Scale.

## Tool flow

```text
Scale tool
→ click A
→ click B
→ modal/inspector: known distance + unit
→ preview factor + scope
→ confirm
→ POST calibration
→ show calibration badge on sheet
```

## UX требования

- crosshair / visible A-B line while choosing;
- `Esc` cancels without server write;
- input supports mm/cm/m, no locale ambiguity in API;
- no auto-trust of text `1:100`;
- after save show source=Manual and status;
- if more than one calibration exists, user can choose default/current calibration;
- prepare UI to show local scale scope, but do not overbuild viewport editor if not yet needed;
- no scale → explicit `Масштаб не задан`, not 0 and not guessed value.

## Architecture

Scale draft state must not be stored in global React state on every pointermove.
Do not rerender PDF base while moving A/B.

Use generated API client. Handle 401/403/404/409/domain errors consistently with portal.

## Tests

- two-click flow;
- cancel;
- keyboard;
- zoom/pan between A and B preserves normalized points;
- reload shows saved calibration;
- wrong permissions hide UI but backend test remains authoritative;
- no network call during pointermove.

STOP with screenshots only if the environment can actually produce them; otherwise do not claim visual verification.
