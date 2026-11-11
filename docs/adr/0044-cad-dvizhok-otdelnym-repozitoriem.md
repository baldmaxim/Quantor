# ADR-0044. CAD-движок — отдельный встраиваемый репозиторий, Quantor берёт его по пину

Дата: 2026-11-11
Статус: принято владельцем 2026-11-11

## Контекст

CAD-конвейер листа состоял из трёх частей в двух репозиториях:

- преобразование PDF → DXF — репозиторий `baldmaxim/CAD_engine`, Quantor пинует его в `tools/cad_engine/pins.json`;
- конструкции `tools/cad_walls` и зоны с трассами `tools/cad_mep` — код внутри Quantor.

Почти все доработки «движка» шли в `tools/cad_*` Quantor, поэтому в `CAD_engine` с 2026-11-10 был один коммит,
а история движка смешивалась с историей портала. `cad_walls` и `cad_mep` не импортируют `apps/api`: API читает у
них только версию генератора и sha256 параметров, исполнитель запускает их подпроцессом интерпретатором движка.

## Решение

1. `cad_mep` и `cad_walls` переезжают в `CAD_engine/generators/` с историей (`git subtree`). Из Quantor
   `tools/cad_mep` и `tools/cad_walls` удаляются. Движок — встраиваемый: вход и выход файлами, вызов CLI, ничего не
   знает о Quantor (правила — `CAD_engine/CLAUDE.md`).
2. Доработки движка коммитятся и пушатся в `CAD_engine`, доработки портала — в Quantor. Связь — только пин.
3. Пин один на весь движок: `pins.json` хранит `engine.repo_ref` (коммит `CAD_engine`), архив преобразования и
   раздел `generators` — версии `cad_mep`, `cad_walls`, `cad_floor3d_dxf` и sha256 их параметров. Обновляет пин
   `tools/cad_engine/pin_engine.py --engine <checkout>`, затем коммит `pins.json` в Quantor.
4. API берёт версию генератора и sha256 параметров из `pins.json`. Исполнитель в образе сверяет файл параметров
   с пином и при расхождении не работает.
5. Образ `quantor-cad-worker` собирается из `CAD_engine` по `repo_ref` (`publish.yml`): архив преобразования и
   `generators/` в `/opt/cad-engine/`. В образ API код генераторов не попадает, как и раньше.

## Последствия

- Изменения результата CAD видны в истории `CAD_engine`; в Quantor — только смена пина.
- Выкатка новой версии движка = пуш в `CAD_engine` + обновление пина в Quantor + обычная выкатка Quantor.
- Локальный запуск исполнителя требует checkout `CAD_engine` (рядом с Quantor: `../CAD_engine`) и настроек
  `CAD_GENERATORS_ROOT` / `CAD_*_RUNNER`.
- Ссылки на `tools/cad_mep` и `tools/cad_walls` в ADR-0036…0042 и отчётах — история; действующее место —
  `CAD_engine/generators/`.
- Уточняет ADR-0036 (состав исполнителя CAD) и ADR-0038 (место скрипта конструкций).
