"""Запуск: `python -m app.cad_worker` (только ENVIRONMENT=local|test и CAD_QA_ENABLED=true).

Перед циклом заданий runner проверяет окружение движка, SHA архива, манифест и каждый файл;
при отказе исполнитель не стартует.
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
    if not settings.cad_qa_enabled:
        raise SystemExit("CAD_QA_ENABLED=false: исполнитель PDF -> CAD выключен")
    try:
        identity = asyncio.run(verify_engine(settings))
    except CadError as failure:
        raise SystemExit(f"{failure.code.value}: {failure.message}") from failure
    print(json.dumps({"cad_engine": identity["engine"], "runner": identity["runner"]}))
    asyncio.run(run_worker(settings, HANDLERS))


if __name__ == "__main__":
    main()
