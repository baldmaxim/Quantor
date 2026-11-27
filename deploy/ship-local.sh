#!/usr/bin/env bash
#
# Выкатка Quantor без GitHub Actions и GHCR: образы собираются на этой машине, передаются на
# сервер по ssh, затем `update.sh` выкатывает их без скачивания.
#
# Дёшево для мелких правок: страницы (web, admin) не пересобираются, если с выпуска на сервере не
# менялось ничего из того, что копирует их образ, - новый тег вешается на прежний образ; тяжёлые
# пакеты cad-worker собираются отдельной стадией и берутся из кэша; на сервер уходит одним архивом
# только то, что изменилось (rsync сверяет его с архивом прошлой выкатки). После выкатки - пилотные
# настройки cad-worker (compose.pilot.ui.yml, если он есть на сервере) и уборка старых образов: здесь
# остаются этот и прошлый выпуск, на сервере - последние QUANTOR_KEEP_RELEASES (5) для отката.
#
# Статичные основы (пакеты API: `quantor-api-deps:<хеш>`; SSH-клиент и venv движка CAD: `quantor-cad-base:<хеш>`)
# собираются отдельно и только если образа с таким хешем входов ещё нет; образы api и cad-worker строятся
# поверх них, поэтому обычная правка кода пересобирает лишь верхние слои. Основы - локальные теги, в GHCR
# и на сервер как отдельные образы не уходят (их слои едут внутри api и cad-worker).
#
#   deploy/ship-local.sh [<git-ref>]      # по умолчанию origin/main
#   deploy/ship-local.sh --build-only [<git-ref>]
#
# Сборка повторяет publish.yml: тот же набор образов, теги `ghcr.io/baldmaxim/<образ>:<полный sha>`
# (по ним update.sh сверяет контейнеры), те же build-args. Исходники берутся из чистых git worktree:
# незакоммиченные правки рабочей копии в образ не попадают. Движок CAD и генераторы — из репозитория
# CAD_engine по tools/cad_engine/pins.json со сверкой sha256.
#
# Окружение: QUANTOR_SSH (по умолчанию suvpn — боевой сервер с 2026-11-13, ADR-0046), CAD_ENGINE_REPO (по умолчанию ../CAD_engine),
# QUANTOR_PUBLIC_ORIGIN, QUANTOR_ADMIN_ORIGIN; QUANTOR_REBUILD_ALL=1 - собрать все образы заново;
# QUANTOR_PREV=<sha> - с чем сравнивать (по умолчанию выпуск на сервере, RELEASE); QUANTOR_KEEP_RELEASES;
# QUANTOR_PILOT_OVERLAY=0 - не трогать cad-worker после выкатки. Образов этой сборки в GHCR нет:
# повторить выкладку того же sha можно только этим скриптом.
set -euo pipefail

BUILD_ONLY=0
if [ "${1:-}" = "--build-only" ]; then BUILD_ONLY=1; shift; fi
REF="${1:-origin/main}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_REPO="${CAD_ENGINE_REPO:-$ROOT/../CAD_engine}"
SSH_HOST="${QUANTOR_SSH:-suvpn}"
PUBLIC_ORIGIN="${QUANTOR_PUBLIC_ORIGIN:-https://quantor.meridianai.ru}"
ADMIN_ORIGIN="${QUANTOR_ADMIN_ORIGIN:-https://admin.quantor.meridianai.ru}"
REG=ghcr.io/baldmaxim
REMOTE_DIR=/opt/portals/quantor
# Архив прошлой выкатки на сервере: основа для передачи дельтой.
REMOTE_SHIP=/var/tmp/quantor-ship
KEEP_RELEASES="${QUANTOR_KEEP_RELEASES:-5}"
remote() { ssh -n -o LogLevel=ERROR "$SSH_HOST" "$@"; }

git -C "$ROOT" fetch -q origin
SHA="$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")"
echo "→ сборка ${SHA}"

WORK="$(mktemp -d)"
WT="$WORK/quantor"
EWT="$WORK/engine"
cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  git -C "$ENGINE_REPO" worktree remove --force "$EWT" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# Выписка байт-в-байт, как в репозитории, при любом локальном `core.autocrlf`. На Windows он обычно
# `true`, а в CAD_engine нет `.gitattributes`: файлы движка получали CRLF, сверка sha256 параметров
# генераторов с pins.json падала, а образ собрался бы из файлов, которых нет в git.
checkout() { git -c core.autocrlf=false -C "$1" worktree add -q --detach "$2" "$3"; }

checkout "$ROOT" "$WT" "$SHA"

PINS="$WT/tools/cad_engine/pins.json"
pin() { jq -er "$1" "$PINS"; }
ENGINE_REF="$(pin .engine.repo_ref)"
ARCHIVE_PATH="$(pin .engine.archive_path)"
ARCHIVE_SHA="$(pin .engine.archive_sha256)"
git -C "$ENGINE_REPO" cat-file -e "${ENGINE_REF}^{commit}" 2>/dev/null \
  || git -C "$ENGINE_REPO" fetch -q origin "$ENGINE_REF"
checkout "$ENGINE_REPO" "$EWT" "$ENGINE_REF"

echo "→ движок CAD ${ENGINE_REF:0:7} (сверка sha256)"
mkdir -p "$WT/deploy/cad-engine/generators"
cp "$EWT/$ARCHIVE_PATH" "$WT/deploy/cad-engine/engine.zip"
echo "$ARCHIVE_SHA  $WT/deploy/cad-engine/engine.zip" | sha256sum -c --quiet -
for name in cad_mep cad_walls cad_eom cad_facades cad_model; do
  [ -d "$EWT/generators/$name" ] || { echo "В движке нет generators/$name"; exit 1; }
  cp -r "$EWT/generators/$name" "$WT/deploy/cad-engine/generators/$name"
  rm -rf "$WT/deploy/cad-engine/generators/$name/tests"
  expected="$(pin ".generators.$name.params_sha256")"
  actual="$(sha256sum "$EWT/$(pin ".generators.$name.params_path")" | cut -d' ' -f1)"
  [ "$actual" = "$expected" ] || { echo "Параметры $name ($actual) не совпали с pins.json ($expected)"; exit 1; }
done

next_args=(
  --build-arg "NEXT_PUBLIC_API_BASE_URL=$PUBLIC_ORIGIN"
  --build-arg "NEXT_PUBLIC_PORTAL_URL=$PUBLIC_ORIGIN"
  --build-arg "NEXT_PUBLIC_ADMIN_URL=$ADMIN_ORIGIN"
  --build-arg "NEXT_PUBLIC_BUILD_VERSION=$SHA"
)
# С чем сравнивать: выпуск на сервере (при --build-only - только если задан QUANTOR_PREV).
PREV="${QUANTOR_PREV:-}"
if [ -z "$PREV" ] && [ "$BUILD_ONLY" = 0 ]; then
  PREV="$(remote "cat $REMOTE_DIR/RELEASE 2>/dev/null" || true)"
fi
# Адреса, вшитые в сборку страниц: другие адреса - другой образ, прежний не годится.
NEXT_ARGS_ID="$(printf '%s\n' "$PUBLIC_ORIGIN" "$ADMIN_ORIGIN" | sha256sum | cut -c1-16)"

build() { echo "→ образ $1"; docker build -q -f "$WT/$2" "${@:3}" -t "$REG/$1:$SHA" "$WT" >/dev/null; }

# Статичные основы. Хеш считается по файлам выписки $WT (не по рабочей копии, где бывают чужие правки):
# Dockerfile целиком, манифесты и lock-файлы, образ python. Образ с таким тегом есть - берём его.
# Основа cad-base хешируется по слоям образа api-deps (ID образа не годится: в нём время сборки), а не по
# его тегу: она меняется, только если реально поменялись пакеты API.
PYTHON_IMAGE="${QUANTOR_PYTHON_IMAGE:-python:3.12-slim}"
PYTHON_ID="$(docker image inspect -f '{{.Id}}' "$PYTHON_IMAGE" 2>/dev/null || echo "$PYTHON_IMAGE")"
base_hash() { { echo "$1"; shift; cat "$@"; } | sha256sum | cut -c1-12; }
API_DEPS="quantor-api-deps:$(base_hash "$PYTHON_ID" "$WT/deploy/Dockerfile.api" "$WT/apps/api/pyproject.toml")"
if docker image inspect "$API_DEPS" >/dev/null 2>&1; then
  echo "→ основа $API_DEPS: есть"
else
  echo "→ основа $API_DEPS: сборка (пакеты API)"
  docker build -q -f "$WT/deploy/Dockerfile.api" --target api-deps -t "$API_DEPS" "$WT" >/dev/null
fi
CAD_BASE="quantor-cad-base:$(base_hash "$(docker image inspect -f '{{json .RootFS.Layers}}' "$API_DEPS")" \
  "$WT/deploy/Dockerfile.cad-worker" "$WT/tools/cad_engine/requirements.linux-cp312.lock.txt" \
  "$WT/tools/cad_model/requirements.linux-cp312.lock.txt")"
if docker image inspect "$CAD_BASE" >/dev/null 2>&1; then
  echo "→ основа $CAD_BASE: есть"
else
  echo "→ основа $CAD_BASE: сборка (SSH-клиент, venv движка и модели)"
  docker build -q -f "$WT/deploy/Dockerfile.cad-worker" --target cad-base \
    --build-arg "API_IMAGE=$REG/quantor-api:$SHA" --build-arg "API_DEPS_IMAGE=$API_DEPS" \
    -t "$CAD_BASE" "$WT" >/dev/null
fi

# Страницы без изменений: всё, что копирует deploy/Dockerfile.next, с выпуска PREV то же, адреса те же,
# прежний образ есть здесь. Тогда новый тег на прежний образ; версия сборки в нём - PREV (код тот же).
reuse_next() {
  local app="$1" old="$REG/quantor-$1:$PREV"
  [ "${QUANTOR_REBUILD_ALL:-0}" != 1 ] && [ -n "$PREV" ] && [ "$PREV" != "$SHA" ] || return 1
  git -C "$ROOT" cat-file -e "${PREV}^{commit}" 2>/dev/null || return 1
  [ "$(docker image inspect -f '{{ index .Config.Labels "quantor.next-args" }}' "$old" 2>/dev/null)" \
    = "$NEXT_ARGS_ID" ] || return 1
  git -C "$ROOT" diff --quiet "$PREV" "$SHA" -- deploy/Dockerfile.next package.json pnpm-lock.yaml \
    pnpm-workspace.yaml .npmrc packages apps/web/package.json apps/admin/package.json "apps/$app" \
    || return 1
  docker tag "$old" "$REG/quantor-$app:$SHA"
}

build quantor-api deploy/Dockerfile.api --build-arg APP= --build-arg "API_DEPS_IMAGE=$API_DEPS" "${next_args[@]}"
for app in web admin; do
  if reuse_next "$app"; then
    echo "→ образ quantor-$app: без изменений с ${PREV:0:7}, тег на прежний образ"
  else
    build "quantor-$app" deploy/Dockerfile.next --build-arg "APP=$app" "${next_args[@]}" \
      --label "quantor.next-args=$NEXT_ARGS_ID"
  fi
done
build quantor-cad-worker deploy/Dockerfile.cad-worker \
  --build-arg "API_IMAGE=$REG/quantor-api:$SHA" --build-arg "CAD_BASE_IMAGE=$CAD_BASE" \
  --build-arg "ENGINE_ARCHIVE_SHA256=$ARCHIVE_SHA"
[ "$BUILD_ONLY" = 1 ] && { echo "собрано: ${SHA}"; exit 0; }

images=("$REG/quantor-api:$SHA" "$REG/quantor-web:$SHA" "$REG/quantor-admin:$SHA" "$REG/quantor-cad-worker:$SHA")
# Одним архивом (общие слои - один раз); rsync сверяет его с архивом прошлой выкатки на сервере и
# шлёт только изменившиеся блоки - на деле новые слои. Первая выкатка передаёт всё.
echo "→ передача образов на ${SSH_HOST} (дельтой к прошлой выкатке)"
docker save -o "$WORK/release.tar" "${images[@]}"
remote "mkdir -p $REMOTE_SHIP"
rsync --partial --timeout=900 --stats -e "ssh -o LogLevel=ERROR" \
  "$WORK/release.tar" "$SSH_HOST:$REMOTE_SHIP/release.tar" \
  | grep -E "^(Total file size|Literal data|Matched data)" | sed 's/^/   /'
rm -f "$WORK/release.tar"
remote "docker load -q -i $REMOTE_SHIP/release.tar" >/dev/null

# update.sh берётся из образа того же коммита: на сервере может лежать старый, без SKIP_PULL.
echo "→ update.sh на сервере"
ssh -o LogLevel=ERROR "$SSH_HOST" "set -e; cd $REMOTE_DIR; \
  h=\$(docker create $REG/quantor-api:$SHA true); docker cp \$h:/app/deploy/update.sh update.sh; \
  docker rm -f \$h >/dev/null; SKIP_PULL=1 bash ./update.sh $SHA"

# Новый update.sh сам подключает compose.pilot.ui.yml; шаг оставлен для серверной копии update.sh
# старше этой правки (она поднимала сервисы только из docker-compose.yml и сбрасывала пилоты ADR-0055).
if [ "${QUANTOR_PILOT_OVERLAY:-1}" = 1 ]; then
  remote "cd $REMOTE_DIR; if [ -f compose.pilot.ui.yml ]; then \
    ./compose.sh -f docker-compose.yml -f compose.pilot.ui.yml up -d --no-deps cad-worker api worker >/dev/null \
    && echo '→ пилотные настройки cad-worker, api и worker возвращены'; fi"
fi

# Уборка. Здесь - образы выпусков Quantor, кроме этого и прошлого (прошлый - для тега без пересборки
# страниц), и кэш сборки старше недели. На сервере - последние KEEP_RELEASES выпусков по времени
# сборки образа API и текущий; образ работающего контейнера docker не удалит и сам.
echo "→ уборка старых образов"
docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E "^$REG/quantor-(api|web|admin|cad-worker):[0-9a-f]{40}\$" \
  | grep -v -e ":$SHA\$" -e ":${PREV:-none}\$" | xargs -r docker rmi >/dev/null 2>&1 || true
# Основы прежних хешей (пакеты или Dockerfile менялись) больше не нужны: слои уже внутри выпусков.
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^quantor-(api-deps|cad-base):' \
  | grep -v -e "^$API_DEPS\$" -e "^$CAD_BASE\$" | xargs -r docker rmi >/dev/null 2>&1 || true
docker builder prune -f --filter until=168h >/dev/null 2>&1 || true
ssh -o LogLevel=ERROR "$SSH_HOST" "REG=$REG KEEP=$KEEP_RELEASES CUR=$SHA bash -s" <<'REMOTE' || true
keep="$CUR $(cat /opt/portals/quantor/RELEASE 2>/dev/null) $(docker images "$REG/quantor-api" \
  --format '{{.CreatedAt}}|{{.Tag}}' | grep -E '\|[0-9a-f]{40}$' | sort -r | head -n "$KEEP" \
  | cut -d'|' -f2 | tr '\n' ' ')"
for repo in quantor-api quantor-web quantor-admin quantor-cad-worker; do
  for tag in $(docker images "$REG/$repo" --format '{{.Tag}}' | grep -E '^[0-9a-f]{40}$'); do
    case " $keep " in *" $tag "*) ;; *) docker rmi "$REG/$repo:$tag" >/dev/null 2>&1 || true ;; esac
  done
done
echo "   на сервере выпусков: $(docker images "$REG/quantor-api" --format '{{.Tag}}' | grep -cE '^[0-9a-f]{40}$')"
REMOTE
