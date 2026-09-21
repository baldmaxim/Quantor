# PROMPT 07 — Live E2E Acceptance & Bugfix (живая сквозная приёмка и исправление дефектов)

**Модель:** Opus 5  
**Режим мышления:** высокий  
**Цель:** не добавлять новые функции, а реально пройти портал как инженер и исправить все blocker/major (блокирующие/существенные) дефекты для пилотной работы.

## 1. Никакой новой архитектуры

Feature development (разработка функций) завершена на P06.

Этот промт — только acceptance/fix (приёмка/исправления).

## 2. Полный автоматический контроль

Запусти максимально полный набор:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm lint:licenses
pnpm api-client:check
```

Если безопасно доступна dev/test DB:

```bash
pnpm db:migrate
```

Запусти `pnpm test:e2e`, если среда готова. Если нет — явно `ENV_BLOCKED`, но обязательно проведи manual USER_RUN (ручной пользовательский прогон).

## 3. Два живых пользовательских сценария

### Scenario A — обычный ручной обмер

1. создать/открыть проект;
2. загрузить raw PDF;
3. дождаться geometry ready;
4. открыть workspace без recognition ZIP;
5. включить `takeoff.manual` на workspace;
6. калибровать масштаб;
7. count/line/polyline/polygon;
8. reload;
9. исправить одно измерение;
10. экспортировать CSV;
11. сверить числа.

### Scenario B — MEP manual pilot

1. включить `mep.manual_pilot_v1` только на pilot workspace;
2. открыть реальный/безопасный тестовый PDF;
3. выбрать sheet/profile;
4. создать HUMAN_GT evidence;
5. создать relation;
6. собрать/validate EvidenceGraph;
7. нарисовать ручную NetworkGraph;
8. добавить evidence link;
9. получить physical BOQ;
10. открыть trace BOQ → Network → Evidence → Sheet;
11. экспортировать CSV;
12. reload и убедиться, что состояние воспроизводится.

Если клиентский реальный PDF доступен только владельцу, подготовь `docs/pilot/USER_RUN_MANUAL_PILOT.md` с чекбоксами и проведи автоматизированную часть на безопасной fixture.

## 4. Severity (критичность)

Исправляй в этом промте:

- P0 blocker — обязательно;
- P1 major — обязательно;
- P2 usability — если правка локальная и низкорисковая;
- P3 cosmetic — записать, не тратить время.

Не превращай acceptance в redesign.

## 5. Проверки безопасности данных

Подтверди:

- клиентские PDF/graphs не попадают в Git;
- dataset root вне Git;
- экспорт не раскрывает чужое workspace;
- все MEP write endpoints требуют права;
- flags OFF реально закрывают функции;
- source hashes/provenance сохраняются;
- MOCK fixtures A/B/C/D остались неизменными или изменение было только техническим без смены эталона (в идеале SHA unchanged).

## 6. Performance smoke (быстрая проверка производительности)

Не оптимизируй преждевременно, но проверь:

- лист разумного размера открывается;
- 100–300 ручных overlay элементов не делают editor непригодным;
- save/edit не блокируют UI ненормально долго;
- BOQ строится интерактивно приемлемо на пилотном графе.

Если проблема есть — измерь и исправь только очевидный hotspot (узкое место).

## 7. Итоговый вердикт

Выдай таблицу:

- RAW_PDF_WORKSPACE;
- MANUAL_TAKEOFF;
- MEP_HUMAN_GT;
- MEP_MANUAL_NETWORK;
- MEP_PHYSICAL_BOQ;
- EXPORT;
- TRACEABILITY;
- ACCESS_CONTROL;
- RELOAD_PERSISTENCE;

Для каждого: `PASS / PASS_WITH_LIMITATION / FAIL`.

Главный вердикт:

`READY_FOR_MANUAL_PILOT = YES/NO`

NO допустим только с конкретным blocker и шагом устранения.

## 8. Review ZIP

Создай `review/QUANTOR_FASTSTART_P07_REVIEW.zip` с:

- acceptance report;
- USER_RUN;
- test outputs summary;
- screenshots без клиентских секретов;
- список исправленных defects (дефектов);
- оставшийся backlog (бэклог) P2/P3.

После отчёта остановись. Никаких коммитов.
