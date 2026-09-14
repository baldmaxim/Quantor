# Инструкция: Stage 2B на локальной машине с RTX 5050

Для владельца. Всё выполняется на своей машине с GPU; частные данные и результаты остаются на ней,
в репозиторий и во внешние сервисы не уходят. Решения, на которых стоит инструкция, —
[журнал](owner-decisions.md) (Р-1…Р-4).

Порядок работы: код каждого промта пишется и проверяется в репозитории на синтетике без GPU →
вы делаете `git pull` и запускаете команду на GPU → присылаете в чат **только текст**: `run.json`,
`metrics.json`, хвост лога. Изображения, тайлы, предсказания и веса не присылаются.

## 0. Что уже известно о машине

RTX 5050 — архитектура Blackwell (compute capability 12.0), 8 ГБ видеопамяти. Отсюда:

- нужны сборки PyTorch под **CUDA 12.8** или новее; более старые (cu121/cu124) на этой карте не
  работают;
- **Qwen3-VL-4B в BF16 не помещается** (одни веса ≈ 9 ГБ): 4B — только 4-битным (QLoRA через Unsloth);
- BF16-замер без дообучения выполним для **2B**; для 4B он BLOCKED по памяти и так записывается;
- малая сегментация (промт 10) и SAM 2 small (промт 11) в 8 ГБ помещаются.

## 1. Проверка драйвера

```powershell
nvidia-smi
```

Ожидается строка с `NVIDIA GeForce RTX 5050` и `8188MiB` (или близко). Драйвер для RTX 50 — ветка
R570 или новее. CUDA Toolkit ставить не нужно: колёса PyTorch несут свою CUDA.

Пришлите вывод `nvidia-smi` (первые ~12 строк) — он пойдёт в запись окружения.

## 2. Репозиторий

```powershell
cd <каталог с репозиторием Quantor>
git pull
```

Архивы PlanSwift в корне репозитория закрыты `.gitignore`, но держать их лучше вне репозитория.

## 3. Корень частных данных

Выберите каталог **вне** репозитория, например `D:\QuantorData`, и задайте переменную:

```powershell
setx QUANTOR_DATASET_ROOT "D:\QuantorData"
# открыть новое окно PowerShell, чтобы переменная подхватилась
```

Дальше данные можно получить двумя путями.

### 3а. Перенести готовое с VM разработки (быстрее)

Скопировать `C:\Users\Usrr\QuantorData\planswift\` целиком (≈ 190 МБ: `raw` 132, `build` 37, `qa` 12,
`gt` 7) в `D:\QuantorData\planswift\`. Затем поправить пути в `D:\QuantorData\planswift\build-v1.json`
(`dataset_dir`, `source_root`) под новое место.

### 3б. Собрать заново из архивов (проверяет воспроизводимость)

Проверить архивы:

```powershell
Get-FileHash "ЖК Stories Кладка.7z","Мосфильмовская 31А Planswift.7z" -Algorithm SHA256
```

| Архив                             | SHA-256                                                            |
| --------------------------------- | ------------------------------------------------------------------ |
| `ЖК Stories Кладка.7z`            | `6b47984b9518d5ab64e4d7361c2eafcfe645a65707ca67539ef2447ca9c04d09` |
| `Мосфильмовская 31А Planswift.7z` | `72e9e27dddad74f2a8032c46739dcf3c3b156b80d774bc39306c97f0fe69b9c7` |

Распаковать так же, как на VM разработки (проект — на один уровень ниже `raw\<ключ>`), и
импортировать стандартной библиотекой (venv бэкенда после `pnpm run setup`):

```powershell
$R = "$env:QUANTOR_DATASET_ROOT\planswift"
7z x "ЖК Stories Кладка.7z" -o"$R\raw\stories"
7z x "Мосфильмовская 31А Planswift.7z" -o"$R\raw\mosfilm"
pnpm planswift convert "$R\raw\stories" --project-key stories_masonry --out "$R\gt\stories_masonry"
pnpm planswift convert "$R\raw\mosfilm" --project-key mosfilm31a --out "$R\gt\mosfilm31a"
pnpm planswift validate "$R\gt\mosfilm31a" --source "$R\raw\mosfilm\Мосфильмовская 31А" --reparse "$R\raw\mosfilm"
```

Корни проектов для `qa`, `validate --source` и `source_root` в конфиге сборки —
`$R\raw\stories\ЖК Stories Кладка` и `$R\raw\mosfilm\Мосфильмовская 31А`.

Отпечатки обязаны совпасть (смотреть в `manifest.json`):

| Датасет           | `dataset_fingerprint`                                              |
| ----------------- | ------------------------------------------------------------------ |
| `stories_masonry` | `fec491dba58e072c0bc810aa5e4b407527fc50c424add00601aeab9ca98612b0` |
| `mosfilm31a`      | `beff4772d016adb40f41c9d4c75c5aa0f071b1b61762337ee41ef13f1b3b4333` |

Конфиг сборки — копия `tools/planswift_gt/configs/dataset-build.example.json` в
`$R\build-v1.json` с двумя правками: реальные пути и метки плиты (Р-3):

```json
"slab": {
  "kinds": ["polygon"],
  "labels": [
    "Плита Перекрытия [Толщина ПП]м [Класс бетона ПП]",
    "Фундаментная Плита [Толщина ФП]м [Класс бетона ФП]"
  ],
  "min_positive_fraction": 0.001
}
```

```powershell
pnpm planswift build "$R\build-v1.json" --out "$R\build\planswift-build-v1"
```

Разбиение обязано совпасть: `split_sha256 = ecb3498034b30def2464a46e2a2558898e819e61793b4b8fa1675d355b79fe2a`,
`tiles_sha256 = edf76c67ffa7b8e1b7bbc9a9d942e1326d9fb57364e0248515998cdf729d2ced`. Не совпало — не
обучать, прислать `build.json`.

## 4. Ручной просмотр оверлеев (промт 07)

```powershell
pnpm planswift qa "$R\gt\mosfilm31a" --source "$R\raw\mosfilm\Мосфильмовская 31А" --out "$R\qa\mosfilm31a"
pnpm planswift qa "$R\gt\stories_masonry" --source "$R\raw\stories\ЖК Stories Кладка" --out "$R\qa\stories_masonry"
```

(при пути 3а оверлеи уже лежат в `$R\qa\`). Открыть PNG и заполнить таблицу
[07, § 5](07-ground-truth-validation.md): первым — `mosfilm31a\page-006.png`. Прислать таблицу
PASS/FAIL текстом.

## 5. Окружения обучения

Два отдельных окружения внутри `vision\` (закрыты `.gitignore`), не venv бэкенда.

### 5а. Малая сегментация и SAM — Apache/BSD-стек

```powershell
cd vision
py -3.12 -m venv .venv-train
.\.venv-train\Scripts\python -m pip install --upgrade pip
.\.venv-train\Scripts\python -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv-train\Scripts\python -m pip install -e .
.\.venv-train\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"
```

Ожидается `2.11.0+cu128 True NVIDIA GeForce RTX 5050 (12, 0)`.

### 5б. Qwen на Unsloth (Р-2)

У вас Unsloth уже работает — окружение пересоздавать не нужно, достаточно проверить совместимость
с условиями и зафиксировать версии:

```powershell
New-Item -ItemType Directory -Force "$env:QUANTOR_DATASET_ROOT\envs" | Out-Null
<ваш python окружения Unsloth> -m pip show unsloth unsloth-zoo torch transformers trl peft bitsandbytes
<ваш python окружения Unsloth> -m pip freeze > "$env:QUANTOR_DATASET_ROOT\envs\unsloth-freeze.txt"
```

Совместимые ориентиры для RTX 50 на дату проверки: `torch 2.11.0+cu128`, `torchvision 0.26.0+cu128`
(связка extra `unsloth[cu128onlytorch2110]`), `transformers ≤ 5.5.0` (и не 4.57.0), `trl ≤ 0.24.0`,
`peft ≥ 0.18`. Если окружения нет или оно старое — создать рядом `vision\.venv-unsloth`:

```powershell
py -3.12 -m venv .venv-unsloth
.\.venv-unsloth\Scripts\python -m pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv-unsloth\Scripts\python -m pip install unsloth unsloth-zoo
.\.venv-unsloth\Scripts\python -m pip install -e .
```

Условия Р-2 на этой машине: Unsloth Studio не запускать; окружение и архивы с ним никому не
передавать; адаптер сохранять стандартным PEFT/safetensors.

Прислать вывод `pip show` из 5б.

## 6. Проверка готовности

```powershell
cd vision
.\.venv-train\Scripts\python -m quantor_vision environment
.\.venv-train\Scripts\python -m quantor_vision dataset verify "$env:QUANTOR_DATASET_ROOT\planswift\build\planswift-build-v1"
```

Ожидается: в `gpus` — RTX 5050, в `missing_modules` нет `torch`/`torchvision`, `dataset verify` —
`"ok": true`. Прислать оба вывода.

## 7. Что дальше

Команды обучения появятся по промтам:

| Промт | Команда (будет)           | Окружение       | Что пришлёте                           |
| ----- | ------------------------- | --------------- | -------------------------------------- |
| 10    | `vision train slab …`     | `.venv-train`   | `run.json`, `metrics.json`, хвост лога |
| 11    | `vision evaluate sam …`   | `.venv-train`   | то же                                  |
| 12    | `vision qwen-build-sft …` | любое           | счётчики набора                        |
| 13    | `vision qwen-train …`     | Unsloth         | `run.json`, `metrics.json`             |
| 14    | `vision qwen-evaluate …`  | Unsloth / train | `metrics.json`                         |

Каждая команда пишет результаты в `$env:QUANTOR_DATASET_ROOT\runs\<run_id>\` — вне репозитория.

## Чего не делать

- не копировать тайлы, оверлеи, датасеты и веса в репозиторий или в чат;
- не менять `split.json` и не пересобирать с `--refreeze` после начала обучения;
- не запускать Unsloth Studio;
- не ставить torch в venv бэкенда `apps/api`.

## Состояние машины владельца — 2026-09-14

| Раздел            | Результат                                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------------------- |
| 1. Драйвер        | 591.44, CUDA 13.1; RTX 5050, 8 151 МиБ                                                                         |
| 2–3. Данные       | `D:\QuantorData`, путь 3б; SHA-256 архивов, оба `dataset_fingerprint`, `split_sha256` и `tiles_sha256` совпали |
| 4. Оверлеи        | сгенерированы в `D:\QuantorData\planswift\qa\`; **просмотр и таблица PASS/FAIL — за владельцем**               |
| 5а. `.venv-train` | `torch 2.11.0+cu128`, CUDA доступна, compute capability (12, 0); `quantor-vision` editable                     |
| 5б. Unsloth       | готового окружения нет; найдена установка Studio в `%USERPROFILE%\.unsloth\studio` — по Р-2 не запускается     |
| 6. Готовность     | `environment`: GPU виден, torch есть; `dataset verify`: `ok: true`                                             |

Для editable-установки в `vision/pyproject.toml` добавлены `build-system` и явный
`tool.setuptools.packages.find` — без них setuptools отказывался из-за каталогов `licenses/` и
`tests/` рядом с пакетом.

Промт 10 готов к запуску на этой машине. `vision\.venv-unsloth` по § 5б создаётся перед промтом 13;
Studio-установка на обучение не влияет и не используется.
