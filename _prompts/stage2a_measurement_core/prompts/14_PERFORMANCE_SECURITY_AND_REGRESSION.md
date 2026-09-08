# PROMPT 14 — Performance, security, regression hardening

Теперь оптимизируй только то, что доказано benchmark/profiling.

## Performance

Проверь:

- current-sheet only loading;
- no N+1;
- no API writes pointermove;
- PDF base not rerendered by measurement changes;
- bounded batch Count;
- Canvas draw 1k/5k/10k;
- hit-test cost;
- React commit count during drawing;
- bundle: pdfjs remains route-local; measurement code не тащит тяжёлую библиотеку на `/projects`.

Если Canvas2D проходит разумно — оставить. Если реально не проходит, сначала документировать
данные, затем оценить spatial index/LOD, и только потом WebGL.

## Security

Red-team endpoints:

- foreign workspace item/sheet/measurement/calibration UUID;
- IDOR through batch;
- optimistic version bypass;
- invalid huge points arrays;
- 100k point polygon payload;
- NaN/Infinity JSON edge;
- audit leakage;
- user spoofing `source=ai`/creator;
- system job scope regression.

Введи bounded geometry sizes на API с понятными limits, чтобы polygon payload не стал DoS.

## Regression

Полный lint/typecheck/tests/build. Existing Stage 1/1.5 live import/viewer/TenderHUB/admin behavior не ломать.

Документируй реальные показатели, а не желаемые.

STOP.
