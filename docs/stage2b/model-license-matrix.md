# Матрица лицензий моделей и ML-зависимостей

Проверено 2026-09-14. Машиночитаемая копия — [`vision/licenses/decisions.json`](../../vision/licenses/decisions.json);
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

| Пакет                         | SPDX                                                                               | Решение                                        | Где                                  | Доказательство (SHA-256 файла лицензии или источник)                                 |
| ----------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------ |
| `torch`                       | BSD-3-Clause; дистрибутив PyPI 2.14.0 — Apache-2.0 AND BSD-2/3 AND MIT AND BSL-1.0 | allow                                          | `vision[train]`                      | pytorch/LICENSE `bd018fee…0e43`                                                      |
| `torchvision`                 | BSD-3-Clause                                                                       | allow                                          | `vision[train]`                      | vision/LICENSE `6502f676…e71d`                                                       |
| `opencv-python-headless`      | Apache-2.0                                                                         | allow + notice                                 | `vision[vectorize]`                  | opencv/LICENSE `cfc7749b…3d30`; PyPI 5.0.0.93                                        |
| `sam2`                        | Apache-2.0                                                                         | allow + notice                                 | `vision[sam]`                        | sam2/LICENSE `c71d239d…0ab4`                                                         |
| `mobile-sam`                  | Apache-2.0                                                                         | allow + notice                                 | `vision[sam]`                        | MobileSAM/LICENSE `c71d239d…0ab4`                                                    |
| `transformers`                | Apache-2.0                                                                         | allow                                          | `vision[qwen]`                       | transformers/LICENSE `77fd4710…2049`                                                 |
| `peft`                        | Apache-2.0                                                                         | allow                                          | `vision[qwen]`                       | peft/LICENSE `c71d239d…0ab4`                                                         |
| `trl`                         | Apache-2.0                                                                         | allow                                          | `vision[qwen]`                       | trl/LICENSE `1bf614b1…8998`                                                          |
| `pypdfium2`                   | BSD-3-Clause OR Apache-2.0 + bundled PDFium                                        | conditional                                    | промт 20                             | PyPI 5.13.0; до образа — список bundled-лицензий, решение 2A пересматривает владелец |
| `segmentation-models-pytorch` | MIT                                                                                | conditional                                    | не в промте 10                       | smp/LICENSE `a9acb108…538c`; каждый энкодер — своя строка                            |
| `shapely`                     | BSD-3-Clause (GEOS LGPL-2.1)                                                       | conditional                                    | `vision[vectorize]`                  | shapely/LICENSE.txt `4a207eac…f754`; в прод-образ — после ADR                        |
| `unsloth`                     | Apache-2.0 для пакета, **AGPL-3.0 файлы внутри wheel**                             | **conditional** (решение владельца 2026-09-14) | `vision[qwen-unsloth]`, промты 12–13 | см. ниже                                                                             |
| `unsloth-zoo`                 | LGPL-3.0-or-later; 41 файл с заголовком AGPL-3.0                                   | **conditional**                                | зависимость unsloth                  | wheel 2026.9.3 `d846a0cd…350c`; COPYING — AGPL-3.0                                   |
| `ultralytics`                 | AGPL-3.0                                                                           | **blocked**                                    | не используется                      | ultralytics/LICENSE `0d96a4ff…abcb0`; PyPI 8.4.152                                   |

## Веса

| Вес                            | SPDX       | Решение    | Ревизия (HF `sha`)                         | Источник                                                    |
| ------------------------------ | ---------- | ---------- | ------------------------------------------ | ----------------------------------------------------------- |
| `Qwen/Qwen3-VL-2B-Instruct`    | Apache-2.0 | allow      | `89644892e4d85e24eaac8bacfd4f463576704203` | HF API `cardData.license: apache-2.0`, не gated, 2025-10-23 |
| `Qwen/Qwen3-VL-4B-Instruct`    | Apache-2.0 | allow      | `ebb281ec70b05090aa6165b016eac8ec08e71b17` | HF API `cardData.license: apache-2.0`, не gated, 2025-10-15 |
| `Qwen/Qwen3-VL-8B-Instruct`    | Apache-2.0 | allow      | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` | HF API `cardData.license: apache-2.0`, не gated, 2025-10-15 |
| `facebook/sam2.1-hiera-small`  | Apache-2.0 | allow      | `ee5bba1d82bb8749febdf90f45e84b687142ba03` | HF API `cardData.license: apache-2.0`                       |
| веса MobileSAM                 | Apache-2.0 | allow      | фиксируется при скачивании                 | репозиторий MobileSAM                                       |
| предобученные веса torchvision | —          | нет строки | —                                          | baseline промта 10 — инициализация с нуля                   |

Репозиторий QwenLM/Qwen3-VL — Apache-2.0 (`c71d239d…0ab4`).

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
- https://raw.githubusercontent.com/huggingface/transformers/main/LICENSE, peft, trl
- https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/LICENSE
- https://huggingface.co/api/models/Qwen/Qwen3-VL-2B-Instruct, -4B-, -8B-, facebook/sam2.1-hiera-small
- https://pypi.org/pypi/pypdfium2/json, torch, ultralytics, unsloth, opencv-python-headless
