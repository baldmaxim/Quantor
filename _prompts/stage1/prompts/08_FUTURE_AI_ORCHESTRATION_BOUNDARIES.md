# PROMPT 08 — Future AI/CV/QTO boundaries only (no runtime inference)

Цель — сделать так, чтобы Stage 2 можно было подключать без переписывания shell. Это architecture/contracts task, не AI implementation.

## 1. Model provider boundary

Создай документацию и минимальные protocol/interface types, но без provider SDK calls.

Concept:

```text
ModelProvider
  capabilities()
  health()
  infer(request)   # interface only / NotImplemented in Stage 1
```

Future capability metadata:
- provider_id;
- model_id;
- endpoint kind;
- text/vision;
- structured output;
- tool calling;
- context tokens;
- image constraints;
- concurrency;
- latency/cost class;
- data residency/local flag.

Expected future adapters:
- Local/OpenAI-compatible HTTP (vLLM/SGLang/llama.cpp etc.);
- remote OpenAI-compatible;
- Anthropic;
- OpenAI;
- custom VLM service.

Business modules must depend on capabilities/contracts, not `if model == ...` branching.

No API keys in DB plaintext. No secrets UI in Stage 1.

## 2. Processing jobs

Define future job types/status payloads:

```text
ingest
sheet_parse
ocr_layout
vector_extract
symbol_detect
semantic_link
measure
quantity_calculate
verify
export
```

Stage 1 only `legacy_import` is real. Future pipeline is docs/types.

Design for:
- idempotency;
- retry;
- resumability;
- cancellation;
- progress by stage;
- input/output artifact IDs;
- model/rule version provenance;
- no hidden background mutation.

Create ADR comparing lightweight queue and Temporal-like durable workflows. Do not install either just for this prompt.

## 3. Geometry/quantity boundary

Document future separation:

```text
Recognition Region != Measurement != Quantity
```

- Region = what recognizer saw / evidence region;
- Measurement = geometry intended for takeoff;
- Quantity = deterministic result/value with rule provenance.

LLM/VLM is never the calculator of record. Future arithmetic/geometry will use deterministic services.

## 4. Scale/calibration future contract

Define only types:
- ScaleCalibration;
- source: manual | detected_dimension | imported;
- confidence;
- validation points;
- `verified` flag.

Do not build scale detector in Stage 1.

## 5. Cursor/Claude Code note

Explicitly document:
- Claude Code and Cursor are developer tools;
- runtime orchestration lives in backend/services;
- no portal feature may require a developer IDE agent to be running.

## 6. Feature flags

Introduce a clean feature flag/capability mechanism so UI can hide/disable:
- `takeoff.manual`;
- `takeoff.ai`;
- `models.gateway`;
- `reports`;
- `bim.import`;
- `drawing.compare`.

Stage 1 defaults false except core projects/import/viewer.

## Acceptance

The codebase contains stable extension points and docs, but dependency graph shows no Anthropic/OpenAI/vLLM/CV SDK pulled into production solely because of this prompt.
