# PROMPT 04 — HUMAN_GT Evidence Editor (ручная эталонная разметка evidence)

**Модель:** Opus 5  
**Режим мышления:** высокий  
**Цель:** инженер на реальном PDF вручную создаёт валидный `MepEvidenceGraph` с `input_mode=HUMAN_GT` без PlanSwift и без моделей.

## 1. Главный принцип

Не создавай новый drawing engine (движок рисования).

Переиспользуй:

- DrawingViewport;
- ToolController;
- point/count geometry (точка);
- polyline (ломаная);
- при необходимости bbox/polygon только если это реально требуется профилем;
- normalized coordinates (нормализованные координаты);
- существующую логику selection/edit/delete/version conflicts.

Новый слой должен быть MEP-специфичным adapter/UI (адаптером/интерфейсом), а не вторым takeoff framework (фреймворком обмеров).

## 2. Profile-driven (управляется профилем)

Классы не хардкодить в React/Python.

Editor читает `MepSystemProfile` и показывает только допустимые:

- evidence class;
- geometry kinds;
- system keys;
- attributes;
- relation types.

Если реальный профиль ещё draft — это нормально. Показывай его status/version/hash.

## 3. Ручной evidence

Пользователь должен уметь:

- выбрать class;
- поставить point / нарисовать polyline / разрешённую геометрию;
- указать system, если известна;
- заполнить profile attributes;
- отметить review state: confirmed / ambiguous / ignore_for_train / not_visible (где это предусмотрено текущей policy);
- добавить raw text/reason/comment при необходимости;
- исправить/удалить черновик;
- сохранить автора и время.

Не превращай «не заполнено» в false/0/пустую уверенную величину.

## 4. Relations (связи)

Нужен минимальный ручной механизм связей между двумя evidence elements:

- выбрать from;
- выбрать to;
- выбрать relation type из profile/policy;
- validate (проверить) допустимость kind/class pair;
- сохранить reason/reviewer.

Не выводить связь по расстоянию автоматически.

## 5. HUMAN_GT graph

Сервер должен уметь собрать из сохранённой разметки настоящий `MepEvidenceGraph v0.3`:

- `input_mode=HUMAN_GT`;
- provenance=`human_ground_truth`;
- status=`human_confirmed` только у реально подтверждённых элементов;
- document/sheet/profile refs и hashes;
- gaps/unresolved — если есть;
- без generated/inferred RD data.

Запускай существующий `validate_evidence_graph`.

Graph JSON должен быть downloadable (скачиваемым) для отладки/датасета, но клиентские данные не класть в Git.

## 6. Не смешивать с обычным takeoff

Если низкоуровневая геометрия хранится в `Measurement`, обычная вкладка «Обмеры» не должна неожиданно показывать MEP-служебные элементы как коммерческие строки, либо должна иметь явное безопасное разделение.

Никакой MEP metadata не должна менять обычный quantity calculation (расчёт количества) Stage 2A.

## 7. UX для реальной работы

Добавь минимум:

- список классов;
- быстрый поиск;
- счётчик размеченных элементов по классу;
- visibility toggle (показ/скрытие);
- selected item inspector (инспектор выбранного элемента);
- понятный индикатор unsaved/saving/saved (не сохранено/сохраняется/сохранено);
- подтверждение перед удалением, если это уже общий паттерн проекта.

Не делай hotkey system (систему горячих клавиш) и batch tooling (пакетные инструменты), если без них пилот работает.

## 8. Реальный пилот без клиентских данных в тестах

Тесты используют synthetic profile/PDF fixture (синтетический профиль/PDF).

Если у владельца в dataset root уже есть реальный profile draft, можно сделать USER_RUN (ручной прогон) на нём, но не копировать данные/названия в Git/report ZIP, если это клиентские данные.

## 9. Acceptance

PASS если:

- на реальном/fixture PDF можно вручную поставить минимум 2 symbols, 1 route, 1 text/anchor (если профиль допускает);
- создать хотя бы 1 relation;
- reload сохраняет всё;
- исправление geometry/attribute сохраняется;
- валидный `MepEvidenceGraph HUMAN_GT` собирается и проходит validator;
- ambiguous не маскируется как confirmed;
- обычный takeoff не сломан.

## 10. Review ZIP

Создай `review/QUANTOR_FASTSTART_P04_REVIEW.zip`.

После отчёта остановись. Не начинай Network editor.
