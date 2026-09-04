# PROMPT 07 — Project workspace + high-performance PDF viewer shell

Это ключевой UX Stage 1. Нужен быстрый Kreo-like workspace, но пока без takeoff engine.

## Goal

Открыть imported project and:
- navigate 77+ PDF pages;
- zoom/pan smoothly;
- select sheet;
- toggle recognition debug overlay;
- click recognized Region and inspect its metadata/raw recognized Markdown;
- keep UI responsive on ~50 MB PDF.

## Rendering architecture

Base drawing:
- use `pdfjs-dist` directly or equivalent low-level integration;
- PDF must be loaded from presigned/range-capable URL;
- worker enabled;
- do not render all pages at full resolution;
- current page + small prefetch only;
- abort stale render tasks when page/zoom changes;
- cache bounded canvases/bitmaps;
- respect rotation;
- lazy load pdf.js only on workspace route.

Overlay:
- separate layer from PDF renderer;
- use PixiJS/WebGL or an equally performant canvas abstraction, lazy-loaded;
- Regions render from normalized coordinates;
- rectangle and polygon support;
- transformations aligned with PDF page viewport;
- toggle by block_type;
- hover/select styling;
- future measurement layer must be a separate layer type, not reuse Region objects.

For Stage 1 overlay may contain hundreds/thousands of regions. Structure code so future 10k+ primitives/page can add spatial indexing and LOD without rewriting workspace.

## Important React performance rule

Pan/zoom pointer events happen frequently. Do not push every frame through root React state. Use an imperative camera/viewport controller, refs, `requestAnimationFrame`, or an external store with narrow subscriptions. React owns panels/controls; renderer owns high-frequency transforms.

## Workspace UX

Follow `reference/ROUTES_AND_UI.md`.

Implement:
- top quick-access page tabs/history;
- left Documents tab with file/sheet tree;
- Recognition tab with type visibility and region list/search by block id;
- Takeoff tab disabled;
- center viewer;
- right Inspector for selected Region;
- bottom status: page, zoom, `scale: Не задан`, rendering/debug info in dev.

Toolbar:
- pointer;
- hand/pan;
- previous/next;
- page field;
- zoom +/-;
- fit page;
- fit width;
- overlay toggle;
- reset view.

Keyboard shortcuts where natural:
- Space-drag pan;
- +/- zoom;
- PageUp/PageDown or arrows only if not conflicting with inputs;
- Esc deselect.

## Selection / Inspector

When Region selected:
- block_id;
- block_type;
- sheet/page;
- shape;
- normalized coordinates;
- status;
- raw recognized Markdown, sanitized and collapsed;
- legacy crop URL shown only as non-active metadata or explicit safe external link if policy allows. No server-side fetch.

## Thumbnails

Do not render full page list as high-res canvases. Use virtualized list and lazy thumbnails. If backend provides no thumbnails yet, generate low-res thumbnail in browser on demand and cache boundedly, or add a small backend thumbnail endpoint if that is measurably simpler and safe.

## Viewer backend abstraction

Define a small interface so Stage 2/3 can add:
- `PdfJsRenderBackend` current;
- `TileRenderBackend` future for pathological PDFs/huge sheets;
- optional vector-aware backend later.

Do not implement tile server now.

## Failure modes

Good UX for:
- expired presigned URL -> refresh URL;
- PDF render error;
- corrupt page;
- regions loaded but PDF unavailable;
- no regions;
- very large document;
- page metadata mismatch.

## Tests

- coordinate transform unit tests;
- rectangle/polygon overlay alignment with known fixture;
- navigation between pages;
- stale render cancellation;
- selection/inspector;
- overlay toggles;
- no full-document eager rendering;
- Playwright smoke with a multipage PDF;
- optional local real-fixture test with the user's 77-page PDF.

## Acceptance

Workspace feels fast and deliberate. It displays imported recognition, but does not pretend to calculate anything. Takeoff controls remain disabled for Stage 2.
