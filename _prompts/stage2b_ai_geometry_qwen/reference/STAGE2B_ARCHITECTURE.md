# Целевая архитектура Stage 2B — comparative AI Geometry Lab

```text
                         PRIVATE / OFFLINE
PlanSwift archives ──→ Dataset Importer ──→ Ground Truth v1
                                         ├─ slab masks + holes
                                         └─ masonry centerlines
                                                │
                         ┌──────────────────────┼────────────────────────┐
                         ▼                      ▼                        ▼
                  Small CV models          SAM baselines          Qwen3-VL Lab
                  semantic/centerline       + refiners             Unsloth SFT
                         │                      │                   2B / 4B / 8B*
                         │                      │                        │
                         │                      │              localization JSON
                         │                      │              or bounded polygon
                         │                      │                        │
                         └──────────────┬───────┴───────────────┬────────┘
                                        │                       │
                                        │              Qwen → SAM hybrid
                                        │                       │
                                        └──────────┬────────────┘
                                                   ▼
                                         Unified QTO Benchmark
                                                   │
                                     only owner-promoted pipeline
                                                   │
───────────────────────────────────────────────────┼────────────────────────
                         PRODUCTION / PILOT         ▼
PDF revision → Raster Tiles → Vision Worker → promoted pipeline
                                                   │
                                      raw mask / direct vector artifact
                                                   │
                                                   ▼
                                            Mask→Vector Core
                                              (when applicable)
                                                   │
                                                   ▼
                                           PredictionCandidate
                                          (NOT Measurement yet)
                                                   │
                                    human accept/edit/reject
                                                   │
                                                   ▼
                                         Measurement(source=ai)
                                                   │
                                                   ▼
                                          Quantity Engine v1
```

`*` 8B — optional upper-bound only, not required.

## Роли компонентов

- Qwen: semantic localization/structured guidance, optionally bounded direct geometry research.
- SAM: precise mask from prompts.
- Small CV: cheap direct mask/centerline baseline and possible coarse prompt generator.
- Quantor vectorizer: geometry/topology source of truth after masks.
- Quantity Engine: the only source of physical quantities.

## Почему PredictionCandidate отделён от Measurement

Unreviewed AI prediction не должен попадать в рабочую сумму. Candidate stores immutable model output/provenance; accepted/edit creates ordinary `Measurement(source=ai)`.

## Viewer layers

```text
PDF raster
Recognition regions
Manual/accepted Measurements
AI candidate vector
optional raw-mask evidence
```
