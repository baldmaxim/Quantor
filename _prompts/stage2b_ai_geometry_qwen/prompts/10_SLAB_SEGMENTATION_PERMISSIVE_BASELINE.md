# PROMPT 10 — Small slab segmentation baseline

Цель — минимальный честный обучаемый baseline без SAM и без proprietary-license риска.

## Model

Начни с маленькой semantic segmentation сети на permissive stack:

- custom Tiny U-Net / compact torchvision-based alternative;
- параметров достаточно мало, чтобы inference был дешёвым;
- не оптимизировать architecture search.

Если хочешь использовать `segmentation_models.pytorch`, сначала завершить license audit всех
конкретных encoder/weights. Нельзя просто считать pretrained weight MIT.

## Task v0

Один binary task: slab/foundation foreground vs background с сохранением holes.
Не добавляй шесть классов монолита сразу.

## Training

- train/val only для подбора thresholds/hyperparams;
- fixed split from Prompt 08;
- deterministic seed where practical;
- mixed precision optional;
- checkpoint by validation metric;
- early stopping;
- class imbalance handled explicitly;
- augmentations не должны ломать engineering topology без отражения transform.

## Evaluation

На frozen test:

- IoU/Dice;
- Boundary F1;
- raw mask area error in normalized pixel space;
- inference latency/memory;
- save predictions by hash.

Пока не делай mask→Measurement — это Prompt 16+.

Сформируй `docs/stage2b/10-slab-small-baseline.md` с реальными числами. Если GPU недоступен,
не выдумывать — подготовить pipeline и пометить training BLOCKED.

STOP.
