"""Пакет сопоставления ВОР и SSH-вызов Claude CLI из окружения CAD-движка (`python -I`).

Только стандартная библиотека. Файлы пакета подготовил исполнитель: позиции ВОР и объекты Quantor
без количеств, промт активной версии `vor_mapper` и схема отчёта.
"""

import argparse
import hashlib
import json
import shlex
import subprocess
import tarfile
from pathlib import Path

# Получатель читает только фиксированный набор имён из архива, который подготовил исполнитель.
# Временная папка и независимый таймаут на сервере ограничивают время хранения пакета.
REMOTE = """
import json, os, re, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path

timeout = int(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="quantor-vormap-") as directory:
    root = Path(directory)
    names = {"manifest.json", "vor_items.json", "objects.json", "prompt.txt", "schema.json"}
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for member in archive:
            if member.name not in names or not member.isfile() or member.size > 8 * 1024 * 1024:
                sys.exit("Invalid vor map package")
            names.remove(member.name)
            with (root / member.name).open("xb") as target:
                shutil.copyfileobj(archive.extractfile(member), target)
    if names:
        sys.exit("Incomplete vor map package")
    manifest = json.loads((root / "manifest.json").read_bytes())
    model = manifest["model"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", model):
        sys.exit("Invalid model name")
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

PACKAGE_FILES = ("manifest.json", "vor_items.json", "objects.json", "prompt.txt", "schema.json")
MAX_MEMBER_BYTES = 8 * 1024 * 1024


def remote_command(timeout: int) -> str:
    return "python3 -c " + shlex.quote(REMOTE) + f" {timeout}"


def map_vor(root: Path, ssh_config: str, timeout: int) -> None:
    # Промт положил исполнитель из активной версии (ai_prompt_versions); здесь он только читается.
    prompt = (root / "prompt.txt").read_bytes().decode("utf-8")
    package = root / "bundle.tar"
    with tarfile.open(package, "w") as archive:
        for name in PACKAGE_FILES:
            path = root / name
            if path.stat().st_size > MAX_MEMBER_BYTES:
                raise ValueError(f"Файл пакета превышает 8 МиБ: {name}")
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
    (root / "vor_map.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("ssh_config")
    parser.add_argument("timeout", type=int)
    args = parser.parse_args()
    map_vor(args.root, args.ssh_config, args.timeout)
