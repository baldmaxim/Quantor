"""Пакет роли «координация» и SSH-вызов Claude CLI из окружения CAD-движка (`python -I`).

Модуль самодостаточен: соседние модули не импортируются (запуск с `-I`). Пакет: манифест, оси
целевого вида и эталона без координат (`axes_*.json`), два плана (`plan_target.png`,
`plan_reference.png`) с красными метками идентификаторов осей, промт и схема. Метки рисуются по
`draw_*.json` (положение осей на странице, pt) - этот файл в пакет модели не входит.
"""

import argparse
import hashlib
import importlib
import json
import shlex
import subprocess
import tarfile
from pathlib import Path
from typing import Any

# Получатель читает только фиксированный набор имён из архива, который подготовил исполнитель.
# Временная папка и независимый таймаут на сервере ограничивают время хранения пакета.
REMOTE = """
import hashlib, json, os, re, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path

timeout = int(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="quantor-coord-") as directory:
    root = Path(directory)
    names = {"manifest.json", "axes_target.json", "axes_reference.json", "plan_target.png",
             "plan_reference.png", "prompt.txt", "schema.json"}
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for member in archive:
            if member.name not in names or not member.isfile() or member.size > 32 * 1024 * 1024:
                sys.exit("Invalid coordination package")
            names.remove(member.name)
            with (root / member.name).open("xb") as target:
                shutil.copyfileobj(archive.extractfile(member), target)
    if names:
        sys.exit("Incomplete coordination package")
    manifest = json.loads((root / "manifest.json").read_bytes())
    model = manifest["model"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", model):
        sys.exit("Invalid model name")
    raw_sources = manifest["sources"]
    if not 1 <= len(raw_sources) <= 8:
        sys.exit("One to eight source documents are required")
    (root / "sources").mkdir()
    sources = {}
    for role, name in raw_sources.items():
        if not re.fullmatch(r"[a-z_]{2,32}", role):
            sys.exit("Invalid source role")
        with Path(name).open("rb") as source:
            data = source.read(16 * 1024 * 1024 + 1)
        if not data.strip() or len(data) > 16 * 1024 * 1024:
            sys.exit("Empty or oversized source: " + role)
        (root / "sources" / (role + ".md")).write_bytes(data)
        sources[role] = {"filename": Path(name).name, "sha256": hashlib.sha256(data).hexdigest()}
    manifest["sources"] = sources
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    home = Path.home()
    env["PATH"] = os.pathsep.join([str(home / ".local/bin"), env["PATH"]])
    schema = (root / "schema.json").read_text(encoding="utf-8")
    try:
        with (root / "prompt.txt").open("rb") as prompt, (root / "answer.json").open("wb") as out:
            subprocess.run(
                [shutil.which("claude", path=env["PATH"]) or "claude",
                 "-p", "--model", model, "--setting-sources", "", "--strict-mcp-config",
                 "--disable-slash-commands", "--no-session-persistence",
                 "--output-format", "json", "--json-schema", schema,
                 "--allowed-tools", "Read", "--permission-mode", "dontAsk"],
                cwd=root, env=env, stdin=prompt, stdout=out,
                stderr=subprocess.DEVNULL, check=True, timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        sys.exit(124)
    with (root / "answer.json").open("rb") as answer:
        data = json.loads(answer.read(4 * 1024 * 1024))
    if isinstance(data, list):
        data = next((item for item in reversed(data) if item.get("type") == "result"), {})
    if data.get("is_error") or not isinstance(data.get("structured_output"), dict):
        sys.exit(3)
    usage = data.get("usage") or {}
    print(json.dumps({
        "sources": sources,
        "report": data["structured_output"],
        "usage": {
            "cost_usd": data.get("total_cost_usd"),
            "duration_ms": data.get("duration_ms"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        },
        "model": model,
    }, ensure_ascii=False))
"""

PACKAGE_FILES = (
    "manifest.json",
    "axes_target.json",
    "axes_reference.json",
    "plan_target.png",
    "plan_reference.png",
    "prompt.txt",
    "schema.json",
)
SIDES = ("target", "reference")
MAX_MEMBER_BYTES = 32 * 1024 * 1024
PLAN_SIDE_PX = 2000
TAG_PX = 22
TAG_COLOR = (0.85, 0.0, 0.0)


def remote_command(timeout: int) -> str:
    return "python3 -c " + shlex.quote(REMOTE) + f" {timeout}"


def _tag(pymupdf: Any, page: Any, text: str, x: float, y: float) -> None:
    """Красная метка идентификатора оси: белая подложка, красная рамка и текст (пиксели рисунка)."""
    width = TAG_PX * 0.62 * len(text) + 8
    x = min(max(x, width / 2), page.rect.width - width / 2)
    y = min(max(y, TAG_PX / 2), page.rect.height - TAG_PX / 2)
    rect = pymupdf.Rect(x - width / 2, y - TAG_PX / 2, x + width / 2, y + TAG_PX / 2)
    page.draw_rect(rect, color=TAG_COLOR, fill=(1, 1, 1), width=1.5)
    # Без подгонки в рамку: `insert_textbox` молча ничего не рисует, если текст не влез.
    page.insert_text(
        (rect.x0 + 4, rect.y1 - TAG_PX * 0.25),
        text,
        fontsize=TAG_PX * 0.7,
        fontname="helv",
        color=TAG_COLOR,
    )


def _render_side(pymupdf: Any, root: Path, manifest: dict[str, Any], side: str) -> None:
    spec = manifest[side]
    with pymupdf.open(root / spec["pdf_file"]) as source:
        page = source[spec["pdf_page"] - 1]
        clip = page.rect
        if spec.get("view_zone"):
            clip &= pymupdf.Rect(spec["view_zone"])
        if clip.is_empty:
            raise ValueError("Вид не пересекает страницу")
        zoom = PLAN_SIDE_PX / max(clip.width, clip.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        image = pix.tobytes("png")
    axes = json.loads((root / f"draw_{side}.json").read_bytes())["axes"]
    with pymupdf.open() as canvas:
        sheet = canvas.new_page(width=pix.width, height=pix.height)
        sheet.insert_image(sheet.rect, stream=image)
        # Соседние метки расходятся по двум рядам: подписи близких осей не накрывают друг друга.
        rows = {"vertical": 0, "horizontal": 0}
        for axis in sorted(axes, key=lambda item: (item["orient"], item["pos_pt"])):
            lane = rows[axis["orient"]] % 2
            rows[axis["orient"]] += 1
            offset = TAG_PX * (0.9 + 1.2 * lane)
            if axis["orient"] == "vertical":
                x = axis["pos_pt"] * zoom - pix.x
                _tag(pymupdf, sheet, axis["id"], x, offset)
                _tag(pymupdf, sheet, axis["id"], x, pix.height - offset)
            else:
                y = axis["pos_pt"] * zoom - pix.y
                _tag(pymupdf, sheet, axis["id"], offset * 1.6, y)
                _tag(pymupdf, sheet, axis["id"], pix.width - offset * 1.6, y)
        sheet.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(root / f"plan_{side}.png")


def render(root: Path) -> None:
    pymupdf = importlib.import_module("pymupdf")  # Окружение CAD-движка, не API.

    manifest = json.loads((root / "manifest.json").read_bytes())
    for side in SIDES:
        _render_side(pymupdf, root, manifest, side)


def coordinate(root: Path, ssh_config: str, timeout: int) -> None:
    render(root)
    # Промт положил исполнитель из активной версии (ai_prompt_versions); здесь он только читается.
    prompt = (root / "prompt.txt").read_bytes().decode("utf-8")
    package = root / "bundle.tar"
    with tarfile.open(package, "w") as archive:
        for name in PACKAGE_FILES:
            path = root / name
            if path.stat().st_size > MAX_MEMBER_BYTES:
                raise ValueError(f"Файл пакета превышает 32 МиБ: {name}")
            archive.add(path, arcname=name)
    command = [
        "ssh",
        "-F",
        ssh_config,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "kg_claude",
        remote_command(timeout),
    ]
    answer = root / "answer.out"
    with package.open("rb") as payload, answer.open("wb") as report:
        result = subprocess.run(command, stdin=payload, stdout=report, check=False)  # noqa: S603
    if result.returncode:
        raise SystemExit(result.returncode)
    data = json.loads(answer.read_bytes())
    data["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    data["bundle_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
    (root / "coordination.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("ssh_config")
    parser.add_argument("timeout", type=int)
    args = parser.parse_args()
    coordinate(args.root, args.ssh_config, args.timeout)
