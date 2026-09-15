"""Закреплённые Qwen3-VL Instruct: ревизия и SHA-256 файлов весов — до скачивания.

Значения сняты 2026-09-15 из `https://huggingface.co/api/models/<id>/revision/<sha>?blobs=true`
и совпадают с `vision/licenses/decisions.json`. Скачанный файл с другим хешем — отказ, а не
предупреждение: это другой родитель, и адаптер от него несравним.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PinnedModel:
    repo_id: str
    revision: str
    weights_sha256: dict[str, str]
    role: str


MODELS: dict[str, PinnedModel] = {
    "2b": PinnedModel(
        repo_id="Qwen/Qwen3-VL-2B-Instruct",
        revision="89644892e4d85e24eaac8bacfd4f463576704203",
        weights_sha256={
            "model.safetensors": "7de1838c87a5349b016c26a1c3f7d2bc400a3d485f95ef39a7059ffd734977a0",
        },
        role="нижняя граница эффективности",
    ),
    "4b": PinnedModel(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        revision="ebb281ec70b05090aa6165b016eac8ec08e71b17",
        weights_sha256={
            "model-00001-of-00002.safetensors": (
                "30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9"
            ),
            "model-00002-of-00002.safetensors": (
                "046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6"
            ),
        },
        role="основная",
    ),
    "8b": PinnedModel(
        repo_id="Qwen/Qwen3-VL-8B-Instruct",
        revision="0c351dd01ed87e9c1b53cbc748cba10e6187ff3b",
        weights_sha256={
            "model-00001-of-00004.safetensors": (
                "d5d0aef0eb170fc7453a296c43c0849a56f510555d3588e4fd662bb35490aefa"
            ),
            "model-00002-of-00004.safetensors": (
                "8be88fb5501e4d5719a6d4cc212e6a13480330e74f3e8c77daa1a68f199106b5"
            ),
            "model-00003-of-00004.safetensors": (
                "83de00eafe6e0d57ccd009dbcf71c9974d74df2f016c27afb7e95aafd16b2192"
            ),
            "model-00004-of-00004.safetensors": (
                "0a88b98e9f96270973f567e6a2c103ede6ccdf915ca3075e21c755604d0377a5"
            ),
        },
        role="условная верхняя граница: только если 4B оставляет неоднозначность и хватает памяти",
    ),
}

# Версии, под которые собран requirements-qwen-unsloth.txt; расхождение в окружении — предупреждение
# в отчёте probe, чтобы прогон не записался как сделанный на другом стеке.
EXPECTED_PACKAGES = {
    "torch": "2.11.0+cu128",
    "torchvision": "0.26.0+cu128",
    "transformers": "5.5.0",
    "trl": "0.24.0",
    "peft": "0.20.0",
    "accelerate": "1.15.0",
    "bitsandbytes": "0.50.2",
    "xformers": "0.0.35",
    "datasets": "4.3.0",
    "unsloth": "2026.9.4",
    "unsloth-zoo": "2026.9.3",
}

# SHA-256 wheel из матрицы лицензий: сверяются при установке (gpu-runbook.md, § Qwen).
UNSLOTH_WHEELS_SHA256 = {
    "unsloth-2026.9.4-py3-none-any.whl": (
        "7892ac14733ba22200ef4a228ac26e06275562c5f72b96a654605d4dcbd05264"
    ),
    "unsloth_zoo-2026.9.3-py3-none-any.whl": (
        "d846a0cdf343ff4ca79a01806e45249362b4ad107442d3c68d32cee3527d350c"
    ),
}


def local_dir_name(model: PinnedModel) -> str:
    return model.repo_id.replace("/", "--") + "@" + model.revision[:12]
