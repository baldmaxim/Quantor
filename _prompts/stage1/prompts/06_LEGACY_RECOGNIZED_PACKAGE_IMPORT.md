# PROMPT 06 — Safe legacy recognized-package import (thin vertical slice)

Это единственная часть Stage 1, которая понимает текущий формат распознавалки. Она нужна, чтобы оболочка могла открыть реально уже распознанный проект. **Не делать новое распознавание.**

Прочитай `reference/EXPORT_ANALYSIS.md`.

## Input

Legacy ZIP example contains:
- exactly/typically one PDF;
- `*_blocks.json`;
- `*_results.md`;
- optional `*_results.html`.

Expected JSON:
- `schema_version = 1`;
- `coordinate_space = normalized_page_top_left`;
- `pages[]`;
- `blocks[]`.

## Security first

ZIP — untrusted input.

Implement safe archive reader:
- no `extractall` into arbitrary path;
- reject path traversal (`../`, absolute paths, drive prefixes);
- reject symlinks/special files;
- configurable max file count;
- configurable max compressed and total uncompressed size;
- configurable per-file size;
- reject suspicious compression ratio/zip bomb;
- whitelist required/optional extensions;
- filenames decoded/handled Unicode safely;
- do not execute/read HTML as active content;
- **never fetch `crop_url` server-side**;
- importer is idempotent by package/revision hash.

Prefer streaming/member reads and temp files with cleanup where needed. Do not keep ~50–500 MB PDF in Python RAM.

## Validation

Create explicit typed validator + error codes:
- missing PDF;
- missing blocks JSON;
- invalid JSON;
- unsupported schema version;
- unsupported coordinate space;
- page index outside range;
- invalid normalized coordinates;
- polygon invalid;
- duplicate block_id;
- malformed Markdown association should warn/fallback rather than corrupt whole import where possible.

`coords_norm` expected [x0,y0,x1,y1] in [0,1], top-left space. Polygon points same coordinate space.

## Persistence

Import transaction/state must be robust:
1. raw ZIP already immutable in storage;
2. PDF stored as revision/source artifact (avoid duplicate physical copy if storage architecture supports server-side copy/reference);
3. create Document + immutable DocumentRevision;
4. create 77/etc Sheets from pages;
5. create RecognitionArtifact records for JSON/MD/HTML;
6. create Regions from blocks;
7. associate `results.md` sections to Regions by `block_id`;
8. store raw section Markdown, but DO NOT semantically normalize Summary/Description/Entities in Stage 1;
9. stamps without MD section remain valid Regions;
10. store legacy crop URL only in metadata;
11. Job -> succeeded only after DB consistency is complete.

On failure:
- job failed with safe code;
- no half-visible project graph;
- raw uploaded package may remain for diagnostics under retention policy;
- retry is possible.

## Markdown parser

Do not parse Markdown as arbitrary HTML. We only need a tolerant index of sections:
`### BLOCK #<ordinal> [<TYPE>]: <block_id>`.

Store the raw section between this heading and the next block/page heading. Do not assume English-only content.

## Current example as acceptance fixture

If `fixtures/legacy/01-03-00-01-12_ПД-00260560-АР.zip` exists, use it in a local integration test **without committing the binary**.

Expected high-level assertions:
- PDF pages = 77;
- total Regions = 383;
- text = 230;
- image = 90;
- stamp = 63;
- MD-associated text/image sections = 320;
- coordinate space recorded exactly;
- no network calls to crop URLs.

If fixture absent, make tests with a tiny generated ZIP fixture matching the same schema and document how to run the real-fixture test locally.

## API/UI integration

Importer can run through a simple Stage 1 background mechanism. Do not introduce a heavyweight orchestration platform. Job status must be queryable and UI updates via polling with sane interval; SSE/WebSocket can wait.

## Acceptance

Upload real legacy ZIP -> project becomes Ready -> Document/Revision/Sheets/Regions exist -> no external crop fetch -> no AI inference -> rerun is idempotent.
