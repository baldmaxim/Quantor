#!/usr/bin/env bash
#
# Обновление Quantor на сервере (ADR-0032).
#
#   ./update.sh <git-sha>   # выкатить сборку конкретного коммита (так же делается откат)
#   ./update.sh             # перевыкатить текущий выпуск из файла RELEASE
#
# Тег выпуска хранится в RELEASE, а не в .env: .env заполняет владелец, скрипт его не
# меняет. Ручные команды compose — через ./compose.sh, он берёт тег оттуда же.
#
# Порядок: скачать образы → сверить описание развёртывания с образом → бакет → миграции →
# перезапуск → проверка, что все контейнеры из одной сборки и API готов.
#
# docker-compose.yml руками здесь не правится: скрипт берёт его из образа API того же
# коммита. Всё, что настраивается, — в .env; в compose только имена и умолчания.
set -euo pipefail

cd "$(dirname "$0")"

TAG="${1:-$(cat RELEASE 2>/dev/null || true)}"
[ -n "$TAG" ] || { echo "Укажите выпуск: ./update.sh <git-sha>"; exit 1; }
export IMAGE_TAG="$TAG"

COMPOSE=(docker compose -p quantor)

echo "→ выкатывается ${TAG}"
# Именно pull: `up -d` не перекачивает образ, если тег уже есть на диске.
"${COMPOSE[@]}" pull minio api worker web admin

echo -n "→ описание развёртывания: "
tmp_compose="$(mktemp)"
helper="$(docker create "ghcr.io/baldmaxim/quantor-api:${TAG}" true)"
if docker cp "$helper:/app/deploy/docker-compose.yml" "$tmp_compose" 2>/dev/null; then
  if cmp -s "$tmp_compose" docker-compose.yml; then
    echo "совпадает с образом"
  else
    backup="docker-compose.yml.bak-$(date +%Y%m%d-%H%M%S)"
    cp docker-compose.yml "$backup"
    echo "разошлось, обновляю (прежнее в $backup)"
    diff -u "$backup" "$tmp_compose" | sed -n '1,40p' || true
    cp "$tmp_compose" docker-compose.yml
  fi
else
  echo "в образе нет — оставляю как есть"
fi
tmp_self="$(mktemp)"
if docker cp "$helper:/app/deploy/update.sh" "$tmp_self" 2>/dev/null && ! cmp -s "$tmp_self" "$0"; then
  # Подменять скрипт посреди его же выполнения нельзя: bash дочитывает файл по ходу.
  echo "   ! update.sh в образе новее этого. Обновить после выкладки:"
  echo "     docker cp \$(docker create ghcr.io/baldmaxim/quantor-api:${TAG} true):/app/deploy/update.sh $0"
fi
docker rm -f "$helper" >/dev/null 2>&1 || true
rm -f "$tmp_compose" "$tmp_self"

# Хранилище и база должны быть подняты до миграций и бакета.
"${COMPOSE[@]}" up -d db minio

echo "→ бакет"
for _ in $(seq 1 15); do
  if "${COMPOSE[@]}" run --rm --no-deps api python -m app.cli ensure-bucket; then break; fi
  sleep 2
done

echo "→ миграции"
"${COMPOSE[@]}" --profile tools run --rm migrate

"${COMPOSE[@]}" up -d --force-recreate api worker web admin

echo "→ из чего собраны контейнеры:"
fail=0
for name in api worker web admin; do
  image="quantor-${name}"
  [ "$name" = worker ] && image="quantor-api"
  want="ghcr.io/baldmaxim/${image}:${TAG}"
  got="$(docker inspect "quantor-${name}" --format '{{.Config.Image}}')"
  printf '   %-16s %s\n' "quantor-${name}" "$got"
  [ "$got" = "$want" ] || { echo "   ✗ ожидался $want"; fail=1; }
done

echo -n "→ готовность API: "
state="нет ответа"
for _ in $(seq 1 30); do
  if docker exec quantor-api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).status == 200 else 1)" 2>/dev/null; then
    state="готов"
    break
  fi
  sleep 2
done
echo "$state"
[ "$state" = готов ] || fail=1

[ "$fail" = 0 ] || { echo; echo "ВЫКЛАДКА НЕ ЧИСТАЯ — смотрите выше; RELEASE не изменён"; exit 1; }
# Выпуск фиксируется только после чистой выкладки: ./compose.sh и следующий ./update.sh
# без аргумента берут его отсюда.
echo "$TAG" > RELEASE
echo
echo "готово: ${TAG}"
