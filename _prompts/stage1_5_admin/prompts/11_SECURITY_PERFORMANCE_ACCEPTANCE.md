# PROMPT 11 — Security, performance and acceptance

Проведи Stage 1.5 acceptance как независимый verifier.

## Security matrix

Проверить:

1. unauthenticated user cannot read Project API;
2. viewer cannot mutate;
3. engineer cannot admin;
4. workspace_admin cannot escape workspace;
5. platform_admin access is explicit;
6. guessed UUID cannot cross workspace;
7. content-url authorization works;
8. admin API deny-by-default;
9. no raw TenderHUB/model/OIDC secret in HTML/JSON/log/client bundle;
10. admin destructive action audited;
11. PWA/service worker does not cache admin authenticated API responses dangerously;
12. logout invalidates/clears portal state appropriately.

## Performance

Measure, don't assume:

- `/projects` first load before/after auth;
- admin dashboard first load;
- admin bundle should not include PDF.js/viewer chunks;
- 100/1000 audit rows pagination does not load all rows;
- users/workspaces tables paginated;
- health probes bounded;
- ordinary portal load does not call admin endpoints.

## Tests

Run full existing Stage 1 suite + new tests.

No regression accepted in:

- legacy package import;
- live 77-sheet viewer test;
- coordinate overlay;
- TenderHUB project binding;
- upload streaming;
- PWA normal portal;
- OpenAPI drift gate.

## Live acceptance

Use a real recognized package again. Verify:

- admin auth doesn't break project load;
- authorized user opens same PDF/regions correctly;
- wrong workspace cannot obtain PDF content-url;
- TenderHUB-linked project displays canonical external metadata correctly.

Create `docs/stage1_5/acceptance-report.md` with measured evidence.

STOP.
