# PDF → CAD в Quantor

CAD-контур (пилот за флагом `cad.export`, ADR-0036; в бою — образ `deploy/Dockerfile.cad-worker`) использует исходный PDF ревизии, очередь Quantor и отдельный процесс CAD.
Зафиксированный вход — архив `Quantor_CAD_source_2026.11.12_bd4d3f554808.zip` с SHA256
`d153beceb24bf1aac28c3e92e667a5b45f2dba5051cc477e1a45e1d2ec574726`.
Путь к архиву задаётся окружением. Раннер 0.1.0 проверяет версии библиотек, архив, манифест
и хеши извлечённых файлов.

## Воспроизведение на Linux x86-64 с CPython 3.12

В корне checkout задайте `CAD_PYTHON` как абсолютный путь к Python отдельного окружения и
`CAD_ARCHIVE` как абсолютный путь к архиву. Установите колёса из lock-файла и проверьте пакет.

```sh
uv pip install --python "$CAD_PYTHON" --require-hashes --only-binary :all: \
  -r tools/cad_engine/requirements.linux-cp312.lock.txt
"$CAD_PYTHON" -I -B tools/cad_engine/quantor_cad_runner.py verify --archive "$CAD_ARCHIVE"
```

Для исполнителя задайте `CAD_ENGINE_PYTHON=$CAD_PYTHON`, `CAD_ENGINE_ARCHIVE=$CAD_ARCHIVE`
и `CAD_ENGINE_RUNNER` с абсолютным путём к `tools/cad_engine/quantor_cad_runner.py`.
Из `apps/api` запустите CAD-исполнитель командой `python -m app.cad_worker` в окружении API.
Для тестов установите dev-зависимости API в отдельное окружение, используйте одноразовый
PostgreSQL и задайте `QUANTOR_CAD_ENGINE_PYTHON` и `QUANTOR_CAD_ENGINE_ARCHIVE`.

```sh
python -B -m pytest -ra tests/test_cad_qa.py tests/test_jobs_service.py \
  tests/test_worker_claiming.py tests/test_openapi.py
```

Параметры задания — `quantor.cad_engine.params.v2`: `pages` (лист выбирает человек) и `scales`
(`mm_per_pt` и `calibration_id` на страницу из действующей калибровки листа, ADR-0018); без калибровки
API отвечает 409 `CAD_CALIBRATION_REQUIRED`.

Маршрут `POST /api/v1/projects/{project_id}/revisions/{revision_id}/cad` ставит
`cad_pdf_convert`. Статус доступен по `GET …/cad/{job_id}`, файлы по
`GET …/cad/{job_id}/artifacts/{name}`. Индексы страниц в API начинаются с нуля.
Скачиваемый DXF имеет отдельный SHA256 и статус `completed_requires_review`. При
недостаточных размерных подтверждениях доступна диагностика `no_cad_review_required`.
На входе с одними заливками текущий PDFContext может вернуть ошибку, даже если масштаб
подтверждён. Артефакты каждой попытки имеют собственный префикс.

Боевое включение — флаг пространства `cad.export` (ADR-0036); лицензии PyMuPDF/Shapely допущены только
в образе CAD-исполнителя. `CAD_QA_ENABLED` — только QA-режим в локальном и тестовом окружении.

## Генераторы CAD (`cad_mep`, `cad_walls`)

Код генераторов трасс, зон, конструкций и 3D DXF в Quantor не хранится: он лежит в репозитории
движка (`generators/cad_mep`, `generators/cad_walls`) и берётся по пину. В `pins.json` раздел
`generators` фиксирует версии генераторов (`cad_mep.vN`, `cad_walls.vN.M`, `cad_floor3d_dxf.vN`)
и sha256 файлов параметров: `params_sha256` — байты файла (по нему CI сверяет файл движка),
`params_canonical_sha256` — канонический JSON (так считают API и генератор, он идёт в ключи заданий).
API читает из pins только это (`CAD_ENGINE_PINS`, по умолчанию `tools/cad_engine/pins.json`);
исполнитель берёт скрипты из `CAD_GENERATORS_ROOT` (в образе `/opt/cad-engine/generators`) и при
`CAD_MEP_PARAMS` / `CAD_WALLS_PARAMS` сверяет параметры с пином. Нет `CAD_GENERATORS_ROOT` и явных
`CAD_MEP_RUNNER` / `CAD_WALLS_RUNNER` — генератор не настроен, задание отказывает.

### Обновление пина

1. Правки генераторов коммитятся и пушатся в репозиторий движка (CAD_engine), не в Quantor.
2. В чистом checkout CAD_engine на запушенном коммите:
   `python tools/cad_engine/pin_engine.py --engine <путь к checkout CAD_engine>`
   — скрипт пишет `engine.repo_ref` и раздел `generators` (версии из исходников, sha256 параметров).
   Архив движка только сверяется: при расхождении обновите поля `engine.archive_*` вручную по
   `engine/dist/<имя>.json`.
3. `python tools/cad_engine/pin_engine.py --engine <путь> --check` — сверка без записи, код выхода 1
   при расхождении (грязный checkout тоже ошибка).
4. Коммит `tools/cad_engine/pins.json` в Quantor. Образ `quantor-cad-worker` собирает `publish.yml`:
   берёт движок и `generators/` по `repo_ref` и сверяет sha256 параметров с pins.

Локальная сборка образа: скопируйте `generators/cad_mep` и `generators/cad_walls` из checkout движка
в `deploy/cad-engine/generators/` (без `tests/`) — см. шапку `deploy/Dockerfile.cad-worker`.
Тесты API, которым нужен настоящий исходник движка, ищут его в `CAD_ENGINE_SRC` (по умолчанию
`../CAD_engine` рядом с Quantor) и без него пропускаются.
