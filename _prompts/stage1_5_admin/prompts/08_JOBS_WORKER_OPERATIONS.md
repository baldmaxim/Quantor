# PROMPT 08 — Jobs / worker operational boundary

Stage 1 handoff указывает, что jobs исполняются внутри API process. До тяжёлого Stage 2 это надо исправить либо доказанно изолировать.

## Сначала audit current Job abstraction

Не меняй API contract `Job` без необходимости.

## Требование

Тяжёлые import/recognition/QTO jobs не должны занимать request worker.

Выбери минимально сложный устойчивый вариант, совместимый с текущей архитектурой. Предпочтительно сначала рассмотреть отдельный worker process с PostgreSQL-backed claiming (`FOR UPDATE SKIP LOCKED`) и existing Job state, чтобы не вводить Redis/Temporal/Celery только ради Stage 1.5. Если текущая архитектура явно лучше подходит другому executor — обоснуй ADR.

## Job lifecycle

Минимум:

```text
queued
running
succeeded
failed
cancel_requested/cancelled (только если реально поддержано)
```

Добавить:

- attempt count;
- lease/heartbeat or stale job recovery;
- worker id;
- started/finished timestamps;
- error code + safe message;
- idempotency boundaries;
- retry policy only for retryable errors.

## Admin Jobs page

Показывать:

- state;
- type;
- project/document context;
- duration;
- attempts;
- worker;
- safe error;
- retry action only if allowed/idempotent;
- filters.

Не показывать raw request payload with secrets/document contents.

## Health

`/health/ready` или dedicated operational endpoint должен различать API ready vs worker unavailable, не ломая read-only portal при временно недоступном worker.

## Load test

Проверить concurrent imports на живом test package/копиях без блокировки API response workers.

Числа latency/throughput в отчёте только реально измерить.

STOP.
