#!/usr/bin/env bash
# Окружение читателя: plangeom (чтение PDF) + pypdfium2 и Pillow (растр для разметки).
# plangeom не входит в зависимости проекта: только в этом изолированном окружении (.venv-reader, вне git).
# Использование: ./setup_reader_env.sh [python]   (по умолчанию python3; при сбое сборки pydantic — python3.12)
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="${1:-python3}"

"$PYTHON" -m venv .venv-reader
.venv-reader/bin/python -m pip install --upgrade pip
.venv-reader/bin/python -m pip install "plangeom==0.1.0a2" pydantic pypdfium2 pillow
.venv-reader/bin/python -c "import importlib.metadata as m; print('plangeom', m.version('plangeom'))"
echo "Готово: .venv-reader. Запуск: PYTHONPATH=. .venv-reader/bin/python -m building_model <команда>"
