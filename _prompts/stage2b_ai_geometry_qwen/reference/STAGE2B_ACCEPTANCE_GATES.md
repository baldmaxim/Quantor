# Stage 2B Acceptance Gates — revised with Qwen/Unsloth branch

1. `STAGE2A_BASELINE_GREEN` — свежий полный прогон, обязательные DB tests не hidden-skipped.
2. `MANUAL_FLAG_PILOT_SAFE` — manual ready, default OFF, workspace pilot possible.
3. `VIEWER_266_PERCENT` — live pan/zoom acceptance after viewer work.
4. `OVERLAY_SCALABILITY` — vector overlays + hit-test выдерживают AI-scale counts.
5. `GEOMETRY_VALIDITY` — self-intersection => INVALID, не 0 quantity.
6. `POLYGON_HOLES` — outer+holes корректно проходят quantity path.
7. `PLANSWIFT_IMPORT` — deterministic import + rejection report.
8. `DATASET_PROVENANCE` — raw source/hash/transforms воспроизводимы.
9. `SPLIT_LEAKAGE` — grouped split frozen before training.
10. `LICENSE_GATE` — dependencies/models/weights audited; no blocked Ultralytics path.
11. `SLAB_SMALL_BASELINE` — reproducible small segmentation run.
12. `SAM_BASELINE` — production-like prompts, no GT leakage.
13. `QWEN_DATASET_CONTRACT` — strict SFT schemas, source-only val/test crops.
14. `QWEN_ZERO_SHOT` — 4B pre-SFT localization baseline measured.
15. `QWEN_SFT` — at least one reproducible 4B Unsloth LoRA/SFT run with exact provenance.
16. `QWEN_VISION_ABLATION` — vision-frozen vs vision-adapted result measured or explicitly hardware-blocked with evidence.
17. `QWEN_SAM_HYBRID` — Qwen prompts feed SAM with zero GT substitution on test.
18. `MASONRY_BASELINE` — reproducible centerline run.
19. `MASK_VECTOR_AREA` — mask→polygon+holes tested.
20. `MASK_VECTOR_CENTERLINE` — mask→polyline tested.
21. `QTO_BENCHMARK` — unified model-family table includes quantity error, not only pixel metrics.
22. `MODEL_PROMOTION_EXPLICIT` — Prompt 18 owner-approved exact pipeline/checkpoint IDs.
23. `AI_PROVENANCE` — full model-chain/input/output hashes traceable.
24. `TRUSTED_INFERENCE` — source=ai cannot be forged via manual API.
25. `HUMAN_REVIEW` — pending candidate never enters working total.
26. `TENANT_SECURITY` — runs/candidates/artifacts respect workspace/project boundary.
27. `DATA_POLICY` — private PlanSwift/drawings never sent remote by default.
28. `LIVE_AI_PILOT` — real sheet: job→AI pipeline→mask/vector→review→Measurement→Quantity.

`takeoff.ai` remains default OFF until production-integration gates pass. Offline lab may run while user feature remains hidden.
