# Human checklist — Stage 1

## Must work
- [ ] Portal starts from clean checkout using documented commands.
- [ ] Projects page is usable and visually consistent.
- [ ] Project can be created.
- [ ] Recognized legacy ZIP can be uploaded.
- [ ] Import is safe and shows status.
- [ ] Real example imports 77 pages / 383 regions when fixture is available.
- [ ] PDF opens without downloading/rendering every page eagerly.
- [ ] Pan/zoom/page navigation are responsive.
- [ ] Recognition overlay can be toggled.
- [ ] Region selection shows metadata/raw recognition payload.
- [ ] No external crop URL is fetched automatically.
- [ ] Raw PDF/ZIP are stored outside PostgreSQL.
- [ ] Russian filenames/text work.
- [ ] Invalid ZIPs fail safely.
- [ ] Tests/build pass.

## Must NOT exist yet
- [ ] No Auto Measure.
- [ ] No Auto Count.
- [ ] No quantity calculation.
- [ ] No scale detector.
- [ ] No CV/LLM/VLM runtime.
- [ ] No BIM parser.
- [ ] No report/estimate engine pretending to be complete.

## Architecture must be ready for later
- [ ] Document revisions immutable.
- [ ] Region != Measurement.
- [ ] ModelProvider boundary documented.
- [ ] Job state documented/implemented minimally.
- [ ] Viewer backend abstraction exists.
- [ ] Overlay layer separate from base PDF renderer.
- [ ] Feature flags/capabilities hide Stage 2 features.
