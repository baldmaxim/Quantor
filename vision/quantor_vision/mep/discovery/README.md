# MEP D0 discovery

Install the pinned `vision[mep-discovery]` extra in the offline vision environment.
Set `MEP_ARCHIVE_ROOT` and `QUANTOR_DATASET_ROOT`, then run:

```powershell
python -m quantor_vision mep discover
```

Equivalent explicit flags: `--archive-root`, `--dataset-root`. The destination is a
**new** `mep/` under the dataset root. Existing results are never overwritten. The
destination cannot overlap the source, reside in a Git worktree, or use a symlink
or junction. Inputs are read only; source hashes are checked again after discovery.

ZIP Unicode extra fields take precedence when their CRC is valid. Otherwise the
explicit legacy code page is used (`--legacy-encoding cp866`, or `cp1251`). Raw ZIP
name bytes are preserved as hex. 7-Zip exposes Unicode names but not original name
bytes; the latter remain null with an explicit reason. Missing 7-Zip means HOLD.

Limits: 100,000 members, 32 GiB per archive, 2 GiB per member, 100 GiB total expanded
data, compression ratio 200, two nested archive levels below the input archive.
Every member is checked before extraction; payload sizes and ZIP CRCs are checked
before publishing any file. Duplicate content uses hardlinks on the dataset volume.
`source_links.jsonl` retains each occurrence and its raw path.

PDF workers have a 600-second timeout (`--pdf-timeout`). Finished pages are checkpointed
and resumed after interruption. The local `.pdf-cache/`
contains only text/operator metadata, keyed by PDF SHA-256 and parser/rules source
hashes. Cache hits are classified again using their occurrence paths. Unused vector
path coordinates are omitted before tokenization; text, graphics transforms, painting
and clipping markers stay intact. Strings remain opaque; inline images/dictionaries
disable the optimization. No OCR,
rendering, image decoding, CAD conversion, spreadsheet-cell parsing, or BIM parsing
is performed. Read errors and unavailable metadata stay explicit.

Classification rules and synthetic examples live in `rules.py`. Evidence sources
are ordered stamp candidate, title, filename, directory. Contradictions remain
unknown. Stamps are conservatively located using an unrotated bottom-right region
and characteristic labels; this does not establish visual readability. Image area
comes from transformed image rectangles clipped to the page; custom clipping is
flagged as an upper bound. No alignment or automatic scale extraction occurs.

Projects use the drawing-code project prefix when available; buildings stay separate.
An explicit object code or project label is the fallback. Folder identity alone is not
enough. Pairing cannot cross project IDs. One P page matched to distinct RD buildings is
REVIEW with the full candidate list; same-building ambiguity produces HOLD.
AUTO_OK also requires building, section and revision confirmation. Pilot selection stops at
10 candidates, or fewer if the data do not support that many.

`inventory/manifest.json` hashes all output payloads except itself, and records
source fingerprint, Git state, configuration and tool source hashes. A page hash
binds the original PDF hash to its one-based page number; `text_sha256` fingerprints
the canonical JSON representation of the extracted text. The aggregate report is
the only private-run artifact intended to be copied into Git.

## D0.1 refinement

```powershell
python -m quantor_vision.mep.discovery.refine --dataset-root D:\QuantorData --workers 6
```

The original inventory is preserved in `inventory/d0-before-refinement/`. Text titles
are re-extracted because D0's cache retained only rule-matching evidence lines. This
uses the existing pypdf text/operator reader, never OCR or rendering. Later rule-only
updates can use `--reuse-text` after a complete title-bearing inventory exists.

PD/RD archive directories and RD drawing-code tokens supply stage evidence. PD section
numbers map to disciplines; RD markers and fire systems remain separate fields. Building
tokens in paths are not interpreted as observed system codes. Explicit stage conflicts
remain unknown. Prefix, section and marker rules have synthetic examples.

Version selection retains every payload and occurrence. Within a project/building/stage/
discipline and normalized filename it ranks revision number, then date. Older occurrences
are `superseded`; equal-ranked different payloads require review. Unknown project identities
are never merged by filename alone. This conservative key does not assume differently
named sheets are revisions of one set.

The inventory includes `pilot_candidates_unconfirmed.json` and
`manual_sample_pd_sections.json`: up to 50 pages per requested section, sampled without
replacement by seeded SHA-256 ordering. The seed and shortages are recorded. Private
samples contain title candidates and stamp text, not a visual-readability judgement.
Issue totals overlap when a page has several limitations. Superseded pages remain in
total counts but are excluded from pairing and pilot selection.
