# Промт 12. Qwen3-VL + Unsloth: контракт SFT-набора и окружение обучения

Дата: 2026-09-15. Модель в этом промте не обучается.

## Статус

| Часть                                                    | Статус                                                                                                      |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| модели закреплены: ревизия и SHA-256 весов до скачивания | готово (§ 1)                                                                                                |
| матрица лицензий: Qwen, Unsloth, стек, адаптер           | готово ([матрица](model-license-matrix.md))                                                                 |
| окружение: закреплённые зависимости                      | готово: `vision/requirements-qwen-unsloth.txt`; снимок `…lock.txt` — **после установки владельцем**         |
| проверка GPU и BF16, скачивание, дымовой прогон          | код готов; **BLOCKED до прогона на RTX 5050** (§ 6)                                                         |
| адаптер SFT из сборки промта 08                          | код готов; **счётчики — после прогона владельцем** (§ 6)                                                    |
| строгий парсер ответа                                    | готово (§ 4)                                                                                                |
| синтетические тесты                                      | написаны (`vision/tests/test_qwen.py`); **на машине разработки не запускались** — прогон у владельца и в CI |

На машине разработки окружения нет по решению владельца: ruff, mypy и pytest запускает владелец
(§ 6, шаг 7) и CI после отправки. До их отчёта ни одна строка выше не записывается как PASS.

## 1. Модели

| Ключ | Модель                      | Роль                                                                | Ревизия                                    |
| ---- | --------------------------- | ------------------------------------------------------------------- | ------------------------------------------ |
| `2b` | `Qwen/Qwen3-VL-2B-Instruct` | нижняя граница эффективности                                        | `89644892e4d85e24eaac8bacfd4f463576704203` |
| `4b` | `Qwen/Qwen3-VL-4B-Instruct` | основная                                                            | `ebb281ec70b05090aa6165b016eac8ec08e71b17` |
| `8b` | `Qwen/Qwen3-VL-8B-Instruct` | условная: только если 4B оставляет неоднозначность и хватает памяти | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` |

Ревизии совпали с записанными 2026-09-14; SHA-256 файлов весов сняты 2026-09-15 из API Hugging Face
до скачивания и лежат в `vision/quantor_vision/qwen/models.py` и `decisions.json` (тест сверяет, что
они одинаковы). `qwen-env fetch` скачивает ровно эту ревизию и отказывает при несовпадении хеша —
адаптер от другого родителя несравним. Thinking-редакции не используются.

**Память RTX 5050 (8 ГБ).** Веса 4B в BF16 — 8,9 ГБ: в память не помещаются. Поэтому BF16-базовая
линия меряется на 2B (4,3 ГБ), а 4B идёт через 4-битный QLoRA — как эксперимент экономии памяти,
продвижение которого требует измеренного качества QTO (промт 18). Попытка 4B BF16 входит в дымовой
прогон, чтобы отказ был измерен, а не предположен.

## 2. Окружение

- Отдельный `vision\.venv-unsloth` (закрыт `.gitignore` правилом `.venv-*/`), Python 3.12, только на
  машине владельца. Не `apps/api`, не производственный образ, не распространяется (Р-2).
- Прямые зависимости закреплены в `vision/requirements-qwen-unsloth.txt`: `torch 2.11.0+cu128`,
  `torchvision 0.26.0+cu128`, `xformers 0.0.35`, `transformers 5.5.0`, `trl 0.24.0`, `peft 0.20.0`,
  `accelerate 1.15.0`, `bitsandbytes 0.50.2`, `datasets 4.3.0`, `unsloth 2026.9.4`,
  `unsloth-zoo 2026.9.3`. Границы взяты из `requires_dist` Unsloth на PyPI: `torch < 2.13`,
  `transformers ≤ 5.5.0`, `trl ≤ 0.24.0`, `datasets < 4.4.0`, `peft ≥ 0.18`.
- Полный снимок — `vision/requirements-qwen-unsloth.lock.txt` из `pip freeze` после установки. Резолвер
  на машине разработки не запускался (нет места и нет CUDA-колёс), поэтому снимок снимает владелец;
  лицензионный гейт проверяет и его — пакет из охраняемого списка без решения даёт красный CI.
- Wheel `unsloth` и `unsloth-zoo` сверяются с SHA-256 из матрицы до установки.
- Studio из wheel не запускается. Установка Studio в `%USERPROFILE%\.unsloth\studio` не используется.

### Телеметрия и сеть

`vision qwen-env` до первого импорта тяжёлых пакетов выставляет `HF_HUB_DISABLE_TELEMETRY=1`,
`HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, `DO_NOT_TRACK=1`, `WANDB_MODE=disabled`, `WANDB_DISABLED=true`,
`DISABLE_MLFLOW_INTEGRATION=TRUE`, `UNSLOTH_DISABLE_STATISTICS=1`. Дымовой прогон дополнительно
идёт с `HF_HUB_OFFLINE=1`: веса уже скачаны и сверены, любая попытка сети — ошибка, видимая в записи.
Что установленный Unsloth действительно проверяет `UNSLOTH_DISABLE_STATISTICS`, `probe` подтверждает
поиском по исходникам пакета; если проверки нет — `BLOCKED`, а не догадка. W&B и облако не
подключаются; в промте 13 обучение идёт с `report_to="none"`.

## 3. SFT-наборы

`vision qwen-build-sft --build <сборка 08> --out <каталог вне репозитория>`. Код —
`vision/quantor_vision/qwen/{targets,sft}.py`, только стандартная библиотека.

```text
<out>/sft.json                                   хеши сборки, инструкций и файлов, счётчики, анти-утечка
<out>/qwen_slab_localization_v1/train.jsonl      изображение + инструкция + ответ
<out>/qwen_slab_localization_v1/val.jsonl        изображение + инструкция
<out>/qwen_slab_localization_v1/test.jsonl       изображение + инструкция
<out>/qwen_slab_localization_v1/labels-val.jsonl метки для метрик
<out>/qwen_slab_localization_v1/labels-test.jsonl
<out>/qwen_masonry_roi_v1/…                      то же для кладки
```

Строка — сообщения в формате чата `transformers`/TRL: `user` = `[{"type":"image"}, {"type":"text"}]`,
`assistant` = текст ответа; путь `image` относительно корня сборки, `image_sha256` из `tiles.jsonl`.

### `qwen_slab_localization_v1`

```json
{
  "schema": "qwen_slab_localization_v1",
  "objects": [
    {
      "class": "slab",
      "bbox": [188, 188, 812, 812],
      "positive_points": [
        [281, 281],
        [719, 719]
      ],
      "negative_points": [[469, 469]]
    }
  ]
}
```

- Координаты — целые 0..1000 относительно тайла, поданного модели (1 024 px, заливка за краем листа
  внутри тайла). Физических единиц нет.
- Объект — связная область маски `targets/slab` (плита с вычтенными отверстиями) на сетке с шагом
  4 px: рамка по клеткам области; `positive_points` — до двух самых глубоких и разнесённых клеток
  области; `negative_points` — до двух клеток внутри рамки, не ближе 2 клеток к плите (отверстия,
  проёмы между плитами, фон). Соприкасающиеся плиты — один объект: SAM в промте 14 получает ту же
  связную область.
- Области меньше 1 024 px тайла — обрывки на краю тайла: отбрасываются и **считаются**
  (`dropped_small_components`).
- Объектов больше 16 — строка train исключается, метка val/test помечается
  `"unsupported": "too_many_objects"`. Молчаливого обрезания нет.
- Ответ сериализуется компактно, ключи в порядке контракта; каждая цель проходит собственный строгий
  парсер (тест).

### `qwen_masonry_roi_v1`

`{"schema":"qwen_masonry_roi_v1","contains_masonry":true,"roi":[x0,y0,x1,y1],"guide_points":[[x,y]]}`
или `contains_masonry:false, roi:null, guide_points:[]`. ROI — клетки 4×4 px, где цель осевой
`targets/masonry` не ниже 128 (максимум по клетке — тонкая линия не теряется); до 4 разнесённых
направляющих точек на линиях. Это помощник локализации, а не осевые токенами (промт 15).

`qwen_masonry_roi_v1` отличается от вида `qwen_masonry_roi_v0` промта 08 полем `schema`: строгий
парсер отличает ответ на один контракт от ответа на другой. Виды промта 08 не меняются.

### `qwen_slab_polygon_v0`

Не строится: решение владельца Р-1 (промт 08) — при тайле 1 024 px ни один тайл не содержит плиту
целиком, окна по разметке в val/test — утечка. Причина пишется в `sft.json → unsupported_views`.

### Анти-утечка

| Правило                                | Как обеспечено                                                                                        |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| разметка порождает только ответы train | ответ пишется только в `train.jsonl`; `anti_leakage.evaluation_rows_have_no_answer`                   |
| вход val/test не зависит от разметки   | строка val/test = изображение тайла + общая инструкция; тест проверяет точный набор полей и сообщение |
| кадры val/test выбраны не разметкой    | любой тайл val/test не из сетки (`crop_policy ≠ grid`) — отказ всей сборки SFT                        |
| разбиение не меняется                  | части берутся из `tiles.jsonl` как есть; перед сборкой `verify_build` сверяет хеши split/tiles/views  |
| метки оценки не попадают в обучение    | метки val/test — отдельные файлы `labels-*.jsonl`; загрузчик обучения промта 13 их не открывает       |
| повторная сборка не перетирает прежнюю | непустой `--out` — отказ; каталог внутри git-репозитория — BLOCKED                                    |

## 4. Строгий парсер

`vision/quantor_vision/qwen/schema.py`: `parse_slab`, `parse_masonry`. Ответ разбирается или отвергается с
кодом; ремонта нет.

| Код                        | Когда                                                            |
| -------------------------- | ---------------------------------------------------------------- |
| `empty`                    | пустой ответ                                                     |
| `prose_or_fence`           | текст до `{` или после `}`, ограждение ```                       |
| `not_json`                 | не разбирается, `NaN`/`Infinity`                                 |
| `duplicate_key`            | ключ повторён на любом уровне                                    |
| `not_object`               | корень — не объект                                               |
| `schema_mismatch`          | другой `schema` или `class ≠ slab`                               |
| `missing_key`, `extra_key` | набор ключей не совпадает с контрактом                           |
| `wrong_type`               | дробь, `true` вместо числа, рамка не из 4 чисел, точка не из 2   |
| `coordinate_out_of_range`  | координата вне 0..1000                                           |
| `bbox_order`, `bbox_area`  | `x0 > x1` или `y0 > y1`; рамка нулевой ширины или высоты         |
| `too_many_objects`         | объектов больше 16                                               |
| `too_many_points`          | больше 3 положительных, 3 отрицательных или 8 направляющих точек |
| `point_outside_box`        | положительная точка вне своей рамки, направляющая — вне ROI      |
| `inconsistent_roi`         | `contains_masonry:false` с ROI или точками; `true` без ROI       |

Пробелы и перевод строки вокруг JSON допускаются. `failure_counts` сводит коды в метрику
`parse_rate` + отказы по кодам — она входит в отчёты промтов 13–14.

Лимиты парсера (3 точки) шире лимитов цели (2 точки): модель, выучившая цель, не упирается в границу,
а явный выход за неё — ошибка.

## 5. Команды

```text
vision qwen-env probe                                         версии, GPU, sm_120, BF16, телеметрия
vision qwen-env fetch --model 2b|4b|8b [--models DIR]         закреплённая ревизия + сверка SHA-256
vision qwen-env smoke --model --backend transformers|unsloth  загрузка без сети и один ответ на
                      --quantization bf16|4bit                синтетическом «чертеже»
vision qwen-build-sft --build DIR --out DIR                   SFT-наборы
```

По умолчанию веса — `$QUANTOR_DATASET_ROOT\models\<id>@<rev12>`, записи дымовых прогонов —
`$QUANTOR_DATASET_ROOT\runs\qwen-env\`. Отказ стека в дымовом прогоне пишется с версиями и
трассировкой и возвращает код 3 (BLOCKED) — обходов наугад нет. Ответ модели до обучения разбирается
строгим парсером; результат — наблюдение, а не условие прохождения.

## 6. Шаги для владельца (RTX 5050)

Все команды — PowerShell из корня репозитория после `git pull`. `$env:QUANTOR_DATASET_ROOT` = `D:\QuantorData`.
Места на `D:` нужно ≈ 25 ГБ: окружение ≈ 8 ГБ, веса 2B 4,3 ГБ и 4B 8,9 ГБ.

**1. Окружение и сверка Unsloth.**

```powershell
cd vision
py -3.12 -m venv .venv-unsloth
.\.venv-unsloth\Scripts\python -m pip install --upgrade pip
New-Item -ItemType Directory -Force "$env:QUANTOR_DATASET_ROOT\wheels" | Out-Null
.\.venv-unsloth\Scripts\python -m pip download unsloth==2026.9.4 unsloth-zoo==2026.9.3 --no-deps -d "$env:QUANTOR_DATASET_ROOT\wheels"
Get-FileHash "$env:QUANTOR_DATASET_ROOT\wheels\unsloth*.whl" -Algorithm SHA256 | Format-List Hash, Path
```

Ожидается `7892AC14…5264` для `unsloth-2026.9.4` и `D846A0CD…350C` для `unsloth_zoo-2026.9.3`. Не
совпало — остановиться и прислать вывод.

```powershell
.\.venv-unsloth\Scripts\python -m pip install -r requirements-qwen-unsloth.txt
.\.venv-unsloth\Scripts\python -m pip install -e . --no-deps
cmd /c ".venv-unsloth\Scripts\python -m pip freeze --exclude-editable > requirements-qwen-unsloth.lock.txt"
```

Если установка падает — прислать последние 40 строк вывода; версии не менять самостоятельно.

**2. Проверка GPU, BF16 и телеметрии.**

```powershell
.\.venv-unsloth\Scripts\python -m quantor_vision qwen-env probe
```

Ожидается `"status": "OK"`, `capability 12.0`, `bf16_supported: true`, `bf16_matmul_finite: true`,
`version_mismatches: {}`, `unsloth_statistics_opt_out: "found: …"`.

**3. Веса 2B и 4B** (8B не качать).

```powershell
.\.venv-unsloth\Scripts\python -m quantor_vision qwen-env fetch --model 2b
.\.venv-unsloth\Scripts\python -m quantor_vision qwen-env fetch --model 4b
```

Ожидается `"verified": true` у обеих.

**4. Дымовые прогоны** — по одному, в этом порядке:

| #   | Команда (`.\.venv-unsloth\Scripts\python -m quantor_vision qwen-env smoke …`) | Что проверяет                                 | Ожидание                    |
| --- | ----------------------------------------------------------------------------- | --------------------------------------------- | --------------------------- |
| 1   | `--model 2b --backend transformers --quantization bf16`                       | BF16-линия без Unsloth — так грузится адаптер | `OK`                        |
| 2   | `--model 2b --backend unsloth --quantization bf16`                            | Unsloth + Qwen3-VL                            | `OK`                        |
| 3   | `--model 4b --backend unsloth --quantization 4bit`                            | основной путь промта 13                       | `OK`                        |
| 4   | `--model 4b --backend transformers --quantization 4bit`                       | 4B без Unsloth                                | `OK`                        |
| 5   | `--model 4b --backend transformers --quantization bf16`                       | помещается ли 4B в BF16                       | вероятно `BLOCKED` (память) |

**5. SFT-набор** (подойдёт и `.venv-train`):

```powershell
.\.venv-train\Scripts\python -m quantor_vision qwen-build-sft --build "$env:QUANTOR_DATASET_ROOT\planswift\build\planswift-build-v1" --out "$env:QUANTOR_DATASET_ROOT\sft\qwen-sft-v1"
```

Работает на стандартной библиотеке, минуты — не секунды. Каталог не должен существовать.

**6. Не открывать в чате и не присылать** тайлы, `train.jsonl`, `labels-*.jsonl` — это производные
клиентских данных. Синтетические PNG дымовых прогонов присылать можно.

**7. Проверка кода.**

```powershell
cd ..
pnpm test:vision
```

**Прислать текстом:**

1. вывод `Get-FileHash` из шага 1 и файл `vision\requirements-qwen-unsloth.lock.txt` (содержимое);
2. вывод `probe` целиком;
3. для каждого из пяти дымовых прогонов — JSON из `runs\qwen-env\…json`; у `BLOCKED` — вместе с `traceback`;
4. из `qwen-build-sft` — `counters` и `anti_leakage` (без путей и строк набора);
5. вывод `pnpm test:vision` — при ошибках полностью.

## 7. Ограничения

- Шаг сетки 4 px ограничивает точность рамки ±4 px тайла (≈ ±4 единицы из 1 000): это цель
  локализации для SAM, а не геометрия для площади.
- Слияние соприкасающихся плит в один объект — выбор под Qwen → SAM; при прямом сравнении с
  векторной разметкой по объектам промт 14 это учитывает.
- Метки val/test лежат рядом с входами на диске владельца: изоляция — отдельные файлы и загрузчик,
  а не права доступа.
- Совместимость Unsloth 2026.9.4 с Qwen3-VL на Windows и RTX 50 до шага 4 не подтверждена. Если стек
  не запускается — фиксируется `BLOCKED` с версиями и трассировкой, и решение принимает владелец
  (запасной путь — `transformers + peft + trl`).
