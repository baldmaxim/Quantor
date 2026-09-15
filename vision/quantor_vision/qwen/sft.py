"""SFT-наборы Qwen3-VL из замороженной сборки промта 08.

```text
<out>/sft.json                              манифест: хеши сборки, инструкций, файлов, счётчики
<out>/<вид>/train.jsonl                     изображение + инструкция + ответ-цель
<out>/<вид>/val.jsonl, test.jsonl           изображение + инструкция, без ответа
<out>/<вид>/labels-val.jsonl, labels-test   метки только для метрик (промты 13–14)
```

Анти-утечка:

- разметка PlanSwift порождает только **ответ** train-строк; val/test-строка собирается из
  изображения тайла и одной и той же инструкции и не зависит от разметки ни одним байтом;
- val/test принимаются только из тайлов сетки (`crop_policy = grid`), иначе отказ всей сборки;
- метки val/test лежат отдельными файлами: загрузчик обучения их не открывает;
- если цель не укладывается в контракт (объектов больше лимита), строка train исключается, а метка
  val/test помечается `unsupported` — ничего не обрезается молча.

`qwen_slab_polygon_v0` не строится: решение владельца Р-1 (промт 08), причина пишется в манифест.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from quantor_vision.png import read_gray
from quantor_vision.qwen.schema import (
    MASONRY_SCHEMA,
    SLAB_SCHEMA,
    Limits,
    serialize_masonry,
    serialize_slab,
)
from quantor_vision.qwen.targets import TargetConfig, TileGeometry, masonry_target, slab_target

SFT_FORMAT = "quantor-qwen-sft-v1"
SPLITS = ("train", "val", "test")
EVALUATION_SPLITS = ("val", "test")

INSTRUCTIONS = {
    SLAB_SCHEMA: (
        "Найди на фрагменте строительного чертежа монолитные плиты перекрытия. Ответь только JSON"
        ' без пояснений: {"schema":"qwen_slab_localization_v1","objects":[{"class":"slab",'
        '"bbox":[x0,y0,x1,y1],"positive_points":[[x,y]],"negative_points":[[x,y]]}]}.'
        " Координаты — целые 0..1000 относительно этого изображения. positive_points — внутри"
        " плиты, negative_points — отверстия и не плита внутри рамки. Плит нет —"
        ' "objects":[].'
    ),
    MASONRY_SCHEMA: (
        "Есть ли на фрагменте строительного чертежа стены из кладки? Ответь только JSON без"
        ' пояснений: {"schema":"qwen_masonry_roi_v1","contains_masonry":true,'
        '"roi":[x0,y0,x1,y1],"guide_points":[[x,y]]}. Координаты — целые 0..1000 относительно'
        ' этого изображения. Кладки нет — {"schema":"qwen_masonry_roi_v1",'
        '"contains_masonry":false,"roi":null,"guide_points":[]}.'
    ),
}
TASK_OF_VIEW = {SLAB_SCHEMA: "slab", MASONRY_SCHEMA: "masonry"}

UNSUPPORTED_VIEWS = {
    "qwen_slab_polygon_v0": (
        "решение владельца Р-1 (2026-09-14): прямой полигон от Qwen не строится — при тайле"
        " 1 024 px ни один тайл не содержал плиты целиком, окна по разметке в val/test — утечка"
    ),
}


class SftRefusedError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SftConfig:
    targets: TargetConfig = field(default_factory=TargetConfig)
    limits: Limits = field(default_factory=Limits)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _user_message(instruction: str) -> dict[str, object]:
    return {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": instruction}]}


def _target_text(
    view: str, pixels: bytes, geometry: TileGeometry, config: SftConfig
) -> tuple[str | None, str, int]:
    """Ответ-цель, причина неподдержки (или пусто) и число отброшенных обрывков."""
    if view == SLAB_SCHEMA:
        target = slab_target(pixels, geometry, config.targets)
        if len(target.objects) > config.limits.max_objects:
            return None, "too_many_objects", target.dropped_small
        return serialize_slab(target.objects), "", target.dropped_small
    roi = masonry_target(pixels, geometry, config.targets)
    return serialize_masonry(roi), "", 0


def build_sft(build_dir: Path, out: Path, config: SftConfig | None = None) -> dict[str, object]:
    config = config or SftConfig()
    if out.exists() and any(out.iterdir()):
        raise SftRefusedError(f"{out} не пуст: SFT-набор не перезаписывается")
    manifest = json.loads((build_dir / "build.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (build_dir / "tiles.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows.sort(key=lambda row: str(row["tile_id"]))

    leaking = sorted(
        str(row["tile_id"])
        for row in rows
        if row["split"] in EVALUATION_SPLITS and row["crop_policy"] != "grid"
    )
    if leaking:
        raise SftRefusedError(
            f"тайлы val/test не из сетки ({len(leaking)}, первый {leaking[0]}):"
            " кадр выбран разметкой"
        )

    files: dict[str, dict[str, list[str]]] = {
        view: {name: [] for name in (*SPLITS, "labels-val", "labels-test")} for view in INSTRUCTIONS
    }
    counters: Counter[str] = Counter()
    for row in rows:
        split = str(row["split"])
        if split not in SPLITS:
            raise SftRefusedError(f"тайл {row['tile_id']}: неизвестная часть {split!r}")
        transform = row["transform"]
        geometry = TileGeometry(
            tile_px=int(transform["tile_px"]),
            valid_width=int(transform["valid_size"][0]),
            valid_height=int(transform["valid_size"][1]),
        )
        image_path = build_dir / str(row["image"])
        image_sha = str(row.get("image_sha256") or _sha256_bytes(image_path.read_bytes()))
        for view, task in TASK_OF_VIEW.items():
            if task not in row["tasks"]:
                continue
            target_path = build_dir / "targets" / task / f"{row['tile_id']}.png"
            width, height, pixels = read_gray(target_path)
            if (width, height) != (geometry.tile_px, geometry.tile_px):
                raise SftRefusedError(f"{target_path.name} ({task}): размер {width}×{height}")
            text, unsupported, dropped = _target_text(view, pixels, geometry, config)
            counters[f"{view}.{split}.tiles"] += 1
            counters[f"{view}.{split}.dropped_small_components"] += dropped
            base: dict[str, object] = {
                "id": row["tile_id"],
                "image": row["image"],
                "image_sha256": image_sha,
                "page_guid": row["page_guid"],
                "crop_policy": row["crop_policy"],
            }
            if unsupported:
                counters[f"{view}.{split}.unsupported.{unsupported}"] += 1
            if split == "train":
                if text is None:
                    continue
                base["messages"] = [
                    _user_message(INSTRUCTIONS[view]),
                    {"role": "assistant", "content": [{"type": "text", "text": text}]},
                ]
                files[view]["train"].append(_dump(base))
                continue
            # val/test: вход не зависит от разметки — изображение и общая инструкция.
            base["messages"] = [_user_message(INSTRUCTIONS[view])]
            files[view][split].append(_dump(base))
            label: dict[str, object] = {"id": row["tile_id"], "target": text}
            if unsupported:
                label["unsupported"] = unsupported
            files[view][f"labels-{split}"].append(_dump(label))

    out.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for view, parts in files.items():
        (out / view).mkdir(exist_ok=True)
        for name, lines in parts.items():
            payload = "".join(line + "\n" for line in lines).encode("utf-8")
            (out / view / f"{name}.jsonl").write_bytes(payload)
            hashes[f"{view}/{name}.jsonl"] = _sha256_bytes(payload)
            counters[f"{view}.{name}.rows"] = len(lines)

    result: dict[str, object] = {
        "format": SFT_FORMAT,
        "build": {
            "root": str(build_dir),
            "split_sha256": manifest.get("split_sha256"),
            "tiles_sha256": manifest.get("tiles_sha256"),
        },
        "instructions_sha256": {
            view: _sha256_bytes(text.encode("utf-8")) for view, text in INSTRUCTIONS.items()
        },
        "config": asdict(config),
        "files_sha256": hashes,
        "counters": dict(sorted(counters.items())),
        "unsupported_views": UNSUPPORTED_VIEWS,
        "anti_leakage": {
            "labels_generate_train_answers_only": True,
            "evaluation_tiles_grid_only": True,
            "evaluation_rows_have_no_answer": all(
                "assistant" not in line for view in files.values() for line in view["val"]
            )
            and all("assistant" not in line for view in files.values() for line in view["test"]),
        },
    }
    (out / "sft.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return result
