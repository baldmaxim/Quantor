# Промт 09 — каркас ML-контура и лицензионный гейт

Дата: 2026-09-14. Граница — [ADR-0021](../adr/0021-oflajn-eksperiment-ne-proizvodstvennaya-vozmozhnost.md),
матрица — [model-license-matrix](model-license-matrix.md). Модели в этом промте не обучались.

> **Обновление 2026-09-14.** Unsloth разрешён владельцем для локального обучения с условиями
> (Р-2, [журнал](owner-decisions.md)); в матрице — `conditional`, extra `vision[qwen-unsloth]`.

## Итог

- **`vision/` — отдельный Python-пакет `quantor-vision`**, не часть `apps/api`: база без
  зависимостей, тяжёлое — в extras `train`, `sam`, `qwen`, `vectorize`, каждая строка которых имеет
  решение в матрице лицензий.
- **Единые команды** `dataset`, `train`, `qwen-build-sft`, `qwen-train`, `qwen-evaluate`,
  `evaluate`, `infer`, `vectorize`, плюс `licenses-check` и `environment`. Команды обучения и оценки
  пока отвечают `BLOCKED` с причинами (модулей нет, GPU нет) и кодом 3 — не делают вид, что работают.
- **Контракт эксперимента** `run.json` со всеми полями промта; запись без метрик, с не-SHA хешем
  разбиения или с несовпадающим хешем весов не пишется.
- **Лицензионный гейт в CI** по всем манифестам репозитория: Ultralytics и Unsloth — `blocked`.
- **Находка аудита: Unsloth blocked.** В wheel `unsloth 2026.9.4` под AGPL-3.0 не только
  `studio/` (1 364 файла), но и `unsloth/kernels/moe` основного пакета. Решение — за владельцем; до
  него SFT Qwen — на `transformers + peft + trl` (Apache-2.0).
- `vision dataset verify` на реальной сборке промта 08 — `ok: true`.

## 1. Структура

```text
vision/
  pyproject.toml            база без зависимостей; extras train / sam / qwen / vectorize
  licenses/decisions.json   машиночитаемая матрица лицензий пакетов и весов
  quantor_vision/
    cli.py                  точки входа
    licenses.py             гейт по манифестам
    runrecord.py            контракт эксперимента run.json
    environment.py          модули, GPU, блокеры команды
  tests/                    без тяжёлых зависимостей, в CI
tools/planswift_gt/         импорт, QA и сборка датасета (промты 06–08) — уже есть
scripts/vision.mjs          запуск интерпретатором venv бэкенда с рабочим каталогом vision
```

Импорт PlanSwift и сборщик датасета оставлены в `tools/planswift_gt`: они работают со стандартной
библиотекой на машине с данными и не требуют окружения обучения. `vision` читает их результат по
файлам и хешам — через `dataset verify`, а не импортом кода.

`apps/api` по-прежнему не видит ни torch, ни SAM, ни Transformers: `test_contracts.py` запрещает их в
его `pyproject.toml`, гейт `vision` — вне разрешённых мест во всём репозитории.

## 2. Команды

| Команда              | Сейчас                                                                          | Промт    |
| -------------------- | ------------------------------------------------------------------------------- | -------- |
| `dataset verify DIR` | работает: хеши `split.json`/`tiles.jsonl`/видов, проверки утечки, метка holdout | 08 → 10+ |
| `licenses-check`     | работает: все `pyproject.toml`, `requirements*.txt`, `package.json`             | 09       |
| `environment`        | работает: GPU, недостающие модули, заблокированные пакеты                       | 09       |
| `train`              | BLOCKED: нет `torch`, `torchvision`, нет NVIDIA GPU                             | 10, 15   |
| `qwen-build-sft`     | NOT_IMPLEMENTED                                                                 | 12       |
| `qwen-train`         | BLOCKED: нет `torch`, `transformers`, `peft`, `trl`, нет GPU                    | 13       |
| `qwen-evaluate`      | BLOCKED: нет `torch`, `transformers`, нет GPU                                   | 14       |
| `evaluate`           | BLOCKED: нет `torch`                                                            | 10–18    |
| `infer`              | BLOCKED: нет `torch`; по пакету — только после PASS промта 18                   | 20       |
| `vectorize`          | BLOCKED: нет `cv2`                                                              | 16–17    |

Запуск: `pnpm vision <команда>`; проверка каркаса — `pnpm test:vision`; гейт — `pnpm lint:licenses`.

## 3. Контракт эксперимента — `run.json`

| Поле промта                      | Поле записи                                                | Проверка                              |
| -------------------------------- | ---------------------------------------------------------- | ------------------------------------- |
| task                             | `task`                                                     | из закрытого списка задач             |
| dataset fingerprint + split hash | `dataset_fingerprint`, `split_sha256`                      | оба — SHA-256                         |
| model architecture               | `architecture`                                             | не пусто                              |
| weight initialization/provenance | `initialization`: `scratch` или вес с ревизией из матрицы  | не пусто                              |
| seed                             | `seed`                                                     | —                                     |
| preprocessing / augmentation     | `preprocessing`, `augmentation`                            | —                                     |
| training params                  | `training`                                                 | —                                     |
| software versions                | `software`: python, платформа, версии torch/transformers/… | есть версия python                    |
| git/source state                 | `source_state`: коммит и «грязное» дерево                  | есть `git_commit` (или `unavailable`) |
| output weights SHA-256           | `weights[]`: путь и SHA-256                                | файл есть, хеш совпадает              |
| metrics JSON                     | `metrics`                                                  | не пусто                              |

## 4. Лицензионный гейт

- Охраняемые пакеты: Ultralytics, Unsloth и unsloth-zoo, torch, torchvision, SAM 2, MobileSAM,
  segment-anything, Transformers, PEFT, TRL, Accelerate, bitsandbytes, OpenCV (три варианта),
  segmentation-models-pytorch, timm, Shapely, pypdfium2, onnxruntime, vLLM.
- Нарушение — охраняемый пакет в любом манифесте при решении `blocked` или без строки в матрице.
- Имена нормализуются (`Ultralytics`, `ultralytics>=8`, `unsloth[colab]` — тот же пакет);
  `node_modules`, окружения и сборки не обходятся.
- CI: новый job «ML-контур, датасет и лицензии» — гейт, ruff/mypy/pytest `vision` и
  `tools/planswift_gt` на синтетике, без тяжёлых зависимостей и без частных данных.
- `.gitignore` дополнен весами: `*.safetensors`, `*.pt`, `*.pth`, `*.ckpt`, `*.onnx`, `*.gguf`.

## 5. Окружение этой машины

`vision environment`: NVIDIA GPU нет, `torch`, `torchvision`, `transformers`, `peft`, `trl`, `sam2`,
`cv2` не установлены; заблокированы по лицензии `ultralytics`, `unsloth`, `unsloth-zoo`. Отсюда —
промты 10, 11, 13–15 в этой среде будут BLOCKED по обучению; конвейер можно готовить, числа — нет.

## 6. Проверки

| Команда                                      | Результат                                       |
| -------------------------------------------- | ----------------------------------------------- |
| `pnpm test:vision`                           | ruff, mypy strict — чисто; 13 passed; гейт `ok` |
| `pnpm test:planswift`                        | 61 passed                                       |
| `vision dataset verify <planswift-build-v1>` | `ok: true`                                      |
| `vision train --epochs 1`                    | `BLOCKED`, код 3                                |

Тесты: гейт зелёный на реальном репозитории; Ultralytics в extras `pyproject.toml` и в
`requirements-train.txt` — два нарушения; неизвестный охраняемый пакет в `package.json` требует
решения; `conditional` проходит, `blocked` — нет; `node_modules` не сканируется; матрица блокирует
Ultralytics и Unsloth; полная запись прогона пишется, неполная — отказ, хеш весов сверяется с файлом;
команды обучения отвечают BLOCKED/NOT_IMPLEMENTED кодом 3; проверка сборки ловит изменённый
`tiles.jsonl` и проваленную проверку утечки.

## 7. Решения владельца

1. **Unsloth**: разрешить ли окружение обучения с AGPL-файлами wheel (без распространения и без
   запуска Studio) — или остаться на `transformers + peft + trl`.
2. **GPU-хост** для промтов 10–15: без него обучение и числа моделей — BLOCKED.
3. Скачивание весов Qwen и SAM с Hugging Face на GPU-хост — по ревизиям из матрицы.
