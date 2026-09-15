"""Окружение Qwen3-VL: проверка GPU и BF16, скачивание закреплённых весов, дымовой прогон.

Окружение — отдельный `vision/.venv-unsloth` из `requirements-qwen-unsloth.txt`, только на
GPU-машине владельца (условия Unsloth — матрица лицензий). В CI оно не ставится, поэтому
transformers, Unsloth, huggingface_hub и Pillow загружаются через `importlib` в момент вызова:
модуль импортируется и проверяется без них.

Телеметрия выключается до первого импорта тяжёлых пакетов, дымовой прогон идёт с
`HF_HUB_OFFLINE=1` — веса уже скачаны и сверены, сеть ему не нужна. Вход дымового прогона —
синтетическое изображение, клиентских данных здесь нет.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import time
import traceback
from collections.abc import MutableMapping
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from types import ModuleType

from quantor_vision.qwen.models import EXPECTED_PACKAGES, MODELS, PinnedModel, local_dir_name
from quantor_vision.qwen.schema import SLAB_SCHEMA, ResponseError, parse_slab
from quantor_vision.qwen.sft import INSTRUCTIONS

TELEMETRY_OFF = {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
    "WANDB_MODE": "disabled",
    "WANDB_DISABLED": "true",
    "DISABLE_MLFLOW_INTEGRATION": "TRUE",
    # Unsloth при загрузке модели шлёт статистику на Hugging Face, если переменная не задана;
    # что проверка переменной есть в установленном пакете, подтверждает `qwen-env probe`.
    "UNSLOTH_DISABLE_STATISTICS": "1",
}
UNSLOTH_STATISTICS_FLAG = "UNSLOTH_DISABLE_STATISTICS"
BACKENDS = ("transformers", "unsloth")
QUANTIZATIONS = ("bf16", "4bit")


def disable_telemetry(environ: MutableMapping[str, str], *, offline: bool = False) -> None:
    environ.update(TELEMETRY_OFF)
    if offline:
        environ["HF_HUB_OFFLINE"] = "1"
        environ["TRANSFORMERS_OFFLINE"] = "1"


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in (*EXPECTED_PACKAGES, "triton-windows", "triton", "huggingface-hub", "pillow"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def version_mismatches(versions: dict[str, str]) -> dict[str, str]:
    return {
        name: f"{versions.get(name)} ≠ {expected}"
        for name, expected in EXPECTED_PACKAGES.items()
        if versions.get(name) != expected
    }


def record_sha256(distribution: str) -> str:
    """SHA-256 файла RECORD установленного пакета: отпечаток того, что именно установлено."""
    try:
        text = metadata.distribution(distribution).read_text("RECORD")
    except metadata.PackageNotFoundError:
        return "not-installed"
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "no-record"


def unsloth_statistics_opt_out() -> str:
    """Есть ли в установленном Unsloth проверка переменной, выключающей статистику."""
    spec = importlib.util.find_spec("unsloth")
    if spec is None or not spec.submodule_search_locations:
        return "unsloth-not-installed"
    root = Path(next(iter(spec.submodule_search_locations)))
    for path in sorted(root.rglob("*.py")):
        if UNSLOTH_STATISTICS_FLAG in path.read_text(encoding="utf-8", errors="replace"):
            return f"found: {path.relative_to(root).as_posix()}"
    return "not-found"


def probe() -> dict[str, object]:
    disable_telemetry(os.environ)
    versions = package_versions()
    reasons: list[str] = []
    report: dict[str, object] = {
        "packages": versions,
        "version_mismatches": version_mismatches(versions),
        "unsloth_record_sha256": {name: record_sha256(name) for name in ("unsloth", "unsloth-zoo")},
        "unsloth_statistics_opt_out": unsloth_statistics_opt_out(),
        "telemetry_env": {name: os.environ.get(name, "") for name in TELEMETRY_OFF},
    }
    if report["version_mismatches"]:
        reasons.append("версии пакетов не совпадают с requirements-qwen-unsloth.txt")
    if importlib.util.find_spec("torch") is None:
        reasons.append("torch не установлен")
        report.update({"status": "BLOCKED", "reasons": reasons})
        return report

    import torch

    gpu: dict[str, object] = {"cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        major, minor = torch.cuda.get_device_capability(0)
        properties = torch.cuda.get_device_properties(0)
        gpu.update(
            {
                "name": torch.cuda.get_device_name(0),
                "capability": f"{major}.{minor}",
                "total_memory_gib": round(properties.total_memory / 1024**3, 2),
                "torch_cuda": str(torch.version.cuda),
                "cudnn": str(torch.backends.cudnn.version()),
                "arch_list": torch.cuda.get_arch_list(),
                "bf16_supported": torch.cuda.is_bf16_supported(),
            }
        )
        # Поддержка на словах и работающее ядро — разное: считаем произведение матриц в bf16.
        sample = torch.randn(512, 512, device="cuda", dtype=torch.bfloat16)
        product = sample @ sample.T
        torch.cuda.synchronize()
        gpu["bf16_matmul_finite"] = bool(torch.isfinite(product).all())
        if f"sm_{major}{minor}" not in torch.cuda.get_arch_list():
            reasons.append(f"сборка torch не содержит ядер для sm_{major}{minor}")
        if not gpu["bf16_matmul_finite"]:
            reasons.append("bf16 на GPU даёт нечисловые значения")
    else:
        reasons.append("CUDA недоступна")
    report["gpu"] = gpu
    if report["unsloth_statistics_opt_out"] == "not-found":
        reasons.append(f"в Unsloth нет проверки {UNSLOTH_STATISTICS_FLAG}: статистика не отключена")
    report.update({"status": "BLOCKED" if reasons else "OK", "reasons": reasons})
    return report


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_weights(local: Path, model: PinnedModel) -> list[str]:
    problems: list[str] = []
    for name, expected in model.weights_sha256.items():
        path = local / name
        if not path.is_file():
            problems.append(f"нет файла {name}")
        elif sha256_file(path) != expected:
            problems.append(f"SHA-256 {name} не совпадает с закреплённым")
    return problems


def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


def fetch(model_key: str, models_root: Path) -> dict[str, object]:
    """Скачивает закреплённую ревизию целиком в `<models>/<id>@<rev12>` и сверяет хеши весов."""
    disable_telemetry(os.environ)
    model = MODELS[model_key]
    local = models_root / local_dir_name(model)
    hub = _module("huggingface_hub")
    hub.snapshot_download(repo_id=model.repo_id, revision=model.revision, local_dir=str(local))
    problems = verify_weights(local, model)
    provenance: dict[str, object] = {
        "repo_id": model.repo_id,
        "revision": model.revision,
        "weights_sha256": model.weights_sha256,
        "verified": not problems,
        "problems": problems,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (local / "quantor-provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"local_dir": str(local), **provenance}


def synthetic_drawing(path: Path, size: int = 1024) -> str:
    """Синтетический «чертёж»: контур плиты с отверстием, штриховка, посторонние линии."""
    image_module = _module("PIL.Image")
    draw_module = _module("PIL.ImageDraw")
    image = image_module.new("L", (size, size), 255)
    draw = draw_module.Draw(image)
    unit = size / 1000
    draw.rectangle([150 * unit, 180 * unit, 850 * unit, 820 * unit], outline=0, width=4)
    draw.rectangle([430 * unit, 440 * unit, 570 * unit, 560 * unit], outline=0, width=4)
    for offset in range(180, 820, 40):
        draw.line([150 * unit, offset * unit, 190 * unit, (offset + 40) * unit], fill=90, width=1)
    draw.line([40 * unit, 930 * unit, 960 * unit, 930 * unit], fill=0, width=2)
    draw.line([920 * unit, 60 * unit, 920 * unit, 900 * unit], fill=0, width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), format="PNG")
    return sha256_file(path)


def _generate_unsloth(
    local: Path, quantization: str, image_path: Path, instruction: str, max_new_tokens: int
) -> tuple[str, dict[str, float]]:
    # Unsloth патчит transformers и обязан импортироваться первым.
    unsloth = _module("unsloth")
    import torch

    image = _module("PIL.Image").open(str(image_path)).convert("RGB")
    started = time.perf_counter()
    model, processor = unsloth.FastVisionModel.from_pretrained(
        model_name=str(local),
        load_in_4bit=quantization == "4bit",
        dtype=None if quantization == "4bit" else torch.bfloat16,
    )
    unsloth.FastVisionModel.for_inference(model)
    torch.cuda.synchronize()
    loaded = time.perf_counter()
    messages = [
        {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": instruction}]}
    ]
    prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
    inputs = processor(image, prompt, add_special_tokens=False, return_tensors="pt").to("cuda")
    output = model.generate(
        **inputs, max_new_tokens=max_new_tokens, use_cache=True, do_sample=False
    )
    torch.cuda.synchronize()
    finished = time.perf_counter()
    prompt_tokens = int(inputs["input_ids"].shape[1])
    text = str(processor.batch_decode(output[:, prompt_tokens:], skip_special_tokens=True)[0])
    return text, {
        "load_s": round(loaded - started, 2),
        "generate_s": round(finished - loaded, 2),
        "prompt_tokens": prompt_tokens,
        "new_tokens": int(output.shape[1]) - prompt_tokens,
    }


def _generate_transformers(
    local: Path, quantization: str, image_path: Path, instruction: str, max_new_tokens: int
) -> tuple[str, dict[str, float]]:
    import torch

    transformers = _module("transformers")
    image = _module("PIL.Image").open(str(image_path)).convert("RGB")
    options: dict[str, object] = {"dtype": torch.bfloat16, "device_map": "cuda:0"}
    if quantization == "4bit":
        options["quantization_config"] = transformers.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    started = time.perf_counter()
    model = transformers.AutoModelForImageTextToText.from_pretrained(str(local), **options)
    processor = transformers.AutoProcessor.from_pretrained(str(local))
    torch.cuda.synchronize()
    loaded = time.perf_counter()
    messages = [
        {
            "role": "user",
            "content": [{"type": "image", "image": image}, {"type": "text", "text": instruction}],
        }
    ]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    torch.cuda.synchronize()
    finished = time.perf_counter()
    prompt_tokens = int(inputs["input_ids"].shape[1])
    text = str(processor.batch_decode(output[:, prompt_tokens:], skip_special_tokens=True)[0])
    return text, {
        "load_s": round(loaded - started, 2),
        "generate_s": round(finished - loaded, 2),
        "prompt_tokens": prompt_tokens,
        "new_tokens": int(output.shape[1]) - prompt_tokens,
    }


def smoke(
    *,
    model_key: str,
    backend: str,
    quantization: str,
    models_root: Path,
    out_dir: Path,
    max_new_tokens: int = 256,
) -> dict[str, object]:
    """Загрузка и один ответ на синтетическом изображении. Ошибка — BLOCKED с трассировкой."""
    disable_telemetry(os.environ, offline=True)
    model = MODELS[model_key]
    local = models_root / local_dir_name(model)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{model_key}-{backend}-{quantization}"
    image_path = out_dir / f"{name}.png"
    record: dict[str, object] = {
        "model": {"repo_id": model.repo_id, "revision": model.revision, "local_dir": str(local)},
        "backend": backend,
        "quantization": quantization,
        "packages": package_versions(),
        "unsloth_record_sha256": {n: record_sha256(n) for n in ("unsloth", "unsloth-zoo")},
        "input": "synthetic",
    }
    problems = verify_weights(local, model)
    if problems:
        record.update({"status": "BLOCKED", "reasons": problems})
        return _write_record(out_dir / f"{name}.json", record)
    record["image_sha256"] = synthetic_drawing(image_path)
    instruction = INSTRUCTIONS[SLAB_SCHEMA]
    generate = _generate_unsloth if backend == "unsloth" else _generate_transformers
    import torch

    # Любой отказ стека — сам по себе результат дымового прогона: записывается с трассировкой.
    try:
        torch.cuda.reset_peak_memory_stats()
        text, timings = generate(local, quantization, image_path, instruction, max_new_tokens)
    except Exception as error:
        record.update(
            {
                "status": "BLOCKED",
                "reasons": [f"{type(error).__name__}: {error}"],
                "traceback": traceback.format_exc(),
                "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
            }
        )
        return _write_record(out_dir / f"{name}.json", record)
    try:
        objects = parse_slab(text)
        parse: dict[str, object] = {"ok": True, "objects": len(objects)}
    except ResponseError as error:
        parse = {"ok": False, "code": error.code, "detail": error.detail}
    record.update(
        {
            "status": "OK",
            "timings": timings,
            "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
            "response": text,
            # Разбор ответа до обучения — наблюдение, а не условие прохождения дымового прогона.
            "parse": parse,
        }
    )
    return _write_record(out_dir / f"{name}.json", record)


def _write_record(path: Path, record: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"record": str(path), **record}
