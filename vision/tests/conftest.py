from __future__ import annotations

import importlib.util

# Тесты обучения требуют torch; в CI и в окружении без extras они не собираются вовсе.
collect_ignore = [] if importlib.util.find_spec("torch") else ["test_slab.py"]
