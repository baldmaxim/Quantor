#!/usr/bin/env bash
#
# docker compose для Quantor с тегом текущего выпуска.
#
# Тег живёт в файле RELEASE, а не в .env: в .env — только значения, которые владелец
# вписывает руками, и скрипты его не трогают. RELEASE пишет update.sh после выкладки.
#
#   ./compose.sh ps
#   ./compose.sh logs --tail 100 api
#   ./compose.sh run --rm api python -m app.cli create-admin --email <почта>
set -euo pipefail

cd "$(dirname "$0")"
IMAGE_TAG="$(cat RELEASE 2>/dev/null || true)"
[ -n "$IMAGE_TAG" ] || { echo "Выпуска нет: сначала ./update.sh <git-sha>"; exit 1; }
export IMAGE_TAG
exec docker compose -p quantor "$@"
