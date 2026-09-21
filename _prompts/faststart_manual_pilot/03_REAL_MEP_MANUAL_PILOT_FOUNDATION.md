# PROMPT 03 — Real MEP Manual Pilot Foundation (основа реального ручного MEP-пилота)

**Модель:** Opus 5  
**Режим мышления:** высокий  
**Цель:** создать отдельный реальный MEP workspace (рабочую область MEP), привязанный к настоящему Project/Revision/Sheet, без AI и без изменения замороженного `/experiments/mep`.

## 1. Архитектурная граница

Заморожено и не меняется:

- `/experiments/mep`;
- MEP contracts v0.3;
- Quantity Engine 0.3.1;
- A/B/C/D fixtures (фикстуры);
- v3 training prompts (промты обучения).

Новый продуктовый контур должен жить отдельно.

Предпочтительный URL:

`/projects/{projectId}/mep?revision={revisionId}&page={page}`

## 2. Новый feature flag (флаг возможности)

Создай отдельный pilot flag, чтобы не смешивать синтетический эксперимент и рабочий ручной режим:

`mep.manual_pilot_v1`

Требования:

- default `False`;
- workspace scoped;
- admin editable только как пилот;
- API + UI deny-by-default;
- `/experiments/mep` продолжает использовать старый `mep_rd_hypothesis_v1`.

Если в репозитории есть строгая naming convention (схема именования), следуй ей и объясни отклонение.

## 3. Реальный источник данных

Страница должна работать с существующими:

- Project;
- DocumentRevision;
- Sheet;
- PageGeometry;
- content URL;
- ScaleCalibration;
- DrawingViewport/pdf.js.

Не делай копию PDF viewer.

## 4. Минимальная persistence (персистентность)

Нужна реальная возможность сохранять ручное MEP-состояние между сессиями.

Сначала исследуй возможность переиспользовать существующие `Measurement` + `measurement_metadata` как низкоуровневое хранилище геометрии **через MEP-адаптер**, не ломая обычный takeoff.

Разрешённый быстрый подход:

- обычные Measurements остаются обычными;
- MEP-записи получают явный namespaced marker (маркер пространства имён), например `measurement_metadata.mep_manual_v1`;
- MEP endpoint (эндпоинт) валидирует metadata и не позволяет произвольному takeoff item случайно стать MEP;
- MEP-specific JSON (специфический JSON MEP) не должен менять смысл generic quantity (общего обмера).

Если существующие ограничения делают это ненадёжным — создай **минимальную** dedicated persistence (отдельное хранение), но не строй универсальную event platform (событийную платформу). Обоснуй выбор.

## 5. Сущности пилота

На этом этапе нужны только контейнеры/сессии:

- MEP manual session/run (ручная сессия/прогон);
- ссылка на project/revision/sheet/profile;
- mode: evidence или network;
- status draft/validated;
- created_by/updated_by;
- version/optimistic locking (оптимистическая блокировка);
- immutable input refs/hashes (неизменяемые ссылки/хеши входа), насколько уже доступны.

Не придумывай классы ВК в core.

## 6. Profile (профиль)

Используй существующий `MepSystemProfile` v0.3.

Если реальный draft profile лежит вне Git в dataset root, UI/API должны уметь работать с выбранным profile reference (ссылкой на профиль) безопасно. Не копируй клиентский профиль в Git.

Для тестов используй synthetic/test profile, не клиентские данные.

## 7. UI skeleton (каркас UI)

На реальной странице должны быть:

- выбор документа/ревизии/листа;
- настоящий PDF;
- шаги: `1. Evidence`, `2. Network`, `3. BOQ`;
- на этом промте шаги 1/2 могут быть empty state;
- отображение выбранного profile id/version;
- сохранённый draft state (черновик);
- явный бейдж `MANUAL PILOT`.

Не переносить синтетические данные в реальную страницу.

## 8. API

Нужны минимальные read/write endpoints (чтение/запись) для pilot session. Все под:

- workspace/project permissions;
- `mep.manual_pilot_v1`;
- строгой проверкой, что revision/sheet принадлежат проекту/пространству.

## 9. Тесты

Минимум:

- flag OFF → API 403 / UI скрыт;
- чужой workspace/project → denied;
- raw PDF geometry-ready → MEP page открывает настоящий лист;
- session сохраняется и читается;
- revision/sheet mismatch → reject;
- MOCK fixtures не затронуты;
- A/B/C/D regression tests проходят.

## 10. Review ZIP

Создай `review/QUANTOR_FASTSTART_P03_REVIEW.zip`.

После отчёта остановись. Не начинай editor (редактор) evidence/network.
