# PROMPT 09 — Vision Lab scaffold + license gate

Создай ML-контур отдельно от production API.

## Separation

Не добавляй torch/SAM/OpenCV training dependencies в `apps/api` runtime.

Выбери структуру вроде:

```text
vision/
  pyproject.toml
  quantor_vision/
  configs/
  tests/
  cli/
```

или эквивалент с чётким объяснением. Training и inference extras можно разделить.

## Experiment contract

Каждый run сохраняет:

- task;
- dataset fingerprint + split hash;
- model architecture;
- weight initialization/provenance;
- seed;
- preprocessing/augmentation;
- training params;
- software versions;
- git/source state where available;
- output weights SHA-256;
- metrics JSON.

## License gate

Создай `docs/stage2b/model-license-matrix.md`.

На этом этапе разрешены только зависимости/weights с documented permissive path.

- SAM2 / MobileSAM допустимы после фиксации Apache notices.
- Official `Qwen/Qwen3-VL-2B-Instruct`, `4B-Instruct`, `8B-Instruct` допустимы только после фиксации конкретного model-card/license hash; на дату пакета official model cards указывают Apache-2.0.
- Unsloth core training package допустим как отдельный training dependency после license audit; **Unsloth Studio UI не встраивать** в Quantor, потому что Studio-компоненты имеют другой license boundary (AGPL).
- OpenCV допустим после notice.
- pypdfium2 допустим как renderer candidate после bundled license audit.
- Ultralytics **BLOCKED** до explicit owner enterprise-license approval.
- pretrained encoder weights — отдельная строка license/provenance, не наследовать лицензию
  Python package автоматически.

Добавь CI/static check, который не даст случайно добавить `ultralytics` dependency без явного
license decision file/allowlist.

## Commands

Определи единые CLI entrypoints:

```text
vision dataset ...
vision train ...
vision qwen-build-sft ...
vision qwen-train ...
vision qwen-evaluate ...
vision evaluate ...
vision infer ...
vision vectorize ...
```

Не обучай модель в этом промте.

STOP.
