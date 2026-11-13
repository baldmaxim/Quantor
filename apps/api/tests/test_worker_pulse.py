"""Отметка жизни исполнителя в цикле: без базы, на подменённых сервисах.

Регрессия боевого стенда (2026-11-13): отметка `workers.heartbeat_at` ставилась только при
захвате и после выполнения задания. Живой исполнитель без заданий через порог молчания
выглядел в `/health/ready` молчащим, а через десять порогов сборщик удалял его запись, и
готовность писала «исполнитель ни разу не запускался». CAD-исполнитель (`app.cad_worker`)
идёт тем же `Worker.run` со своим реестром, поэтому проверка общая.

Здесь проверяется проводка цикла — что простаивающий исполнитель отмечается сам и что
отметка гаснет до снятия с учёта. Что именно пишется в базу, проверяют тесты захвата.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import TracebackType

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import JobType
from app.models import Job
from app.services import jobs as jobs_service
from app.services import workers as workers_service
from app.storage.base import ObjectStorage
from app.worker import runner
from tests.conftest import clean_settings

# Сколько отметок ждать. Две подряд без единого захвата — уже не случайность первого удара.
BEATS = 3
# Предел ожидания: отметка идёт раз в сотые доли секунды, пять секунд — только от зависания.
DEADLINE_SECONDS = 5.0


class _FakeSession:
    """Сессия-пустышка: все запросы цикла подменены, базе здесь нечего делать."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _fake_factory() -> Callable[[], _FakeSession]:
    return _FakeSession


async def _never_called(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    raise AssertionError("в пустой очереди задание не выполняется")


def _quick_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Интервал пульса — свойство (треть аренды, не меньше секунды); тест ждать секунды не
    # должен, поэтому интервал подменяется на классе на время теста.
    monkeypatch.setattr(Settings, "worker_heartbeat_interval_seconds", property(lambda _self: 0.01))
    return clean_settings(worker_poll_interval_seconds=0.01)


class _Journal:
    """Порядок обращений цикла к учёту исполнителей и очереди."""

    def __init__(self, *, failing_touches: int = 0) -> None:
        self.events: list[str] = []
        self.beaten = asyncio.Event()
        self._failing_touches = failing_touches

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def register(session: object, **_: object) -> None:
            self.events.append("register")

        async def touch(session: object, *, worker_id: str) -> bool:
            if self._failing_touches > 0:
                self._failing_touches -= 1
                self.events.append("touch_failed")
                raise ConnectionError("база недоступна")
            self.events.append("touch")
            if self.events.count("touch") >= BEATS:
                self.beaten.set()
            return True

        async def unregister(session: object, *, worker_id: str) -> None:
            self.events.append("unregister")

        async def claim(session: object, **_: object) -> None:
            self.events.append("claim")

        async def dispose() -> None:
            return None

        monkeypatch.setattr(runner, "get_worker_session_factory", _fake_factory)
        monkeypatch.setattr(runner, "dispose_worker_engine", dispose)
        monkeypatch.setattr(workers_service, "register", register)
        monkeypatch.setattr(workers_service, "touch", touch)
        monkeypatch.setattr(workers_service, "unregister", unregister)
        monkeypatch.setattr(jobs_service, "claim", claim)


async def _run_until_beaten(worker: runner.Worker, journal: _Journal) -> None:
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(journal.beaten.wait(), timeout=DEADLINE_SECONDS)
    finally:
        worker.request_stop()
        await asyncio.wait_for(task, timeout=DEADLINE_SECONDS)


async def test_idle_worker_marks_itself_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустая очередь, ни одного захвата — а отметки идут по таймеру."""
    journal = _Journal()
    journal.install(monkeypatch)
    worker = runner.Worker(
        _quick_settings(monkeypatch), handlers={JobType.LEGACY_IMPORT: _never_called}
    )

    await _run_until_beaten(worker, journal)

    assert journal.events[0] == "register"
    assert journal.events.count("touch") >= BEATS
    assert "claim" in journal.events, "очередь опрашивалась, но была пуста"
    # Отметка погашена до снятия с учёта: удар после `unregister` вернул бы
    # остановленного исполнителя в список живых.
    assert journal.events[-1] == "unregister"
    assert journal.events.count("unregister") == 1


async def test_failed_beat_does_not_stop_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Недоступная на миг база — не повод замолчать навсегда: следующий удар проходит."""
    journal = _Journal(failing_touches=2)
    journal.install(monkeypatch)
    worker = runner.Worker(
        _quick_settings(monkeypatch), handlers={JobType.LEGACY_IMPORT: _never_called}
    )

    await _run_until_beaten(worker, journal)

    assert journal.events.count("touch_failed") == 2
    first_success = journal.events.index("touch")
    assert journal.events.index("touch_failed") < first_success
    assert journal.events.count("touch") >= BEATS
    assert journal.events[-1] == "unregister"
