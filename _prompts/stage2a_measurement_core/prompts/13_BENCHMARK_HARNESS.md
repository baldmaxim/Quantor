# PROMPT 13 — Benchmark harness Stage 2A

Создай воспроизводимый benchmark отдельно от unit tests.

## CLI

Например:

```bash
pnpm benchmark:measurement
```

или единая команда, запускающая Python geometry/calculation benchmark и frontend overlay benchmark.
Не подменять benchmark обычным pytest output.

## Dataset format

Создай versioned manifest, где case содержит:

```text
case_id
page geometry / sheet ref
calibration evidence
measurement geometry
expected quantity
unit
tolerance
source_note
```

Synthetic cases хранятся в repo. Live cases могут ссылаться на локальный fixture и не должны
коммитить 50–500 МБ PDF без решения владельца.

## Metrics

Для math:

- absolute error;
- relative error;
- pass/fail tolerance;
- repeatability.

Для API:

- list/create/update/batch latency на живой БД, если доступна;
- query count / N+1.

Для overlay:

- draw time 1k / 5k / 10k primitives;
- memory snapshot if measurable;
- bundle delta.

Не ставь маркетинговую цель типа «60 FPS» без измерения среды. Сначала baseline, затем вывод.

## Output

Machine-readable JSON + human markdown report under `docs/stage2a/`.
Все числа с environment metadata.

STOP.
