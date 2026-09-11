# Unified model comparison matrix

Prompt 18 must populate this from machine-readable runs; never hand-wave blank cells.

| Pipeline | Task | QTO error median/p90 | Geometry validity | Hole/branch metrics | Parse rate | Latency | VRAM | Model size | License | Runtime complexity | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| Small semantic | slab | | | | n/a | | | | | low | |
| SAM production prompt | slab | | | | n/a | | | | | medium | |
| Small→SAM | slab | | | | n/a | | | | | medium | |
| Qwen4B zero→SAM | slab | | | | | | | | | high | |
| Qwen4B SFT→SAM | slab | | | | | | | | | high | |
| Qwen2B SFT→SAM | slab | | | | | | | | | high | |
| Qwen direct polygon | slab | | | | | | | | | medium/high | |
| Centerline small model | masonry | | | | n/a | | | | | low | |

Selection principle: if QTO quality is practically equivalent within predeclared tolerance, choose the simpler runtime. A VLM/hybrid is promoted only for measurable downstream benefit.
