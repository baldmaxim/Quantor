"""Детерминированные отпечатки: канонический JSON без меток времени."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_sha256(payload: Any) -> str:
    """Отпечаток структуры: ключи отсортированы, разделители фиксированы, UTF-8."""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
