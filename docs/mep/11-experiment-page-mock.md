# MEP: страница эксперимента — режим MOCK

v3 PROMPT 11, 2026-09-15. Только синтетические сценарии: реального комплекта П нет, PROMPT 02–04 не
начинались. Модель, распознавание, обучение и цены не подключены.

## 1. Что сделано

```text
GET /api/v1/mep/experiment/scenarios[/{id}]        флаг mep_rd_hypothesis_v1, право workspace.read
  └─ services/mep/scenarios.py                     фикстуры пакета → validate_* → build_boq (PROMPT 09)
/experiments/mep                                    Next.js, закрыта флагом, в навигации нет
  Шаг 1 · Стадия П / evidence    лист + EvidencePanel
  Шаг 2 · Сеть РД (сгенерировано) лист (evidence приглушён) + NetworkPanel + InferenceStepCard
  Шаг 3 · Физический ВОР          BoqTable
```

- Сервер отдаёт профиль, evidence, сеть, их хеши, замечания проверок и ВОР, посчитанный на запросе
  `build_boq`. Интерфейс чисел и статусов не вычисляет.
- Флаг стал пилотным (`admin_editable`, выключен по умолчанию, включается на пространство). Выключен —
  API отвечает `403 FEATURE_DISABLED`, страница показывает «Страница не найдена» без данных и названия.
- Лист — Canvas2D (ADR-0015) на пропорциях снимка калибровки; попадание считает существующий
  `hitTestMeasurements`. PDF и `PageRasterProvider` не используются.
- Фикстуры перенесены из `docs/mep/examples/` в `apps/api/app/services/mep/fixtures/` (данные пакета).

## 2. Сценарии

| Сценарий     | Сеть                                | Проверки                                                        | ВОР                                                                                        |
| ------------ | ----------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| A · COMPLETE | `network_graph_resolved.v0.3.json`  | без ошибок                                                      | `complete`: 6 строк, 21,025 м + 48,990 м, 2 шт, топология                                  |
| B · PARTIAL  | `network_graph.v0.3.json`           | без ошибок; материал `unresolved`, `ud-1`                       | `partial`: счёт и разветвление; длины — `PARAMETER_UNRESOLVED`, `DECISION_BLOCKS_QUANTITY` |
| C · REFUSED  | `network_graph_corrupted.v0.3.json` | `CALIBRATION_FINGERPRINT_MISMATCH` (мм/pt изменён после снимка) | `refused`: строк нет, `NETWORK_INVALID`                                                    |

## 3. Как разведены observed и generated

- Шаг 1 рисует только evidence: синие прямоугольники и линии, бейдж «наблюдено на П».
- Шаг 2 приглушает evidence и рисует сеть кругами и линиями другого цвета и штриха: по evidence —
  сплошная зелёная, по правилу — пунктир, по опыту РД — точки, не определено — штрих-пунктир.
  Бейдж панели: «сгенерировано, не распознано на П»; у каждого элемента и параметра — своё происхождение.
- Элемент без `evidence_ids` показывает «нет — на листе П не показан»; связь не достраивается.
- В отображении происхождения сети нет значения «наблюдено» (тест `trace.test.ts`).

## 4. Трассировка на примере (сценарий A)

```text
Шаг 3  строка mep.segment_length.v0 · size 50, syn.mat_a · 21.025 м · source_ids [seg-main]
  → Шаг 2  seg-main  derivation evidence_observed, evidence [ev-route-1], шаги [st-3]
             nominal_size_mm = 50  evidence_observed [ev-route-1, ev-txt-2] via st-5
             material = syn.mat_a  deterministic_rule via st-7 (правило syn.material.single.v0)
           st-3 topology · synthetic-retrieval-baseline 0.0.0 · run-demo-001 (d570e83, dirty)
             · case train-case-017 · corpus-demo (train) · 2 альтернативы
  → Шаг 1  ev-route-1  route/polyline на sheet-p3 · mep_model_observed · page_raster raster-p3-150dpi (det) · 0,8
             атрибут syn.size_label = d50 ← ev-txt-2 (pdf_text_layer span-p3-0002)
  → лист   линия (0,20; 0,50) → (0,45; 0,50) подсвечена

Обратно: ev-route-1 → «Элементы сети» [seg-main] → «Строки ВОР» [длина size 50] → шаг 3.
```

Связи — только поля контрактов (`source_ids`, `Derivation`, `InferenceStep.evidence_ids`,
`UnresolvedDecision.subject_ids`) и их обращение: `apps/web/src/lib/mep/trace.ts`.

## 5. Gaps в контрактах

| #   | Gap                                                                                                       | Последствие в UI                                                 |
| --- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 1   | `BoqLine` не хранит вклад каждого источника (сколько метров дал `seg-b1`)                                 | видно только общий итог строки и список источников               |
| 2   | `BoqLine` не ссылается на параметры и шаги, давшие значения группы                                        | путь к шагу — только через элемент сети                          |
| 3   | `mep.parameter_change` и `mep.branch_nodes` ссылаются на узел, но не на участки, чьи значения различаются | участки находятся только из панели узла                          |
| 4   | `QuantityBlocker.subject_ids` и `ContractIssue.subject_id` без вида объекта (лист, узел, профиль)         | интерфейс отличает элементы сети по наличию id в графе           |
| 5   | `SourceRef.ref_id` (ключ растра, id спана) не разрешается в артефакт в MOCK                               | «место на П» — синтетический лист по нормализованным координатам |
| 6   | Узлы и вершины только с отметкой или уровнем не имеют места на плане                                      | на листе не рисуются; видны в списке                             |
| 7   | `EvidenceRelation` не имеет геометрии                                                                     | связи evidence только текстом                                    |
| 8   | Нет сценария `HYBRID_REVIEWED` / `HUMAN_GT`                                                               | блок «Проверка человеком» есть, но в сценариях не показан        |

Ни один gap не закрыт на фронтенде выдуманной связью.

## 6. Файлы

- API: `app/api/v1/mep.py`, `app/api/v1/router.py`, `app/services/mep/scenarios.py`,
  `app/services/mep/fixtures/network_graph_corrupted.v0.3.json`, перенесённые фикстуры,
  `app/core/features.py` (флаг — пилот), `pyproject.toml` (данные пакета).
- Клиент: `packages/api-client` перегенерирован (`listMepScenarios`, `getMepScenario`, типы MEP).
- Web: `app/(portal)/experiments/mep/page.tsx`, `components/mep/*`, `lib/mep/{access,queries,sheet,trace}.ts`,
  `components/mep/__fixtures__/` (снятые с эндпоинта ответы).
- Тесты: `apps/api/tests/test_mep_experiment_api.py`, `apps/web/src/lib/mep/trace.test.ts`,
  `apps/web/src/components/mep/MepExperiment.test.tsx`; `test_control_plane.py` — флаг теперь редактируемый.

## 7. Как открыть

Включить флаг `mep_rd_hypothesis_v1` для пространства в админке (или `FEATURE_FLAGS=mep_rd_hypothesis_v1=true`
локально) и перейти на `/experiments/mep`. Пункта в навигации нет намеренно.

## 8. PROMPT 11.1 — трассировка ВОР

Совместимые дополнения v0.3 (`schema_version` прежний, движок `mep-quantity-engine 0.3.1`).

| Требование               | В контракте                                                                                                                                                            | Проверки                                                                                              |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| вклад источников         | `BoqLine.additive`, `BoqLine.sources[]: LineSource{subject, quantity, canonical_quantity}`; распределение остатка округления — наибольший остаток, при равенстве по id | модель строки отвергает вклады, не дающие итог; порядок входа не влияет                               |
| происхождение группы     | `LineSource.group_values[]: GroupValueRef{key, subject, parameter_key}` — ссылка на параметр элемента сети                                                             | `validate_boq`: `GROUP_VALUE_MISMATCH`, `GROUP_VALUE_UNREFERENCED`                                    |
| участники производных    | `LineSource.participants[]: Participant{subject, role: anchor/connected/compared, parameter_key, value}`                                                               | разветвление: узел + все участки; смена параметра: сравниваемые значения                              |
| типизированные ссылки    | `SubjectRef{kind, id}`, `SubjectKind` — только понятия ядра; `QuantityBlocker.subjects`, `UnresolvedDecision.subjects`; `subject_ids` сохранены                        | `SUBJECT_KIND_MISMATCH`, `UNKNOWN_SUBJECT`, `SUBJECT_REFS_MISMATCH`; неоднозначный id не типизируется |
| сценарий HYBRID_REVIEWED | D: `evidence_graph_hybrid` (модель прочла `d63`, инженер исправил на `d50`; символ сдвинут; история с автором и временем) → `network_graph_hybrid` → ВОР `complete`    | контракты без ошибок; `original` и история сохранены; сеть ссылается на проверенный evidence          |

Все текущие правила аддитивны: метры участков и штуки узлов или поворотов. Поле `additive=false` оставлено
для будущих неаддитивных правил — для них вкладов нет, модель это проверяет.

Пример строки: `mep.segment_length.v0 · size 32 · 48.990 м` ← `seg-b1 24.495 м` + `seg-b2 24.495 м`;
`syn.nominal_size_mm ← segment:seg-b1.parameters.syn.nominal_size_mm`, дальше — `Derivation` параметра
(`rd_prior_inferred`, шаг `st-6`). Разветвление `n-j1`: участники `node n-j1`, `segment seg-main`, `seg-b1`, `seg-b2`.

Интерфейс: разбор выбранной строки (источники, вклад, значения группы ←, участники), типизированные ссылки у
блокеров, «Участник строк» у элемента сети, в сценарии D — бейджи «исправлено/подтверждено человеком»,
таблица «модель → человек», история проверки и серый пунктир исходной геометрии на листе.

Закрыты gaps 1–4 и 8 из § 5. Отложены по решению владельца: ссылки на растр и текстовые спаны,
`PageRasterProvider`, геометрия связей, отображение вертикальных элементов.

Тесты: `apps/api/tests/test_mep_boq_trace.py`, `apps/web/src/components/mep/BoqTrace.test.tsx`; сверка
web-фикстур с эндпоинтом — для всех четырёх сценариев.
