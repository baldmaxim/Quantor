# Stage 1 domain contracts

Do not over-model, but make revisioning and provenance correct now.

## Persistent entities to implement

### Project
- id UUID (prefer UUIDv7 if chosen library is mature; otherwise UUIDv4);
- workspace_id / organization boundary placeholder;
- name;
- status;
- created_at / updated_at.

### Document
Logical document inside project.
- id;
- project_id;
- display_name;
- discipline optional;
- document_kind: pdf | recognized_package | revit | navisworks | ifc | other;
- created_at.

### DocumentRevision
Immutable uploaded version.
- id;
- document_id;
- revision_label optional;
- source_filename;
- source_mime;
- source_size;
- source_sha256;
- storage_key;
- processing_status;
- schema/source metadata JSONB;
- created_at.

### Sheet
- id;
- revision_id;
- page_index zero-based;
- page_label/display_name;
- width_px optional;
- height_px optional;
- rotation;
- metadata JSONB.

### RecognitionArtifact
- id;
- revision_id;
- artifact_kind: blocks_json | results_md | results_html | package_zip | other;
- schema_version;
- sha256;
- storage_key;
- metadata JSONB.

### Region
Stage 1 only for recognition/debug overlay.
- id;
- sheet_id;
- external_block_id;
- ordinal optional;
- block_type;
- shape_type;
- coords_norm JSON/geometry;
- polygon_points optional;
- recognition_status;
- raw_content_md optional;
- legacy_metadata JSONB;

Do not use Region as future Measurement. They are different concepts.

### Job
Minimal durable status record.
- id;
- project_id optional;
- job_type;
- status: queued | running | succeeded | failed | cancelled;
- progress 0..1 optional;
- stage;
- idempotency_key optional;
- error_code / safe_error_message optional;
- created_at / started_at / finished_at.

## Future contracts — define in docs/types only, no full DB yet

```text
Measurement
- geometry_type: count | line | polyline | polygon
- geometry in normalized/world coordinate space
- scale/calibration reference
- source: manual | ai | imported
- confidence/provenance

QuantityItem
- category/type
- value/unit
- formula/rule_version
- measurement links
- evidence links
- verification status
```

## Provenance invariant

Every derived object later must be traceable back to:
`project -> document -> revision -> sheet -> geometry/evidence -> algorithm/model version`.

Stage 1 should make that possible without yet implementing quantity logic.
