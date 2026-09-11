# PROMPT 23 — Security, performance, data governance

Проведи red-team Stage 2B.

## Security

- IDOR prediction run/candidate/mask URL across workspaces;
- forged target_takeoff_item from another project;
- arbitrary model id/path;
- malicious weights never user-executed;
- object-storage presigned URLs bounded;
- oversized masks/candidates/point counts;
- job replay/idempotency;
- accept candidate race;
- zip/XML PlanSwift private importer path traversal if archive convenience exists;
- XML entity expansion/XXE disabled.

## Data policy

Тестом/архитектурой доказать: PlanSwift/private drawing bytes не покидают local/on-prem vision
runtime. `DataPolicy` provider contracts не являются доказательством сами по себе — сетевой
client к remote model отсутствует в execution path.

## Performance

На representative sheet:

- raster tiles/sec;
- inference latency;
- peak VRAM/RAM;
- mask artifact size;
- vectorization latency;
- candidate DB batch latency;
- candidate overlay 1k/5k/10k;
- accept batch/individual latency;
- page open unaffected when AI unused.

Heavy vision dependencies не должны попасть в `/projects`/normal web bundle или API cold path.

## Failure recovery

Worker crash/OOM/lease expiry/retry не создают duplicate prediction runs/candidates.

Документ `docs/stage2b/20-hardening.md`.

STOP.
