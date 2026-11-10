# PDF → CAD в Quantor

CAD-контур (пилот за флагом `cad.export`, ADR-0036; в бою — образ `deploy/Dockerfile.cad-worker`) использует исходный PDF ревизии, очередь Quantor и отдельный процесс CAD.
Зафиксированный вход — архив `Quantor_CAD_source_2026.11.10_e37b347ff1a4.zip` с SHA256
`8daba71dc7d81dffe564408eea68984974ecbeff71d25317d9046b20fe0ca275`.
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
