"""Ход попыток PDF -> CAD: снимки runner, упорядоченные события и история попыток.

Источник — файл `--progress` runner (`quantor.cad_engine.progress.v1`), куда тот переносит
этапы, которые штатный worker движка сам пишет в `events.json`, и свои фазы. Исполнитель
читает снимок, сверяет его с предыдущим и дописывает события в `payload.cad_attempts` задания.
Номера событий — свои у каждой попытки и строго растут; снимок со старым `seq` отбрасывается.
Прогресс по таймеру не досчитывается: событие есть только там, где движок что-то записал.

Хранение в `payload` задания (JSONB), а не в отдельной таблице: QA-контур не добавляет
миграцию в общую схему (ADR-0035 не снят). Объём ограничен `MAX_EVENTS_PER_ATTEMPT`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final

PROGRESS_SCHEMA: Final = "quantor.cad_engine.progress.v1"
STAGE_KEYS: Final = ("source", "regions", "scale", "geometry", "assemblies", "checks", "export")
STAGE_STATES: Final = frozenset({"running", "done", "needs_review", "error", "unknown"})
VIEW_STATES: Final = frozenset({"queued", "running", "done", "needs_review", "error", "unknown"})
ENGINE_STATES: Final = frozenset({"running", "needs_review", "error", "unknown"})
# Фазы runner и исполнителя Quantor. Порядок — порядок работы попытки.
PHASES: Final = (
    "claimed",
    "download",
    "starting",
    "verify",
    "intake",
    "worker",
    "collect",
    "finished",
    "failed",
    "publish",
    "published",
)
MAX_EVENTS_PER_ATTEMPT: Final = 1000
MAX_PHASES: Final = 32
MAX_PROGRESS_BYTES: Final = 4 * 1024 * 1024
_TEXT_LIMIT: Final = 240


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _text(value: Any) -> str:
    return value[:_TEXT_LIMIT] if isinstance(value, str) else ""


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return round(float(value), 3)


# ------------------------------------------------------------------ разбор снимка


def parse_snapshot(raw: bytes) -> dict[str, Any] | None:
    """Снимок runner в проверенном виде или None. Runner доверенный, но вход сверяется заново."""
    if len(raw) > MAX_PROGRESS_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != PROGRESS_SCHEMA:
        return None
    seq = _int(data.get("seq"))
    phase = data.get("phase")
    if seq is None or phase not in PHASES:
        return None
    views: list[dict[str, Any]] = []
    for item in _as_list(data.get("views")):
        view = _view(item)
        if view is not None:
            views.append(view)
    engine = data.get("engine") if isinstance(data.get("engine"), dict) else None
    error = data.get("error") if isinstance(data.get("error"), dict) else None
    pages = data.get("pages") if isinstance(data.get("pages"), dict) else None
    phases = [
        {"phase": row["phase"], "detail": _text(row.get("detail"))}
        for row in _as_list(data.get("phases"))[:MAX_PHASES]
        if isinstance(row, dict) and row.get("phase") in PHASES
    ]
    return {
        "seq": seq,
        "phase": phase,
        "phase_detail": _text(data.get("phase_detail")),
        "phases": phases,
        "pages": _pages(pages),
        "engine": None
        if engine is None
        else {
            "status": engine.get("status") if engine.get("status") in ENGINE_STATES else "unknown",
            "stage": _text(engine.get("stage")),
            "error": _text(engine.get("error")) or None,
        },
        "error_code": (_text(error.get("code")) or None) if error else None,
        "views": views,
    }


def _pages(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    total = _int(raw.get("total"))

    def indexes(key: str) -> list[int]:
        values = raw.get(key)
        return [v for v in values if _int(v) is not None] if isinstance(values, list) else []

    return {"total": total, "planned": indexes("planned"), "requested": indexes("requested")}


def _view(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    index, page, view = _int(item.get("index")), _int(item.get("legacy_pdf_page")), item.get("view")
    if index is None or page is None or _int(view) is None or page != index + 1:
        return None
    stages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in _as_list(item.get("stages")):
        if not isinstance(step, dict) or step.get("key") not in STAGE_KEYS:
            continue
        key = str(step["key"])
        if key in seen:
            continue
        seen.add(key)
        completed, total = _int(step.get("completed")), _int(step.get("total"))
        stages.append(
            {
                "key": key,
                "status": step.get("status") if step.get("status") in STAGE_STATES else "unknown",
                "elapsed_s": _number(step.get("elapsed_s")),
                "completed": completed if total is not None else None,
                "total": total if completed is not None else None,
                "detail": _text(step.get("detail")) or None,
            }
        )
    return {
        "index": index,
        "legacy_pdf_page": page,
        "view": view,
        "status": item.get("status") if item.get("status") in VIEW_STATES else "unknown",
        "stage": _text(item.get("stage")),
        "ready": item.get("ready") is True,
        "stages": stages,
    }


# ------------------------------------------------------------------ события


def _diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    """События между двумя снимками. Ничего не придумывает: только то, что изменилось."""
    events: list[dict[str, Any]] = []
    # Фазы runner — по его истории: каждая фаза дойдёт событием, даже если сменилась между
    # опросами. Снимок без истории (старый runner) — по текущей фазе.
    seen = len((previous or {}).get("phases", []))
    phases = current["phases"][seen:] or (
        [{"phase": current["phase"], "detail": current["phase_detail"]}]
        if previous is None or previous["phase"] != current["phase"]
        else []
    )
    for row in phases:
        events.append(
            {
                "scope": "document",
                "phase": row["phase"],
                "status": "error" if row["phase"] == "failed" else "running",
                "detail": row["detail"] or None,
            }
        )
    before = {(v["index"], v["view"]): v for v in (previous or {}).get("views", [])}
    for view in current["views"]:
        old = before.get((view["index"], view["view"]))
        where = {
            "scope": "view",
            "page_index": view["index"],
            "legacy_pdf_page": view["legacy_pdf_page"],
            "view": view["view"],
        }
        if old is None or (old["status"], old["stage"]) != (view["status"], view["stage"]):
            events.append({**where, "status": view["status"], "detail": view["stage"] or None})
        old_stages = {s["key"]: s for s in (old or {}).get("stages", [])}
        for stage in view["stages"]:
            prior = old_stages.get(stage["key"])
            fields = ("status", "detail", "completed", "total")
            if prior is None or any(prior[f] != stage[f] for f in fields):
                events.append(
                    {
                        **where,
                        "stage": stage["key"],
                        "status": stage["status"],
                        "detail": stage["detail"],
                        "elapsed_s": stage["elapsed_s"],
                        "completed": stage["completed"],
                        "total": stage["total"],
                    }
                )
    return events


def attempts_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("cad_attempts")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def attempt_record(payload: dict[str, Any], attempt: int) -> dict[str, Any] | None:
    return next((row for row in attempts_of(payload) if row.get("attempt") == attempt), None)


def _replace(payload: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in attempts_of(payload) if row.get("attempt") != record["attempt"]]
    rows.append(record)
    rows.sort(key=lambda row: int(row["attempt"]))
    return {**payload, "cad_attempts": rows}


def _append(record: dict[str, Any], events: list[dict[str, Any]], at: datetime) -> None:
    for event in events:
        if len(record["events"]) >= MAX_EVENTS_PER_ATTEMPT:
            record["events_dropped"] = int(record.get("events_dropped", 0)) + 1
            continue
        record["last_seq"] = int(record["last_seq"]) + 1
        record["events"].append(
            {"seq": record["last_seq"], "at": _iso(at), "attempt": record["attempt"], **event}
        )


def begin_attempt(payload: dict[str, Any], attempt: int, at: datetime) -> dict[str, Any]:
    """Новая попытка с чистым ходом. Записи прежних попыток не трогаются."""
    record: dict[str, Any] = {
        "attempt": attempt,
        "started_at": _iso(at),
        "finished_at": None,
        "outcome": None,
        "error_code": None,
        "result_status": None,
        "runner_seq": 0,
        "snapshot": None,
        "events": [],
        "events_dropped": 0,
        "last_seq": 0,
    }
    _append(
        record,
        [{"scope": "document", "phase": "claimed", "status": "running", "detail": None}],
        at,
    )
    return _replace(payload, record)


def phase_event(
    payload: dict[str, Any], attempt: int, phase: str, detail: str | None, at: datetime
) -> dict[str, Any]:
    """Фаза самого исполнителя Quantor (загрузка PDF, публикация артефактов)."""
    record = attempt_record(payload, attempt)
    if record is None or record.get("finished_at") is not None:
        return payload
    record = {**record, "events": list(record["events"])}
    _append(
        record, [{"scope": "document", "phase": phase, "status": "running", "detail": detail}], at
    )
    return _replace(payload, record)


def apply_snapshot(
    payload: dict[str, Any], attempt: int, snapshot: dict[str, Any], at: datetime
) -> tuple[dict[str, Any], int]:
    """Применяет снимок runner. Возвращает новый payload и число новых событий."""
    record = attempt_record(payload, attempt)
    if record is None or record.get("finished_at") is not None:
        return payload, 0
    if snapshot["seq"] <= int(record.get("runner_seq", 0)):
        return payload, 0  # устаревший или повторный снимок
    events = _diff(record.get("snapshot"), snapshot)
    record = {**record, "events": list(record["events"]), "runner_seq": snapshot["seq"]}
    record["snapshot"] = snapshot
    _append(record, events, at)
    return _replace(payload, record), len(events)


def finish_attempt(
    payload: dict[str, Any],
    attempt: int,
    at: datetime,
    *,
    outcome: str,
    error_code: str | None = None,
    result_status: str | None = None,
) -> dict[str, Any]:
    record = attempt_record(payload, attempt)
    if record is None:
        return payload
    record = {**record, "events": list(record["events"])}
    _append(
        record,
        [
            {
                "scope": "document",
                "phase": "published" if outcome == "succeeded" else "failed",
                "status": "done" if outcome == "succeeded" else "error",
                "detail": result_status or error_code,
            }
        ],
        at,
    )
    record.update(
        finished_at=_iso(at), outcome=outcome, error_code=error_code, result_status=result_status
    )
    return _replace(payload, record)
