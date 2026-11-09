"""Запуск: `python -m app.cad_worker` (образ `quantor-cad-worker`, ADR-0036).

Исполнитель стартует, если движок сконфигурирован (`CAD_ENGINE_PYTHON`, `CAD_ENGINE_RUNNER`,
`CAD_ENGINE_ARCHIVE`). Перед циклом заданий runner проверяет окружение движка, SHA архива,
манифест и каждый файл; при отказе исполнитель не стартует и выходит с кодом != 0.
"""

from __future__ import annotations

import asyncio
import json

from app.cad_worker import HANDLERS
from app.cad_worker.handler import CadError, verify_engine
from app.core.config import get_settings
from app.worker.runner import run_worker


def main() -> None:
    settings = get_settings()
    try:
        identity = asyncio.run(verify_engine(settings))
    except CadError as failure:
        raise SystemExit(f"{failure.code.value}: {failure.message}") from failure
    print(json.dumps({"cad_engine": identity["engine"], "runner": identity["runner"]}))
    asyncio.run(run_worker(settings, HANDLERS))


if __name__ == "__main__":
    main()
