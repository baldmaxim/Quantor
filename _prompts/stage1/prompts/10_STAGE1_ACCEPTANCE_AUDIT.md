# PROMPT 10 — Stage 1 final acceptance audit

Это финальный контроль. Сначала ничего не меняй: проведи аудит как независимый reviewer.

## Product acceptance

Проверь end-to-end:
1. start local dependencies;
2. start API/web;
3. open Projects;
4. create project;
5. upload recognized legacy ZIP;
6. observe real import status;
7. open project;
8. see document/revision/sheets;
9. open workspace;
10. PDF page renders;
11. navigate pages;
12. recognition Regions overlay aligns by normalized coordinates;
13. select Region -> Inspector;
14. toggle text/image/stamp visibility;
15. no takeoff calculation/AI inference exists yet.

If real fixture is available, verify expected 77 / 383 / 230 / 90 / 63 counts. Do not hardcode these counts into product code; they are fixture assertions only.

## Architecture audit

Verify:
- binary files in object storage, not DB;
- DocumentRevision immutable;
- Region separate from Measurement;
- future model providers not hardcoded;
- Claude Code/Cursor absent from runtime dependencies;
- no server-side crop URL fetching;
- API contract single source;
- viewer renderer separable from overlay;
- future tile backend possible;
- job abstraction supports future async pipeline;
- RVT/NWD/NWC/IFC can be stored without fake parsing.

## Performance audit

Verify:
- viewer heavy libs lazy;
- no all-page full-res render;
- thumbnails/list virtualization;
- bounded upload/import memory;
- stale renders/calls cancel;
- no obvious N+1;
- no huge React rerender loop during zoom/pan.

## Security audit

Verify tests for:
- zip traversal/bomb;
- invalid schema;
- malicious markdown/html;
- cross-project access boundary;
- oversized file;
- external crop SSRF prevented.

## Quality gates

Run every repo quality command from a clean state:
- formatting/lint;
- typecheck;
- tests;
- build;
- migrations;
- Playwright smoke.

## Scope audit

Search codebase for accidental premature functionality. Stage 1 should contain no real:
- CV model;
- LLM/VLM inference;
- quantity calculation;
- scale detection;
- BIM extraction;
- agent loop.

Remove accidental dead/fake implementation if it was introduced, but preserve documented interfaces.

## Deliverables

Create/update:
- `docs/stage1/README.md` — what Stage 1 actually does;
- `docs/stage1/KNOWN_LIMITATIONS.md`;
- `docs/stage1/STAGE2_HANDOFF.md` containing only factual architecture state, endpoints, tables, viewer interfaces, import schema, tests and deliberate TODOs.

Do **not** propose or start Stage 2 implementation in code. Handoff should make the next prompt pack easy to create.

At the end give user:
- PASS/FAIL for each acceptance group;
- exact commands to launch;
- exact location of architecture docs;
- known blockers;
- short statement: “Stage 1 ready for Stage 2” only if all critical gates pass.
