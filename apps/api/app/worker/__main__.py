"""Запуск исполнителя: `python -m app.worker`.

Тот же образ и тот же код, что у API, — отличается только команда. Это и есть граница,
о которой договорились: воркер не третье приложение, а второй вход в существующее
(ADR-0015).
"""

from __future__ import annotations

import asyncio

from app.worker.runner import run_worker

if __name__ == "__main__":
    asyncio.run(run_worker())
