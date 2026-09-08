# Acceptance gates Stage 2A

Stage 2A считается закрытым только если каждый gate имеет PASS или явно согласованное
владельцем исключение.

1. **PREVIOUS_STAGE_GREEN** — свежий test-run Stage 1.5 после последних viewer/security fixes.
2. **CANONICAL_GEOMETRY** — server geometry extracted from PDF, no raster width for QTO.
3. **CROSS_RUNTIME_COORDINATES** — Python/TypeScript shared vectors green.
4. **SCALE_CORRECTNESS** — horizontal/vertical/diagonal calibration tests green.
5. **MULTI_SCALE_SAFETY** — data model allows explicit calibration per Measurement.
6. **MANUAL_COUNT** — persistent count works after reload.
7. **MANUAL_LENGTH** — Line/Polyline returns authoritative physical length.
8. **MANUAL_AREA** — Polygon returns authoritative physical area.
9. **EDITING** — select/edit/delete does not corrupt geometry or quantities.
10. **PROVENANCE** — every quantity response traces measurement, sheet, revision, calibration, rule.
11. **TENANT_SECURITY** — cross-workspace measurement/scale/takeoff access is impossible.
12. **PERFORMANCE** — current live project stays responsive; 1k/5k/10k benchmark recorded.
13. **NO_AI** — no runtime model/CV/VLM calls have appeared.
14. **LIVE_PDF** — real known dimensions/count/area checked on actual project.
15. **FEATURE_GATE** — `takeoff.manual` only enabled after the gates above are actually green.
