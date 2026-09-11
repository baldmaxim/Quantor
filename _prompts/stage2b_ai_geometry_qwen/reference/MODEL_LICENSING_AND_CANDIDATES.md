# Model candidates и licensing gate

Quantor — потенциально proprietary/commercial product. Лицензия является техническим gate,
а не бумажкой «на потом».

## Разрешённые для первичного эксперимента кандидаты

### Custom Tiny U-Net / small semantic baseline

Реализовать на PyTorch/Torchvision или другом разрешённом стеке с отдельной проверкой
license weights. Цель — маленький воспроизводимый baseline, не SOTA любой ценой.

### SAM 2

Официальный код/checkpoints/training code Meta SAM 2 опубликован под Apache-2.0. Использовать
как promptable/refinement baseline после фиксации THIRD_PARTY_NOTICES.

### MobileSAM

Официальный проект заявляет Apache-2.0. Использовать прежде всего как лёгкий promptable
refiner/inference baseline; не предполагать, что он сам решит semantic classification.

### OpenCV

Apache-2.0. Подходит для masks, contours, morphology и части vectorization.

### pypdfium2 / PDFium

pypdfium2: Apache-2.0 OR BSD-3-Clause; PDFium — BSD-style плюс third-party notices. Кандидат
для server-side raster tiles. Перед production image сохранить список bundled licenses.


### Qwen3-VL official dense models

Для VLM experiment основной кандидат — official `Qwen/Qwen3-VL-4B-Instruct`; 2B — efficiency lower bound, 8B — optional upper bound. На дату проверки 2026-09-11 official Hugging Face model cards 2B/4B показывают Apache-2.0; перед фактическим download зафиксировать exact revision/license и повторно проверить 8B.

Qwen не получает право считать физические quantities; outputs = structured localization/geometry only.

### Unsloth

Использовать core Unsloth только в isolated training environment. Репозиторий Unsloth на дату проверки описывает dual-license boundary: core package Apache-2.0, отдельные Studio/UI components AGPL-3.0. Поэтому **не vendor/use Unsloth Studio UI inside Quantor**; зафиксировать exact package files/versions в license matrix. Production inference не должен требовать Unsloth, если promoted checkpoint можно безопасно загрузить стандартным runtime.

## Условно разрешённые после отдельного dependency audit

- `segmentation_models.pytorch`: core MIT, но pretrained encoders/weights могут иметь свои
  условия. Нельзя автоматически считать все веса MIT.
- Shapely: BSD-3, GEOS LGPL-2.1; прежде чем включать в production image, оформить dependency
  ADR/notice и проверить способ распространения.

## Ultralytics YOLO — НЕ добавлять по умолчанию

На момент подготовки пакета Ultralytics указывает, что YOLO code/models/training под
AGPL-3.0 по умолчанию, а proprietary/commercial/private use требует Enterprise license.
Поэтому:

- не добавлять `ultralytics` в Quantor dependencies;
- не коммитить trained YOLO weights;
- можно описать adapter/experiment slot;
- реальный эксперимент в Quantor — только после явного подтверждения владельца о лицензии.

## Sources checked 2026-09-11

- https://www.ultralytics.com/license
- https://github.com/facebookresearch/sam2/blob/main/LICENSE
- https://github.com/ChaoningZhang/MobileSAM
- https://github.com/opencv/opencv
- https://pypdfium2.readthedocs.io/
- https://github.com/qubvel-org/segmentation_models.pytorch
- https://github.com/shapely/shapely

Этот документ не является юридическим заключением. Любая новая dependency/model weight
должна попасть в license matrix с URL, SPDX, weight provenance и решением allow/block.


## Additional sources checked 2026-09-11

- https://github.com/QwenLM/Qwen3-VL
- https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct
- https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct
- https://github.com/unslothai/unsloth
- https://github.com/unslothai/notebooks
- https://github.com/unslothai/unsloth/blob/main/studio/backend/assets/configs/model_defaults/qwen/unsloth_Qwen3-VL-8B-Instruct-unsloth-bnb-4bit.yaml

Unsloth ecosystem evolves quickly; exact versions and license boundaries must be frozen in experiment metadata, not inferred from this document forever.
