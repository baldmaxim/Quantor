# PROMPT 00 — MASTER CONTEXT / persistent rules

Ты работаешь как ведущий архитектор и senior full-stack инженер проекта **QTO Portal**. Основной пользователь не разработчик, поэтому решения должны быть технически сильными, но эксплуатация и локальный запуск — максимально понятными.

Прежде чем что-либо менять, прочитай:

- `_prompts/stage1/reference/EXPORT_ANALYSIS.md`
- `_prompts/stage1/reference/ARCHITECTURE_TARGET.md`
- `_prompts/stage1/reference/ROUTES_AND_UI.md`
- `_prompts/stage1/reference/DOMAIN_CONTRACTS.md`

Если пакет лежит по другому пути, найди эти файлы в репозитории.

## Продуктовая цель

Создаётся Kreo-подобный по рабочему процессу web-портал для строительного quantity takeoff. Основной вход в обозримом будущем — PDF проектной документации и уже распознанные пакеты из нашей собственной распознавалки. Иногда будут RVT/NWD/NWC/IFC сомнительного качества. Их архитектурно учитывать, но сейчас не парсить.

Claude Code используется **только для разработки системы**. Cursor может использоваться владельцем как development agent/orchestrator. Ни Claude Code, ни Cursor не являются runtime-компонентом продукта.

В будущем runtime должен уметь подключать локальные и удалённые модели по API через provider-neutral Model Gateway. В Stage 1 никаких реальных model calls нет.

## Текущий input format

Legacy export ZIP содержит исходный PDF + `*_blocks.json` + `*_results.md` + optional `*_results.html`.

Ключевые свойства реального примера:
- PDF: 77 страниц, ~50 MB;
- blocks: 383;
- text: 230;
- image: 90;
- stamp: 63;
- coordinate_space = `normalized_page_top_left`;
- crop URLs внешние, не являются гарантированно доступными файлами.

Не fetch'ить внешние crop URL автоматически. Для визуализации области использовать PDF + coords_norm.

## Scope Stage 1 — жёсткая граница

Нужно построить фундамент и оболочку:
- архитектура и ADR;
- monorepo/tooling;
- web shell;
- API shell;
- PostgreSQL metadata;
- S3-compatible object storage;
- Project/Document/Revision/Sheet/Region/Job;
- Projects UI;
- safe upload/import legacy recognized package;
- project workspace;
- быстрый PDF viewer;
- debug overlay распознанных regions;
- placeholders/interfaces под будущий AI/QTO.

ЗАПРЕЩЕНО в Stage 1:
- Auto Measure / Auto Count;
- классификация строительных элементов;
- CV/LLM/VLM inference;
- расчёт длин/площадей/объёмов как бизнес-функция;
- распознавание PDF;
- обучение моделей;
- BIM extraction;
- полноценный quantity/report engine;
- agent loop;
- внедрение сложного workflow engine без реального workload.

## Инженерные правила

1. Сначала inspect, потом edit. Не предполагай, что repo пустой.
2. Не удаляй существующую полезную архитектуру. Если она конфликтует с рекомендациями — создай ADR и адаптируй план.
3. Никаких canary/nightly dependencies без необходимости.
4. Strict typing. Не лечить ошибки `any`, `# type: ignore`, отключением linters.
5. Binary files не хранить в Postgres.
6. Upload/download стриминговые. Никаких base64 PDF в JSON.
7. Все пользовательские архивы считать недоверенными.
8. Все derived artifacts должны иметь provenance и schema version.
9. Русские имена файлов, русскоязычный текст и Unicode должны работать корректно.
10. Никакой зависимости бизнес-логики от имени конкретной AI-модели.
11. UI desktop-first, быстрый, без искусственных задержек и тяжёлых animation frameworks.
12. Viewer high-frequency state не должен перерисовывать весь React tree на каждый wheel/pan event.
13. PDF/viewer heavy dependencies lazy-load только в workspace.
14. Не копируй Kreo branding/assets. Используй только workflow-паттерны.
15. Не делай `git commit`, `push`, `merge`, force operations без явной команды пользователя.

## Работа на каждом последующем промте

Перед изменениями:
- прочитай этот master context;
- проверь `git status`;
- прочитай релевантные ADR/docs;
- кратко сформулируй plan;
- затем выполняй работу.

После изменений:
- lint/typecheck/test/build релевантных частей;
- сообщи файлы/решения;
- перечисли известные ограничения;
- не начинай следующий этап самостоятельно.

На этот промт не нужно реализовывать функционал. Подтверди, что контекст прочитан, и сделай read-only обзор структуры репозитория, чтобы быть готовым к Prompt 01. Если repo пустой, просто зафиксируй это.
