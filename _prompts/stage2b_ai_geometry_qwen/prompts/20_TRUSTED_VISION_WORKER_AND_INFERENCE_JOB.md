# PROMPT 20 — Trusted Vision Worker + server-side raster inference

Выполнять только для model task, прошедшего Prompt 18.

## Separate process

Torch/SAM/PDF raster dependencies не входят в API worker process. Сделай отдельный
vision-worker/runtime boundary с bounded concurrency и явной GPU/CPU configuration.

## Job

Добавь project-scoped job type, например `ai_geometry_predict`. Job payload содержит IDs,
не binary. Tenant/workspace scope следует существующим rules.

API только ставит задание. Vision worker:

1. получает immutable revision/sheet;
2. читает PDF/object;
3. server-side rasterizes controlled tiles;
4. runs selected promoted model;
5. сохраняет raw mask artifact;
6. vectorizes versioned pipeline;
7. writes PredictionRun/Candidates transactionally;
8. marks Job status/progress.

## PDF renderer

Для pypdfium2 сначала зафиксировать license/third-party notices. Render transform обязан быть
проверен против canonical PageGeometry и browser geometry на synthetic/real pages. Rotation
не применять дважды.

## Promoted pipeline loading

Runtime обязан исполнять **только pipeline ID, прошедший Prompt 18**. Поддержи pipeline adapter boundary, чтобы production мог быть:

- small segmentation only;
- SAM/refiner chain;
- Qwen→SAM hybrid;
- другой explicitly promoted candidate.

Если победил Qwen LoRA:

- не предполагай, что vLLM/SGLang поддерживает vision LoRA именно в текущей версии;
- сначала сделай runtime compatibility smoke;
- разрешены merged weights или Transformers/другой local runtime, если benchmark и license/provenance сохранены;
- training dependency Unsloth не обязана и предпочтительно не должна присутствовать в inference image;
- не подключать remote API для client drawings на этом этапе.

## Model loading

- lazy/load once per worker;
- weights verified by SHA-256 before use;
- model id/version allowlisted/promoted, не arbitrary path from user;
- no pickle/untrusted model upload execution;
- timeout/cancel/lease heartbeat;
- OOM gives controlled job error, не убивает очередь молча.

## No remote provider

Текущий pilot — local/on-prem only. Не отправлять source drawing во внешний cloud API.

Документ `docs/stage2b/17-vision-worker.md`.

STOP.
