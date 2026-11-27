"""Подготовка пакета и SSH-вызов Claude CLI из окружения CAD-движка (`python -I`)."""

import argparse
import hashlib
import importlib.util
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
with tempfile.TemporaryDirectory(prefix="quantor-ai-") as directory:
    root = Path(directory)
    names = {"manifest.json", "walls.json", "project_context.json", "source.pdf", "plan.png",
             "overlay.png", "slab_overlay.png", "prompt.txt", "schema.json", "render.json"}
    optional = {"prev_round_diff.json"}
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for member in archive:
            allowed = member.name in names or member.name in optional
            if not allowed or not member.isfile() or member.size > 32 * 1024 * 1024:
                sys.exit("Invalid review package")
            names.discard(member.name)
            optional.discard(member.name)
            with (root / member.name).open("xb") as target:
                shutil.copyfileobj(archive.extractfile(member), target)
    if names:
        sys.exit("Incomplete review package")
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


def render(root: Path) -> None:
    import pymupdf  # type: ignore[import-not-found]  # Окружение CAD-движка.
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]

    manifest = json.loads((root / "manifest.json").read_bytes())
    walls = json.loads((root / "walls.json").read_bytes())
    with pymupdf.open(root / "input.pdf") as source, pymupdf.open() as excerpt:
        index = manifest["pdf_page"] - 1
        excerpt.insert_pdf(source, from_page=index, to_page=index)
        excerpt.save(root / "source.pdf", garbage=4, deflate=True)
        page = excerpt[0]
        clip = page.rect
        if manifest.get("view_zone"):
            clip &= pymupdf.Rect(manifest["view_zone"])
        if clip.is_empty:
            raise ValueError("Вид не пересекает страницу")
        zoom = 2000 / max(clip.width, clip.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        pix.save(root / "plan.png")

    # Растр покрывает целые пиксели: пиксель (0, 0) лежит в (pix.x / zoom, pix.y / zoom) pt
    # страницы от левого верхнего угла, поэтому в render.json - фактический участок растра.
    extent = [
        pix.x / zoom,
        pix.y / zoom,
        (pix.x + pix.width) / zoom,
        (pix.y + pix.height) / zoom,
    ]
    (root / "render.json").write_text(json.dumps({"clip": extent, "zoom": zoom}), encoding="utf-8")

    base_rgb = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image = base_rgb.copy()
    draw = ImageDraw.Draw(image)
    ox, oy, mm_per_pt = manifest["frame"]

    def draw_ring(ring: list[list[float]], color: str) -> None:
        points = [
            ((ox + x / mm_per_pt) * zoom - pix.x, (oy - y / mm_per_pt) * zoom - pix.y)
            for x, y in ring
        ]
        if len(points) >= 3:
            draw.line([*points, points[0]], fill=color, width=2)

    for group, color in (("constructions", "#e11d48"), ("frame_partitions", "#0284c7")):
        for row in walls.get(group, []):
            polygon = row["polygon"]
            for ring in [polygon["shell"], *polygon["holes"]]:
                draw_ring(ring, color)
    for opening in walls.get("openings", []):
        if opening.get("lintel"):
            draw_ring(opening["lintel"], "#15803d")
    image.save(root / "overlay.png")

    spec = importlib.util.spec_from_file_location(
        "view_render_cli", Path(__file__).with_name("view_render_cli.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("view_render_cli.py не найден рядом с ai_review_cli.py")
    render_mod: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render_mod)
    render_mod.render_slab_overlay(
        base_rgb=base_rgb,
        walls=walls,
        frame=(ox, oy, mm_per_pt),
        zoom=zoom,
        pix_x=pix.x,
        pix_y=pix.y,
        out_path=root / "slab_overlay.png",
    )


def review(root: Path, ssh_config: str, timeout: int) -> None:
    render(root)
    if not (root / "project_context.json").is_file():
        (root / "project_context.json").write_text("{}", encoding="utf-8")
    # Промт положил исполнитель из активной версии (ai_prompt_versions); здесь он только читается.
    prompt = (root / "prompt.txt").read_bytes().decode("utf-8")
    package = root / "bundle.tar"
    with tarfile.open(package, "w") as archive:
        for name in (
            "manifest.json",
            "walls.json",
            "project_context.json",
            "source.pdf",
            "plan.png",
            "overlay.png",
            "slab_overlay.png",
            "prompt.txt",
            "schema.json",
            "render.json",
        ):
            path = root / name
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError(f"Файл пакета превышает 32 МиБ: {name}")
            archive.add(path, arcname=name)
        prev_diff = root / "prev_round_diff.json"
        if prev_diff.is_file() and prev_diff.stat().st_size > 2:
            if prev_diff.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("Файл пакета превышает 32 МиБ: prev_round_diff.json")
            archive.add(prev_diff, arcname="prev_round_diff.json")
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
        "python3 -c " + shlex.quote(REMOTE) + f" {timeout}",
    ]
    answer = root / "answer.out"
    with package.open("rb") as payload, answer.open("wb") as report:
        result = subprocess.run(command, stdin=payload, stdout=report, check=False)  # noqa: S603
    if result.returncode:
        raise SystemExit(result.returncode)
    data = json.loads(answer.read_bytes())
    data["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    data["bundle_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
    (root / "review.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("ssh_config")
    parser.add_argument("timeout", type=int)
    args = parser.parse_args()
    review(args.root, args.ssh_config, args.timeout)
