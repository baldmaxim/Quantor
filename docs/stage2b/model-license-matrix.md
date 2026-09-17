# Матрица лицензий моделей и ML-зависимостей

Проверено 2026-09-14, дополнено 2026-09-15 (промты 11 и 12). Машиночитаемая копия — [`vision/licenses/decisions.json`](../../vision/licenses/decisions.json);
её читает гейт `pnpm lint:licenses` в CI. Не юридическое заключение: решение `allow` значит «есть
задокументированный permissive-путь», а не «проверено юристом».

Правила:

- пакет из охраняемого списка (фреймворки обучения, SAM, VLM-стек, OpenCV, Shapely, pypdfium2,
  Ultralytics, Unsloth…) попадает в любой манифест репозитория только при решении `allow` или
  `conditional`; `blocked` или отсутствие строки — красный CI;
- лицензия веса — отдельная строка с ревизией; лицензия Python-пакета на веса не переносится;
- версия и ревизия фиксируются в записи прогона (`run.json`) при первом настоящем скачивании —
  здесь ориентир на дату проверки.

## Пакеты

| Пакет                         | SPDX                                                                               | Решение                                        | Где                                              | Доказательство (SHA-256 файла лицензии или источник)                                                           |
| ----------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `torch`                       | BSD-3-Clause; дистрибутив PyPI 2.14.0 — Apache-2.0 AND BSD-2/3 AND MIT AND BSL-1.0 | allow                                          | `vision[train]`                                  | pytorch/LICENSE `bd018fee…0e43`                                                                                |
| `torchvision`                 | BSD-3-Clause                                                                       | allow                                          | `vision[train]`                                  | vision/LICENSE `6502f676…e71d`                                                                                 |
| `opencv-python-headless`      | Apache-2.0                                                                         | allow + notice                                 | `vision[vectorize]`                              | opencv/LICENSE `cfc7749b…3d30`; PyPI 5.0.0.93                                                                  |
| `sam2` (PyPI)                 | Apache-2.0 заявлено                                                                | **blocked**                                    | не используется                                  | PyPI `sam2` 1.1.0 — сторонний форк `JinsuaFeito-dev/segment-anything-2`, не Meta; SAM 2 — через `transformers` |
| `mobile-sam`                  | Apache-2.0                                                                         | **blocked**                                    | промт 11 не выполнен                             | MobileSAM/LICENSE `c71d239d…0ab4`; на PyPI нет, только git + `timm` без решения                                |
| `transformers`                | Apache-2.0                                                                         | allow                                          | `vision[sam]`, `vision[qwen]`; 5.5.0             | transformers/LICENSE `77fd4710…2049`                                                                           |
| `peft`                        | Apache-2.0                                                                         | allow                                          | `vision[qwen]`; 0.20.0                           | peft/LICENSE `c71d239d…0ab4`                                                                                   |
| `trl`                         | Apache-2.0                                                                         | allow                                          | `vision[qwen]`; 0.24.0                           | trl/LICENSE `1bf614b1…8998`                                                                                    |
| `accelerate`                  | Apache-2.0                                                                         | allow                                          | `vision[qwen-unsloth]`; 1.15.0                   | accelerate/LICENSE `c71d239d…0ab4`                                                                             |
| `bitsandbytes`                | MIT                                                                                | allow + условие                                | `vision[qwen-unsloth]`; 0.50.2                   | bitsandbytes/LICENSE `52412d7b…fc85`; 4 бита продвигаются только по измеренному качеству QTO                   |
| `pypdfium2`                   | BSD-3-Clause OR Apache-2.0 + bundled PDFium                                        | conditional                                    | `tools/planswift_gt[pdf]` 5.13.0 (Р-9); промт 20 | PyPI 5.13.0; офлайн-импорт — да; в образ — после списка bundled-лицензий PDFium                                |
| `segmentation-models-pytorch` | MIT                                                                                | conditional                                    | не в промте 10                                   | smp/LICENSE `a9acb108…538c`; каждый энкодер — своя строка                                                      |
| `shapely`                     | BSD-3-Clause (GEOS LGPL-2.1)                                                       | conditional                                    | `vision[vectorize]`                              | shapely/LICENSE.txt `4a207eac…f754`; в прод-образ — после ADR                                                  |
| `unsloth`                     | Apache-2.0 для пакета, **AGPL-3.0 файлы внутри wheel**                             | **conditional** (решение владельца 2026-09-14) | `vision[qwen-unsloth]`, промты 12–13             | см. ниже                                                                                                       |
| `unsloth-zoo`                 | LGPL-3.0-or-later; 41 файл с заголовком AGPL-3.0                                   | **conditional**                                | зависимость unsloth                              | wheel 2026.9.3 `d846a0cd…350c`; COPYING — AGPL-3.0                                                             |
| `ultralytics`                 | AGPL-3.0                                                                           | **blocked**                                    | не используется                                  | ultralytics/LICENSE `0d96a4ff…abcb0`; PyPI 8.4.152                                                             |

## Веса

| Вес                               | SPDX                 | Решение         | Ревизия (HF `sha`)                         | Источник                                                           |
| --------------------------------- | -------------------- | --------------- | ------------------------------------------ | ------------------------------------------------------------------ |
| `Qwen/Qwen3-VL-2B-Instruct`       | Apache-2.0           | allow           | `89644892e4d85e24eaac8bacfd4f463576704203` | HF API `cardData.license: apache-2.0`, не gated, 2025-10-23        |
| `Qwen/Qwen3-VL-4B-Instruct`       | Apache-2.0           | allow           | `ebb281ec70b05090aa6165b016eac8ec08e71b17` | HF API `cardData.license: apache-2.0`, не gated, 2025-10-15        |
| `Qwen/Qwen3-VL-8B-Instruct`       | Apache-2.0           | allow           | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` | HF API `cardData.license: apache-2.0`, не gated, 2025-10-15        |
| `facebook/sam2.1-hiera-small`     | Apache-2.0           | allow           | `ee5bba1d82bb8749febdf90f45e84b687142ba03` | HF API `cardData.license: apache-2.0`                              |
| `facebook/sam2.1-hiera-tiny`      | Apache-2.0           | allow           | `de431c4043854a71d8101e17995dfe596bf101a5` | HF API, формат `transformers`; `model.safetensors` `48c14467…c2a7` |
| `facebook/sam2.1-hiera-base-plus` | Apache-2.0           | allow           | `b7320756a13354e7530a63935656d35b2f91a290` | HF API, формат `transformers`                                      |
| `facebook/dinov2-large`           | Apache-2.0           | allow           | `47b73eefe95e8d44ec3623f8890bd894b6ea2d6c` | HF API, не gated; `model.safetensors` `399fba97…2e23`; Р-8         |
| `facebook/dinov2-base`            | Apache-2.0           | allow           | `f9e44c814b77203eaa57a6bdbbd535f21ede1415` | HF API, не gated; `model.safetensors` `d73036b5…0841`; запасной    |
| веса DINOv3 (SU10)                | лицензия Meta DINOv3 | не используются | —                                          | нужна проверка лицензии до любого использования (Р-7)              |
| веса MobileSAM                    | Apache-2.0           | не используются | —                                          | MobileSAM заблокирован как зависимость (промт 11)                  |
| предобученные веса torchvision    | —                    | нет строки      | —                                          | baseline промта 10 — инициализация с нуля                          |

Репозиторий QwenLM/Qwen3-VL — Apache-2.0 (`c71d239d…0ab4`).

### Qwen3-VL: карточки и хеши родительских весов (промт 12)

Ревизии и SHA-256 файлов сверены повторно 2026-09-15 через `api/models/<id>/revision/<sha>?blobs=true`
до скачивания; закреплены в [`vision/quantor_vision/qwen/models.py`](../../vision/quantor_vision/qwen/models.py)
и в `decisions.json`. `vision qwen-env fetch` отказывает, если скачанный файл не совпал. Лицензия
весов — из карточки модели (`cardData.license`), а не из лицензии пакета `transformers`.

| Модель      | Роль                     | Карточка на ревизии                                                     | Файлы весов и SHA-256                                                       |
| ----------- | ------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 2B Instruct | нижняя граница           | `huggingface.co/Qwen/Qwen3-VL-2B-Instruct/blob/89644892…4203/README.md` | `model.safetensors` `7de1838c…77a0`                                         |
| 4B Instruct | основная                 | `huggingface.co/Qwen/Qwen3-VL-4B-Instruct/blob/ebb281ec…1b17/README.md` | `-00001-of-00002` `30a01a05…39a9`, `-00002-of-00002` `046296a2…02a6`        |
| 8B Instruct | условная верхняя граница | `huggingface.co/Qwen/Qwen3-VL-8B-Instruct/blob/0c351dd0…ff3b/README.md` | 4 файла: `d5d0aef0…aefa`, `8be88fb5…06b5`, `83de00ea…2192`, `0a88b98e…77a5` |

Thinking-редакции не используются: нужен строгий структурированный ответ, а не рассуждение.

### Стек обучения Qwen (промт 12)

Одно окружение `vision\.venv-unsloth`, только на GPU-машине владельца, из
[`vision/requirements-qwen-unsloth.txt`](../../vision/requirements-qwen-unsloth.txt); полный снимок
после установки — `requirements-qwen-unsloth.lock.txt` (его тоже проверяет гейт).

| Компонент                                                                                  | Версия                           | Лицензия                                        | Замечание                                                                               |
| ------------------------------------------------------------------------------------------ | -------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------- |
| `unsloth`                                                                                  | 2026.9.4, wheel `7892ac14…5264`  | Apache-2.0 + AGPL-3.0 файлы                     | Р-2; Studio (`studio/` в wheel) не запускается, не встраивается, не вендорится          |
| `unsloth-zoo`                                                                              | 2026.9.3, wheel `d846a0cd…350c`  | LGPL-3.0-or-later + AGPL-3.0 файлы              | те же условия                                                                           |
| `torch` / `torchvision`                                                                    | 2.11.0+cu128 / 0.26.0+cu128      | BSD-3-Clause                                    | Unsloth требует `torch < 2.13`                                                          |
| CUDA-библиотеки в колёсах cu128                                                            | CUDA 12.8, cuDNN из колеса torch | NVIDIA Software License                         | не распространяются: окружение остаётся на машине владельца                             |
| `xformers`                                                                                 | 0.0.35                           | BSD-3-Clause (xformers/LICENSE `8b069586…b7ea`) | зависимость Unsloth на Windows                                                          |
| `transformers`                                                                             | 5.5.0                            | Apache-2.0                                      | верхняя граница Unsloth                                                                 |
| `trl`, `peft`, `accelerate`                                                                | 0.24.0, 0.20.0, 1.15.0           | Apache-2.0                                      | —                                                                                       |
| `bitsandbytes`                                                                             | 0.50.2                           | MIT                                             | только QLoRA-эксперимент                                                                |
| `datasets`                                                                                 | 4.3.0 (Unsloth: `< 4.4.0`)       | Apache-2.0 (datasets/LICENSE `cfc7749b…3d30`)   | —                                                                                       |
| транзитивные: `triton-windows`, `torchao`, `diffusers`, `cut-cross-entropy`, `hf_transfer` | из lock-файла                    | MIT / BSD-3 / Apache-2.0 / по lock              | лицензии сверяются по lock-файлу; пакет из охраняемого списка без строки — красный гейт |

### Адаптер и слитые веса: происхождение

- Выход обучения промта 13 — PEFT-адаптер (`adapter_model.safetensors`, `adapter_config.json`),
  сохранённый стандартным `save_pretrained` и загружаемый **без Unsloth** (`transformers + peft`).
- В `run.json` пишутся: SHA-256 каждого файла адаптера; родитель — `repo_id`, полная ревизия и SHA-256
  всех файлов весов из таблицы выше; SHA-256 wheel `unsloth` и `unsloth-zoo` и `RECORD` установленных
  пакетов; версии стека; SHA-256 SFT-набора (`sft.json`).
- Слитые веса (merge) по умолчанию не делаются. Если сделаны — отдельный SHA-256 каждого файла и
  ссылка на адаптер и родителя; лицензия слитых весов — Apache-2.0 родителя, код Unsloth в веса не
  попадает.

## Unsloth: AGPL внутри пакета и условия разрешения

Текст пакета промтов предполагал «core Apache-2.0, AGPL — только Studio UI, его просто не встраивать».
Аудит конкретного артефакта это не подтвердил:

- wheel `unsloth-2026.9.4-py3-none-any.whl` (SHA-256 `7892ac14733ba22200ef4a228ac26e06275562c5f72b96a654605d4dcbd05264`)
  содержит **1 364 файла `studio/`** с `studio/LICENSE.AGPL-3.0` — Studio ставится вместе с пакетом,
  даже если его не запускать;
- `unsloth/kernels/moe/LICENSE` и `unsloth/kernels/moe/grouped_gemm/LICENSE` — **AGPL-3.0**, и это
  каталог основного пакета, а не Studio;
- `dist-info/licenses/COPYING` — AGPL-3.0 рядом с Apache-2.0 `LICENSE`; `License-Expression` в
  METADATA — `Apache-2.0`, то есть метаданные неполны;
- README: «dual-licensing model of Apache 2.0 and AGPL-3.0».

- `unsloth-zoo 2026.9.3` (SHA-256 `d846a0cdf343ff4ca79a01806e45249362b4ad107442d3c68d32cee3527d350c`)
  объявлен LGPL-3.0-or-later, но `COPYING` — AGPL-3.0 и 41 файл `.py` с заголовком AGPL-3.0.

**Решение владельца 2026-09-14** ([журнал](owner-decisions.md), Р-2): Unsloth разрешён для обучения
в локальном окружении при условиях — не в `apps/api` и не в производственном образе; окружение и
образы с файлами Unsloth не распространяются; Studio не запускается и не встраивается; checkpoint
сохраняется стандартным safetensors / PEFT-адаптером и грузится без Unsloth; версии и SHA-256 wheel
пишутся в `run.json`. `transformers + peft + trl` (Apache-2.0) остаются запасным путём и путём
инференса. Формулировка `CLAUDE.md` обновлена под эти условия.

## Источники

- https://raw.githubusercontent.com/facebookresearch/sam2/main/LICENSE
- https://raw.githubusercontent.com/ChaoningZhang/MobileSAM/master/LICENSE
- https://raw.githubusercontent.com/opencv/opencv/4.x/LICENSE
- https://raw.githubusercontent.com/ultralytics/ultralytics/main/LICENSE
- https://raw.githubusercontent.com/pytorch/pytorch/main/LICENSE, https://raw.githubusercontent.com/pytorch/vision/main/LICENSE
- https://raw.githubusercontent.com/qubvel-org/segmentation_models.pytorch/main/LICENSE
- https://raw.githubusercontent.com/shapely/shapely/main/LICENSE.txt
- https://raw.githubusercontent.com/unslothai/unsloth/main/LICENSE, README.md (раздел License), wheel 2026.9.4 на PyPI
- https://raw.githubusercontent.com/huggingface/transformers/main/LICENSE, peft, trl, accelerate, datasets
- https://raw.githubusercontent.com/bitsandbytes-foundation/bitsandbytes/main/LICENSE, facebookresearch/xformers
- https://pypi.org/pypi/unsloth/2026.9.4/json, unsloth-zoo/2026.9.3 — `requires_dist` для закрепления версий
- https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/LICENSE
- https://huggingface.co/api/models/Qwen/Qwen3-VL-2B-Instruct, -4B-, -8B-, facebook/sam2.1-hiera-small
- https://pypi.org/pypi/pypdfium2/json, torch, ultralytics, unsloth, opencv-python-headless

## MEP D0: чтение текстового слоя и метаданных

`pypdf==6.18.0` — BSD-3-Clause, allow для `vision[mep-discovery]`. Версия совпадает с порталом; проверен установленный `dist-info/licenses/LICENSE`, SHA-256 `a97ac230e5f33ef10a5367a850eb01f91f1a0b064e34742c7794d2294557f524`. Только офлайн-опись PDF без OCR/рендера. Новых зависимостей для CAD и BIM нет.
