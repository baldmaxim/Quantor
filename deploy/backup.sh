#!/usr/bin/env bash
#
# Ежедневная копия базы Quantor: pg_dump в сжатый файл рядом с порталом, хранится 7 дней.
# Ставится в cron на сервере — см. deploy/README.md.
#
# Файлы MinIO этим скриптом не копируются: в тестовом режиме они живут на том же диске,
# и потеря диска означает потерю документов (ADR-0032). Перед реальной работой —
# управляемое хранилище или отдельная копия бакета.
set -euo pipefail

dir="$(cd "$(dirname "$0")" && pwd)/backups"
mkdir -p "$dir"
file="$dir/quantor-$(date +%Y%m%d-%H%M).sql.gz"

docker exec quantor-db pg_dump -U quantor --no-owner quantor | gzip > "$file.part"
mv "$file.part" "$file"
find "$dir" -name 'quantor-*.sql.gz' -mtime +7 -delete
