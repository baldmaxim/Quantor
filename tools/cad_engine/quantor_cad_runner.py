"""Runner движка PDF → CAD для Quantor (пилот за флагом cad.export, ADR-0036).

Запускается интерпретатором отдельного окружения движка с закреплёнными зависимостями:

    <engine-python> -I quantor_cad_runner.py verify --archive ZIP
    <engine-python> -I quantor_cad_runner.py run --archive ZIP --input PDF --params JSON \
        --work DIR --out DIR [--expect-archive-sha256 HEX] [--progress FILE]

`--progress` — файл вне `--out` и `--work`, куда runner атомарно пишет снимок хода работы
(`quantor.cad_engine.progress.v1`): собственные фазы runner и этапы видов, которые штатный
worker сам публикует в `events.json`. Ничего не досчитывается по таймеру: в снимок попадает
только то, что движок уже записал. Поля проходят белый список, пути из текста вырезаются.

Код движка в git не хранится. Runner читает SHA-закреплённый ZIP с исходниками, сверяет
SHA архива, MANIFEST.json и каждого файла, распаковывает его в каталог попытки и запускает
штатный `pdf_job_monitor/worker.py` отдельным процессом с ограничением времени и памяти.
Из результатов в `--out` попадают только опубликованные worker'ом файлы, раздельно по видам,
с `report.json` и `manifest.json` (sha256 каждого файла).

Коды возврата: 0 — работа выполнена (`completed_requires_review` или `no_cad_review_required`);
1 — ошибка движка или нарушение гейта; 2 — некорректный вход; 3 — некорректные параметры;
4 — превышен предел; 5 — не прошла проверка архива или окружения.

Только стандартная библиотека на уровне модуля; движок (PyMuPDF, ezdxf) импортируется
лениво и только в этом процессе — процесс API Quantor его не импортирует.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

PINS_PATH = Path(__file__).resolve().with_name("pins.json")
PARAMS_SCHEMA = "quantor.cad_engine.params.v2"
REPORT_SCHEMA = "quantor.cad_engine.report.v1"
MANIFEST_SCHEMA = "quantor.cad_engine.manifest.v1"
# scale.json вида (движок после ADR-0036): status — passed | needs_review | failed,
# source — operator_calibration | dimension_chains.
SCALE_PASSED = "passed"
SCALE_NEEDS_REVIEW = "needs_review"
SCALE_FAILED = "failed"
SCALE_SOURCE_OPERATOR = "operator_calibration"
FAILURE_CALIBRATION_MISMATCH = "calibration_mismatch"
LIMIT_KEYS = {"max_pages": (1, 200), "total_timeout_s": (10, 7200), "max_memory_mb": (256, 16384)}
DEFAULT_LIMITS = {"max_pages": 50, "total_timeout_s": 900, "max_memory_mb": 3072}
# Имена, которые публикует legacy worker (available_artifacts), → ASCII-имена Quantor.
PUBLISHED = {"Масштаб.json": "scale.json", "План_кандидаты.dxf": "plan_candidates.dxf",
             "Контроль_CAD.json": "cad_checks.json"}
CHECKS_FILE, CHECKS_NAME = "Контроль.json", "checks.json"
FORBIDDEN_ACTIVE = ("native_cad_read_during_recognition", "pilot_geometry_read_during_recognition",
                    "finish_detector_called", "quantity_release_allowed")
VIEW_DIR = re.compile(r"^PDF_(\d{3})_Вид_(\d{2})/(.+)$")
FILL_ONLY_SIGNATURE = "zero-size array"

EXIT_OK, EXIT_ENGINE, EXIT_INPUT, EXIT_PARAMS, EXIT_LIMIT, EXIT_INTEGRITY = 0, 1, 2, 3, 4, 5

PROGRESS_SCHEMA = "quantor.cad_engine.progress.v1"
PREVIEW_SCHEMA = "quantor.cad_engine.preview.v1"
# Семь этапов вида у штатного worker (architecture_transfer.STAGES), в том же порядке.
STAGE_KEYS = ("source", "regions", "scale", "geometry", "assemblies", "checks", "export")
STAGE_STATES = frozenset({"running", "done", "needs_review", "error"})
VIEW_STATES = frozenset({"queued", "running", "done", "needs_review", "error"})
ENGINE_STATES = frozenset({"running", "needs_review", "error"})
# Путь в тексте этапа: абсолютный POSIX или Windows. «0 / 89» путём не считается.
PATH_LIKE = re.compile(r"(?:[A-Za-z]:\\|/)(?:[^\s/\\]+[/\\])+[^\s]*")
PROGRESS_POLL_S = 0.25
# Предпросмотр DXF: кривые спрямляются с этой точностью, объём ограничен.
PREVIEW_FLATTEN_MM = 5.0
PREVIEW_MAX_POINTS = 250_000


class RunnerError(Exception):
    def __init__(self, exit_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.exit_code, self.code, self.message = exit_code, code, message


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def load_pins() -> dict[str, Any]:
    pins: dict[str, Any] = json.loads(PINS_PATH.read_bytes())
    if pins.get("schema") != "quantor.cad_engine.pins.v1":
        raise RunnerError(EXIT_INTEGRITY, "pins_invalid", "pins.json: неизвестная схема")
    return pins


def runner_identity(pins: dict[str, Any]) -> dict[str, str]:
    return {"version": pins["runner_version"], "sha256": sha256_file(Path(__file__).resolve()),
            "pins_sha256": sha256_file(PINS_PATH)}


# ------------------------------------------------------------------ окружение и архив


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def check_environment(pins: dict[str, Any]) -> dict[str, str]:
    """Точные версии интерпретатора и пакетов. Несовпадение — отказ, а не предупреждение."""
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if python != pins["python"] or sys.implementation.name != "cpython":
        raise RunnerError(EXIT_INTEGRITY, "environment_mismatch",
                          f"нужен CPython {pins['python']}, получен {sys.implementation.name} {python}")
    found: dict[str, str] = {}
    for dist in metadata.distributions():
        found[_norm(dist.metadata["Name"] or "")] = dist.version
    actual: dict[str, str] = {}
    for name, version in pins["packages"].items():
        have = found.get(_norm(name))
        if have != version:
            raise RunnerError(EXIT_INTEGRITY, "environment_mismatch",
                              f"{name}: нужен {version}, установлен {have}")
        actual[name] = have
    return {"python": sys.version.split()[0], **actual}


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or name.endswith("/") or "\\" in name or path.is_absolute()
            or any(part in ("", ".", "..") for part in path.parts)):
        raise RunnerError(EXIT_INTEGRITY, "archive_invalid", "недопустимое имя в архиве")
    return path


def verify_archive(archive: Path, pins: dict[str, Any], expected_sha: str | None = None) -> dict[str, Any]:
    """SHA архива, SHA MANIFEST.json, состав и SHA каждого файла — до распаковки."""
    engine = pins["engine"]
    if expected_sha is not None and expected_sha != engine["archive_sha256"]:
        raise RunnerError(EXIT_INTEGRITY, "archive_pin_mismatch",
                          "ожидаемый SHA архива у Quantor и у runner различаются")
    if not archive.is_file():
        raise RunnerError(EXIT_INTEGRITY, "archive_missing", "архив движка не найден")
    archive_sha = sha256_file(archive)
    if archive_sha != engine["archive_sha256"]:
        raise RunnerError(EXIT_INTEGRITY, "archive_sha_mismatch", "SHA256 архива не совпал с pins")
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) != engine["archive_entries"]:
            raise RunnerError(EXIT_INTEGRITY, "archive_invalid", "число записей архива не совпало")
        if sum(info.file_size for info in infos) > engine["max_unpacked_bytes"]:
            raise RunnerError(EXIT_INTEGRITY, "archive_invalid", "архив больше допустимого")
        for info in infos:
            _safe_member(info.filename)
            mode = info.external_attr >> 16
            if info.is_dir() or (mode and not stat.S_ISREG(mode)):
                raise RunnerError(EXIT_INTEGRITY, "archive_invalid", "в архиве не только файлы")
        manifest_bytes = bundle.read("MANIFEST.json")
        if hashlib.sha256(manifest_bytes).hexdigest() != engine["manifest_sha256"]:
            raise RunnerError(EXIT_INTEGRITY, "manifest_sha_mismatch", "SHA256 MANIFEST.json не совпал")
        manifest = json.loads(manifest_bytes)
        if manifest.get("version") != engine["version"] or \
                manifest.get("source_snapshot_sha256") != engine["source_snapshot_sha256"]:
            raise RunnerError(EXIT_INTEGRITY, "manifest_invalid", "версия в манифесте не совпала")
        expected = {row["file"]: row["sha256"] for row in manifest["files"]}
        names = {info.filename for info in infos} - {"MANIFEST.json"}
        if names != set(expected):
            raise RunnerError(EXIT_INTEGRITY, "manifest_invalid", "состав архива не совпал с манифестом")
        for name, digest in expected.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != digest:
                raise RunnerError(EXIT_INTEGRITY, "file_sha_mismatch", f"SHA256 файла не совпал: {name}")
    return {"name": engine["name"], "version": engine["version"], "archive_sha256": archive_sha,
            "manifest_sha256": engine["manifest_sha256"],
            "source_snapshot_sha256": engine["source_snapshot_sha256"], "files_verified": len(expected)}


def extract_archive(archive: Path, target: Path, pins: dict[str, Any]) -> None:
    """Распаковка уже проверенного архива; повторная сверка SHA каждого файла после записи."""
    target.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("MANIFEST.json"))
        expected = {row["file"]: row["sha256"] for row in manifest["files"]}
        for info in bundle.infolist():
            destination = target.joinpath(*_safe_member(info.filename).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, destination.open("xb") as sink:
                shutil.copyfileobj(source, sink)
            if info.filename in expected and sha256_file(destination) != expected[info.filename]:
                raise RunnerError(EXIT_INTEGRITY, "file_sha_mismatch", "файл изменился при распаковке")
    if not (target / pins["engine"]["worker"]).is_file():
        raise RunnerError(EXIT_INTEGRITY, "archive_invalid", "в архиве нет штатного worker")


# ------------------------------------------------------------------ параметры и вход


def _parse_scales(raw: Any, pages: list[int]) -> dict[str, dict[str, Any]]:
    """scales: ключ — индекс страницы с 0 строкой, ровно для выбранных страниц."""
    if not isinstance(raw, dict) or set(raw) != {str(p) for p in pages}:
        raise RunnerError(EXIT_PARAMS, "params_invalid", "scales: ключи должны совпадать с pages")
    scales: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict) or set(entry) != {"mm_per_pt", "calibration_id"}:
            raise RunnerError(EXIT_PARAMS, "params_invalid",
                              f"scales.{key}: нужны mm_per_pt и calibration_id")
        factor, calibration = entry["mm_per_pt"], entry["calibration_id"]
        if (isinstance(factor, bool) or not isinstance(factor, (int, float))
                or not math.isfinite(factor) or factor <= 0):
            raise RunnerError(EXIT_PARAMS, "params_invalid",
                              f"scales.{key}.mm_per_pt: конечное число больше нуля")
        if not isinstance(calibration, str) or not calibration or len(calibration) > 64:
            raise RunnerError(EXIT_PARAMS, "params_invalid",
                              f"scales.{key}.calibration_id: непустая строка")
        scales[key] = {"mm_per_pt": float(factor), "calibration_id": calibration}
    return scales


def parse_params(raw: bytes) -> dict[str, Any]:
    """Схема quantor.cad_engine.params.v2: лист и масштаб задаёт человек.

    Отделка и ведомости объёмов — только false. `pages` обязательны, `scales` — по странице.
    """
    try:
        params = json.loads(raw)
    except ValueError as error:
        raise RunnerError(EXIT_PARAMS, "params_invalid", "params.json не JSON") from error
    if not isinstance(params, dict):
        raise RunnerError(EXIT_PARAMS, "params_invalid", "params.json не объект")
    allowed = {"schema", "mode", "pages", "page_selection", "scales", "finishes", "schedules",
               "limits"}
    if set(params) - allowed or params.get("schema") != PARAMS_SCHEMA:
        raise RunnerError(EXIT_PARAMS, "params_invalid", "неизвестная схема или поле параметров")
    if params.get("mode") != "architecture":
        raise RunnerError(EXIT_PARAMS, "params_invalid", "поддерживается только mode=architecture")
    if params.get("page_selection") != "operator":
        raise RunnerError(EXIT_PARAMS, "params_invalid", "page_selection: только operator")
    if params.get("finishes") is not False or params.get("schedules") is not False:
        raise RunnerError(EXIT_PARAMS, "params_invalid", "отделка и ведомости объёмов выключены")
    pages = params.get("pages")
    if (not isinstance(pages, list) or not pages or not all(type(p) is int and p >= 0 for p in pages)
            or len(set(pages)) != len(pages)):
        raise RunnerError(EXIT_PARAMS, "params_invalid", "pages: непустой список индексов с 0")
    scales = _parse_scales(params.get("scales"), pages)
    limits = dict(DEFAULT_LIMITS)
    given = params.get("limits", {})
    if not isinstance(given, dict) or set(given) - set(LIMIT_KEYS):
        raise RunnerError(EXIT_PARAMS, "params_invalid", "limits: неизвестное поле")
    for key, value in given.items():
        low, high = LIMIT_KEYS[key]
        if type(value) is not int or not low <= value <= high:
            raise RunnerError(EXIT_PARAMS, "params_invalid", f"limits.{key} вне [{low}, {high}]")
        limits[key] = value
    return {**params, "pages": pages, "scales": scales, "limits": limits}


def operator_scales_for_job(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Масштабы оператора для job.json: ключ — pdf_page с 1 строкой (как `legacy_page`)."""
    return {str(legacy_page(int(index))): {"mm_per_pt": entry["mm_per_pt"],
                                           "calibration_id": entry["calibration_id"]}
            for index, entry in params["scales"].items()}


def job_document(pages: list[int], params: dict[str, Any]) -> dict[str, Any]:
    """job.json для worker'а движка: страницы и масштабы выбирает оператор."""
    return {"id": "job", "status": "running", "attempt": 1, "pages": pages,
            "operator_pages": True, "operator_scales": operator_scales_for_job(params)}


def legacy_page(index: int) -> int:
    """Quantor: page_index с 0 (Sheet.page_index). Legacy worker: pdf_page с 1."""
    return index + 1


def quantor_index(pdf_page: int) -> int:
    return pdf_page - 1


def intake(engine_root: Path, pins: dict[str, Any], source: Path) -> dict[str, Any]:
    """Штатный intake движка: битый, зашифрованный, пустой вход отклоняется до worker."""
    intake_dir = str(engine_root / pins["engine"]["intake"])
    sys.path.insert(0, intake_dir)
    try:
        from intake_profile import IntakeError, inspect_pdf
    finally:
        sys.path.remove(intake_dir)
    try:
        result: dict[str, Any] = inspect_pdf(source)
    except IntakeError as error:
        raise RunnerError(EXIT_INPUT, "input_invalid", str(error)) from error
    return result


# ------------------------------------------------------------------ ход работы


def _text(value: Any, limit: int) -> str:
    """Текст этапа для показа: без путей файловой системы, ограниченной длины."""
    if not isinstance(value, str):
        return ""
    return PATH_LIKE.sub("…", value)[:limit]


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def sanitize_views(raw: Any) -> list[dict[str, Any]]:
    """Этапы видов из `events.json` worker'а по белому списку полей и значений."""
    views: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        page, view = item.get("page"), item.get("view")
        if type(page) is not int or type(view) is not int or page < 1 or view < 0:
            continue
        stages: list[dict[str, Any]] = []
        for step in item.get("stages") or []:
            if not isinstance(step, dict) or step.get("key") not in STAGE_KEYS:
                continue
            entry: dict[str, Any] = {
                "key": step["key"],
                "status": step["status"] if step.get("status") in STAGE_STATES else "unknown",
            }
            elapsed = step.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0:
                entry["elapsed_s"] = round(float(elapsed), 3)
            completed, total = _count(step.get("completed_items")), _count(step.get("total_items"))
            if completed is not None and total is not None:
                entry.update(completed=completed, total=total)
            detail = _text(step.get("detail"), 160)
            if detail:
                entry["detail"] = detail
            stages.append(entry)
        views.append({
            "index": quantor_index(page), "legacy_pdf_page": page, "view": view,
            "status": item["status"] if item.get("status") in VIEW_STATES else "unknown",
            "stage": _text(item.get("stage"), 160), "ready": item.get("ready") is True,
            "stages": stages,
        })
    return views


class Progress:
    """Снимок хода попытки для исполнителя Quantor. Без `--progress` ничего не пишет."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.state: dict[str, Any] = {"schema": PROGRESS_SCHEMA, "seq": 0, "phase": "starting",
                                      "phase_detail": "", "phases": [], "pages": None,
                                      "engine": None, "views": [], "error": None}
        self._source: tuple[int, int] | None = None
        self._started = time.monotonic()

    def phase(self, phase: str, detail: str = "", **extra: Any) -> None:
        # История фаз в снимке: читатель опрашивает файл реже, чем меняются быстрые фазы,
        # и без неё «проверка архива» и «входной контроль» терялись бы между опросами.
        self.state["phases"].append({"phase": phase, "detail": detail,
                                     "t_s": round(time.monotonic() - self._started, 3)})
        self.state.update(phase=phase, phase_detail=detail, **extra)
        self._write()

    def mirror(self, events_path: Path) -> None:
        """Переносит свежий `events.json` worker'а, если файл изменился с прошлого раза."""
        try:
            info = events_path.stat()
        except OSError:
            return
        mark = (info.st_mtime_ns, info.st_size)
        if mark == self._source:
            return
        try:
            events = json.loads(events_path.read_bytes())
        except (OSError, ValueError):
            return  # worker пишет атомарно; недочитанный файл подхватится на следующем опросе
        self._source = mark
        if not isinstance(events, dict):
            return
        status = events.get("status")
        self.state["engine"] = {
            "status": status if status in ENGINE_STATES else "unknown",
            "stage": _text(events.get("stage"), 160),
            "error": _text(events.get("error"), 240) or None,
        }
        self.state["views"] = sanitize_views(events.get("views"))
        self._write()

    def _write(self) -> None:
        if self.path is None:
            return
        self.state["seq"] += 1
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_bytes(canonical_json(self.state))
        os.replace(temporary, self.path)


# ------------------------------------------------------------------ worker


def _limit_memory(max_mb: int) -> None:
    import resource

    limit = max_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def run_worker(engine_root: Path, operator: Path, job_dir: Path, attempt: Path, pages: list[int],
               limits: dict[str, int], log_path: Path, progress: Progress | None = None) -> int:
    worker = engine_root / load_pins()["engine"]["worker"]
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(job_dir), "TMPDIR": str(job_dir),
           "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "CAD_JOB_MONITOR_OPERATOR_ROOT": str(operator)}
    command = [sys.executable, "-B", "-s", str(worker), str(job_dir / "input.pdf"), str(attempt),
               ",".join(map(str, pages))]
    deadline = time.monotonic() + limits["total_timeout_s"]
    events_path = attempt / "events.json"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command, cwd=engine_root, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT,
            preexec_fn=lambda: _limit_memory(limits["max_memory_mb"]),
        )
        while True:
            try:
                code = process.wait(timeout=PROGRESS_POLL_S)
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise RunnerError(EXIT_LIMIT, "timeout",
                                      "превышено общее время обработки") from None
                if progress is not None:
                    progress.mirror(events_path)
                continue
            if progress is not None:
                progress.mirror(events_path)
            return code


def _dxf_summary(path: Path) -> dict[str, Any]:
    import ezdxf  # окружение движка

    document = ezdxf.readfile(path)
    entities = len(document.modelspace())
    errors = len(document.audit().errors)
    if entities == 0 or errors:
        raise RunnerError(EXIT_ENGINE, "gate_violation", "DXF пуст или не прошёл аудит")
    return {"dxf_version": document.dxfversion, "entities": entities, "audit_errors": errors}


def _preview(dxf: Path, rel: str) -> dict[str, Any]:
    """Геометрия DXF для просмотра: полилинии по слоям в мм системы DXF, без текста.

    Строится тем же ezdxf из выпущенного файла, а не из промежуточных данных движка: на экране
    ровно то, что лежит в скачиваемом DXF. Кривые спрямлены, блоки раскрыты.
    """
    import ezdxf  # окружение движка
    from ezdxf import disassemble

    document = ezdxf.readfile(dxf)
    layers: dict[str, int] = {}
    paths: list[dict[str, Any]] = []
    skipped = {"text": 0, "other": 0}
    total = 0
    truncated = False
    low = [float("inf"), float("inf")]
    high = [float("-inf"), float("-inf")]
    entities = disassemble.recursive_decompose(document.modelspace())
    for primitive in disassemble.to_primitives(entities, max_flattening_distance=PREVIEW_FLATTEN_MM):
        kind = primitive.entity.dxftype()
        if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            skipped["text"] += 1
            continue
        path = primitive.path
        if path is None:
            skipped["other"] += 1
            continue
        layer = _text(str(primitive.entity.dxf.layer), 64) or "0"
        index = layers.setdefault(layer, len(layers))
        for sub in path.sub_paths():
            points = [(round(v.x, 2), round(v.y, 2)) for v in sub.flattening(PREVIEW_FLATTEN_MM)]
            if len(points) < 2:
                continue
            if total + len(points) > PREVIEW_MAX_POINTS:
                truncated = True
                break
            total += len(points)
            for x, y in points:
                low = [min(low[0], x), min(low[1], y)]
                high = [max(high[0], x), max(high[1], y)]
            paths.append({"layer": index, "closed": bool(sub.is_closed), "fill": kind == "HATCH",
                          "points": [c for point in points for c in point]})
        if truncated:
            break
    return {"schema": PREVIEW_SCHEMA, "units": "mm", "dxf": rel, "dxf_sha256": sha256_file(dxf),
            "layers": [name for name, _ in sorted(layers.items(), key=lambda item: item[1])],
            "paths": paths, "points": total, "truncated": truncated, "skipped": skipped,
            "bbox": [*low, *high] if paths else None,
            "flatten_mm": PREVIEW_FLATTEN_MM}


def collect(attempt: Path, out: Path, inventory: dict[str, Any], exit_code: int,
            log_text: str) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    """Перенос опубликованных worker'ом файлов в out/ с гейтами. Возвращает статус, ошибку, страницы."""
    if list(attempt.rglob("*.dwg")):
        raise RunnerError(EXIT_ENGINE, "gate_violation", "движок выдал DWG")
    events_path = attempt / "events.json"
    events = json.loads(events_path.read_bytes()) if events_path.is_file() else None
    if exit_code not in (0, 1) or events is None:
        raise RunnerError(EXIT_ENGINE, "engine_crashed", f"worker завершился кодом {exit_code}")
    titles = {row["pdf_page"]: row for row in inventory["pages"]}
    pages: dict[int, dict[str, Any]] = {}
    for view in events.get("views", []):
        page = int(view["page"])
        entry = pages.setdefault(page, {"index": quantor_index(page), "legacy_pdf_page": page,
                                        "intake_selected": bool(titles.get(page, {}).get("selected")),
                                        "views": []})
        entry["views"].append({"view": int(view["view"]), "status": view["status"],
                               "stage": view.get("stage", ""), "scale_status": None,
                               "scale_source": None, "scale_deviation": None,
                               "files": [], "dxf": None})
    if events["status"] == "needs_review" and exit_code == 0:
        published = [item["path"] for item in events.get("artifacts", [])]
        for rel in published:
            match = VIEW_DIR.match(rel)
            if not match or match.group(3) not in PUBLISHED:
                raise RunnerError(EXIT_ENGINE, "gate_violation", "worker опубликовал неизвестный файл")
            page, view_no, name = int(match.group(1)), int(match.group(2)), match.group(3)
            source = (attempt / rel).resolve()
            if not source.is_relative_to(attempt.resolve()) or not source.is_file():
                raise RunnerError(EXIT_ENGINE, "gate_violation", "файл worker вне каталога попытки")
            view = next((v for v in pages.get(page, {}).get("views", []) if v["view"] == view_no), None)
            if view is None:
                raise RunnerError(EXIT_ENGINE, "gate_violation", "файл вида без события вида")
            folder = out / "views" / f"p{page:03d}_v{view_no:02d}"
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, folder / PUBLISHED[name])
            view["files"].append(f"views/{folder.name}/{PUBLISHED[name]}")
        for page_entry in pages.values():
            for view in page_entry["views"]:
                folder_rel = f"views/p{page_entry['legacy_pdf_page']:03d}_v{view['view']:02d}"
                scale_file = out / folder_rel / "scale.json"
                scale = json.loads(scale_file.read_bytes()) if scale_file.is_file() else {}
                scale = scale if isinstance(scale, dict) else {}
                view["scale_status"] = scale["status"] if isinstance(scale.get("status"), str) else None
                view["scale_source"] = scale["source"] if isinstance(scale.get("source"), str) else None
                deviation = scale.get("deviation")
                if isinstance(deviation, (int, float)) and not isinstance(deviation, bool) \
                        and math.isfinite(deviation):
                    view["scale_deviation"] = float(deviation)
                dxf = out / folder_rel / "plan_candidates.dxf"
                if view["scale_status"] == SCALE_FAILED:
                    # Калибровка человека расходится с размерными цепочками: DXF не выпускается,
                    # причина движка доходит до результата.
                    if dxf.is_file():
                        raise RunnerError(EXIT_ENGINE, "gate_violation", "DXF при отказе по масштабу")
                    view["failure_code"] = FAILURE_CALIBRATION_MISMATCH
                    view["failure_reason"] = _text(scale.get("reason"), 400) or None
                    continue
                if not dxf.is_file():
                    continue
                # DXF разрешён при passed, а при needs_review — только по калибровке человека;
                # needs_review по размерным цепочкам без калибровки оператора DXF не даёт.
                if not (view["scale_status"] == SCALE_PASSED
                        or (view["scale_status"] == SCALE_NEEDS_REVIEW
                            and view["scale_source"] == SCALE_SOURCE_OPERATOR)):
                    raise RunnerError(EXIT_ENGINE, "gate_violation", "DXF без подтверждённого масштаба")
                legacy = attempt / f"PDF_{page_entry['legacy_pdf_page']:03d}_Вид_{view['view']:02d}"
                checks_src = legacy / CHECKS_FILE
                if not checks_src.is_file():
                    raise RunnerError(EXIT_ENGINE, "gate_violation", "нет Контроль.json у DXF")
                checks = json.loads(checks_src.read_bytes())
                if any(checks.get(flag) is not False for flag in FORBIDDEN_ACTIVE):
                    raise RunnerError(EXIT_ENGINE, "gate_violation", "активен запрещённый режим движка")
                shutil.copyfile(checks_src, out / folder_rel / CHECKS_NAME)
                view["files"].append(f"{folder_rel}/{CHECKS_NAME}")
                view["dxf"] = {"file": f"{folder_rel}/plan_candidates.dxf", **_dxf_summary(dxf)}
                write_json(out / folder_rel / "preview.json",
                           _preview(dxf, f"{folder_rel}/plan_candidates.dxf"))
                view["files"].append(f"{folder_rel}/preview.json")
        has_dxf = any(v["dxf"] for p in pages.values() for v in p["views"])
        # Вид с ошибкой движка без DXF — отказ, а не «CAD не требуется»: движок публикует
        # масштаб.json и при падении вида, и завершается кодом 0 (событие needs_review).
        engine_error = any(v["status"] == "error" for p in pages.values() for v in p["views"])
        if engine_error and not has_dxf:
            return "failed", _engine_failed(log_text), sorted(
                pages.values(), key=lambda p: p["legacy_pdf_page"])
        status = "completed_requires_review" if has_dxf else "no_cad_review_required"
        return status, None, sorted(pages.values(), key=lambda p: p["legacy_pdf_page"])
    return "failed", _engine_failed(log_text), sorted(pages.values(), key=lambda p: p["legacy_pdf_page"])


def _engine_failed(log_text: str) -> dict[str, Any]:
    error: dict[str, Any] = {"code": "engine_failed", "message": "движок не выдал пригодных результатов"}
    if FILL_ONLY_SIGNATURE in log_text:
        # Известное ограничение: калиброванный лист без чёрных штрихов в области — PDFContext.
        error["known_limitation"] = "pdfcontext_empty_black_stroke_index"
    return error


def write_manifest(out: Path, base: dict[str, Any]) -> None:
    files = []
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = path.relative_to(out).as_posix()
        if rel != "manifest.json":
            files.append({"name": rel, "sha256": sha256_file(path), "size": path.stat().st_size})
    write_json(out / "manifest.json", {"schema": MANIFEST_SCHEMA, **base, "files": files})


@contextlib.contextmanager
def _timer() -> Iterator[dict[str, float]]:
    started = time.monotonic()
    box: dict[str, float] = {}
    try:
        yield box
    finally:
        box["total"] = round(time.monotonic() - started, 3)


def run(args: argparse.Namespace) -> int:
    out: Path = args.out
    work: Path = args.work
    for directory in (out, work):
        if not directory.is_dir() or any(directory.iterdir()):
            print(json.dumps({"error": "out и work должны быть существующими пустыми каталогами"}))
            return EXIT_PARAMS
    pins = load_pins()
    base: dict[str, Any] = {"runner": runner_identity(pins), "engine": None, "input": None,
                            "params_sha256": None, "environment": None}
    report: dict[str, Any] = {"schema": REPORT_SCHEMA, "status": "failed", "error": None, "pages": [],
                              "page_numbering": {"quantor": "page_index с 0",
                                                 "legacy_worker": "pdf_page с 1 (= index + 1)"},
                              "disabled": ["finishes", "schedules"]}
    exit_code = EXIT_ENGINE
    progress = Progress(args.progress)
    with _timer() as timings:
        try:
            progress.phase("verify", "Проверка окружения и SHA-закреплённого архива движка")
            base["environment"] = check_environment(pins)
            base["engine"] = verify_archive(args.archive, pins, args.expect_archive_sha256)
            raw_params = args.params.read_bytes()
            base["params_sha256"] = hashlib.sha256(raw_params).hexdigest()
            params = parse_params(raw_params)
            source_sha = sha256_file(args.input)
            base["input"] = {"sha256": source_sha, "size": args.input.stat().st_size}

            engine_root = work / "engine"
            extract_archive(args.archive, engine_root, pins)
            # Legacy route: каталог оператора внутри распакованного проекта (как в smoke.py).
            operator = engine_root / "АР_Обработка" / "_quantor_attempt"
            job_dir = operator / "jobs" / "job"
            attempt = job_dir / "attempt-1"
            attempt.mkdir(parents=True, mode=0o700)
            shutil.copyfile(args.input, job_dir / "input.pdf")

            progress.phase("intake", "Входной контроль PDF: читаемость, шифрование, перечень листов")
            inventory = intake(engine_root, pins, job_dir / "input.pdf")
            base["input"].update(pages=inventory["page_count"])
            selected = [row["pdf_page"] for row in inventory["pages"] if row["selected"]]
            # Лист выбирает человек; перечень входного контроля — лишь подсказка intake_selected.
            if any(index >= inventory["page_count"] for index in params["pages"]):
                raise RunnerError(EXIT_PARAMS, "pages_out_of_range", "страница вне PDF")
            pages = [legacy_page(index) for index in params["pages"]]
            if len(pages) > params["limits"]["max_pages"]:
                raise RunnerError(EXIT_LIMIT, "limit_exceeded", "превышено число страниц")
            write_json(job_dir / "job.json", job_document(pages, params))
            progress.phase("worker", f"Движок обрабатывает листы: {len(pages)}",
                           pages={"total": inventory["page_count"],
                                  "planned": [quantor_index(p) for p in selected],
                                  "requested": [quantor_index(p) for p in pages]})
            log_path = work / "worker.log"
            code = run_worker(engine_root, operator, job_dir, attempt, pages, params["limits"],
                              log_path, progress)
            progress.phase("collect", "Гейты выпуска: состав файлов, масштаб, аудит DXF")
            if sha256_file(job_dir / "input.pdf") != source_sha:
                raise RunnerError(EXIT_ENGINE, "gate_violation", "worker изменил входной PDF")
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            status, error, page_rows = collect(attempt, out, inventory, code, log_text)
            report.update(status=status, error=error, pages=page_rows,
                          requested_pages=[{"index": quantor_index(p), "legacy_pdf_page": p}
                                           for p in pages],
                          worker_exit_code=code)
            exit_code = EXIT_OK if status != "failed" else EXIT_ENGINE
        except RunnerError as error:
            # Ни одного частичного файла при отказе: out/ очищается, остаются отчёт и манифест.
            for child in out.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            report.update(status="failed", error={"code": error.code, "message": error.message},
                          pages=[])
            exit_code = error.exit_code
            progress.phase("failed", error.message, error={"code": error.code})
    report["timings_s"] = timings
    report.update({key: base[key] for key in ("runner", "engine", "input", "params_sha256")})
    write_json(out / "report.json", report)
    write_manifest(out, {**base, "status": report["status"]})
    if exit_code == EXIT_OK or progress.state["phase"] != "failed":
        progress.phase("finished", report["status"],
                       error={"code": (report["error"] or {}).get("code")} if report["error"] else None)
    print(json.dumps({"status": report["status"], "error": report["error"], "exit": exit_code},
                     ensure_ascii=False))
    return exit_code


def verify(args: argparse.Namespace) -> int:
    pins = load_pins()
    try:
        result = {"runner": runner_identity(pins), "environment": check_environment(pins),
                  "engine": verify_archive(args.archive, pins, args.expect_archive_sha256)}
    except RunnerError as error:
        print(json.dumps({"error": {"code": error.code, "message": error.message}},
                         ensure_ascii=False))
        return error.exit_code
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


FIXTURES = {"calibrated": {"dimensions": True, "linework": True},
            "scale_only": {"dimensions": False, "linework": True},
            "fill_only": {"dimensions": True, "linework": False}}


def fixture(args: argparse.Namespace) -> int:
    """Синтетический PDF штатным генератором архива (smoke.make_pdf); код в git не копируется."""
    import tempfile

    pins = load_pins()
    try:
        check_environment(pins)
        verify_archive(args.archive, pins, None)
    except RunnerError as error:
        print(json.dumps({"error": {"code": error.code, "message": error.message}}, ensure_ascii=False))
        return error.exit_code
    with tempfile.TemporaryDirectory(prefix="quantor-cad-fixture-") as tmp:
        root = Path(tmp) / "engine"
        extract_archive(args.archive, root, pins)
        sys.path.insert(0, str(root))
        try:
            import smoke
        finally:
            sys.path.remove(str(root))
        smoke.make_pdf(args.out, **FIXTURES[args.kind])
    print(json.dumps({"fixture": args.kind, "sha256": sha256_file(args.out)}))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quantor CAD engine runner")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="проверить окружение и архив движка")
    check.add_argument("--archive", type=Path, required=True)
    check.add_argument("--expect-archive-sha256")
    execute = commands.add_parser("run", help="одна попытка преобразования PDF → DXF")
    for name in ("--archive", "--input", "--params", "--work", "--out"):
        execute.add_argument(name, type=Path, required=True)
    execute.add_argument("--expect-archive-sha256")
    execute.add_argument("--progress", type=Path, default=None)
    synth = commands.add_parser("fixture", help="синтетический PDF штатным генератором архива")
    synth.add_argument("--archive", type=Path, required=True)
    synth.add_argument("--kind", choices=sorted(FIXTURES), required=True)
    synth.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Движок работает с cwd в своём каталоге: относительные пути вызывающего — к абсолютным.
    for name in ("archive", "input", "params", "work", "out", "progress"):
        value = getattr(args, name, None)
        if isinstance(value, Path):
            setattr(args, name, value.absolute())
    handlers = {"verify": verify, "run": run, "fixture": fixture}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
