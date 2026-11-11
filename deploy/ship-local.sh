#!/usr/bin/env bash
#
# Выкатка Quantor без GitHub Actions и GHCR: образы собираются на этой машине, передаются на
# сервер по ssh (`docker save | docker load`), затем `update.sh` выкатывает их без скачивания.
#
#   deploy/ship-local.sh [<git-ref>]      # по умолчанию origin/main
#   deploy/ship-local.sh --build-only [<git-ref>]
#
# Сборка повторяет publish.yml: тот же набор образов, теги `ghcr.io/baldmaxim/<образ>:<полный sha>`
# (по ним update.sh сверяет контейнеры), те же build-args. Исходники берутся из чистых git worktree:
# незакоммиченные правки рабочей копии в образ не попадают. Движок CAD и генераторы — из репозитория
# CAD_engine по tools/cad_engine/pins.json со сверкой sha256.
#
# Окружение: QUANTOR_SSH (по умолчанию quantor), CAD_ENGINE_REPO (по умолчанию ../CAD_engine),
# QUANTOR_PUBLIC_ORIGIN, QUANTOR_ADMIN_ORIGIN. Образов этой сборки в GHCR нет: повторить выкладку
# того же sha можно только этим скриптом.
set -euo pipefail

BUILD_ONLY=0
if [ "${1:-}" = "--build-only" ]; then BUILD_ONLY=1; shift; fi
REF="${1:-origin/main}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_REPO="${CAD_ENGINE_REPO:-$ROOT/../CAD_engine}"
SSH_HOST="${QUANTOR_SSH:-quantor}"
PUBLIC_ORIGIN="${QUANTOR_PUBLIC_ORIGIN:-https://quantor.meridianai.ru}"
ADMIN_ORIGIN="${QUANTOR_ADMIN_ORIGIN:-https://admin.quantor.meridianai.ru}"
REG=ghcr.io/baldmaxim
REMOTE_DIR=/opt/portals/quantor

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

git -C "$ROOT" worktree add -q --detach "$WT" "$SHA"

PINS="$WT/tools/cad_engine/pins.json"
pin() { jq -er "$1" "$PINS"; }
ENGINE_REF="$(pin .engine.repo_ref)"
ARCHIVE_PATH="$(pin .engine.archive_path)"
ARCHIVE_SHA="$(pin .engine.archive_sha256)"
git -C "$ENGINE_REPO" cat-file -e "${ENGINE_REF}^{commit}" 2>/dev/null \
  || git -C "$ENGINE_REPO" fetch -q origin "$ENGINE_REF"
git -C "$ENGINE_REPO" worktree add -q --detach "$EWT" "$ENGINE_REF"

echo "→ движок CAD ${ENGINE_REF:0:7} (сверка sha256)"
mkdir -p "$WT/deploy/cad-engine/generators"
cp "$EWT/$ARCHIVE_PATH" "$WT/deploy/cad-engine/engine.zip"
echo "$ARCHIVE_SHA  $WT/deploy/cad-engine/engine.zip" | sha256sum -c --quiet -
for name in cad_mep cad_walls; do
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
build() { echo "→ образ $1"; docker build -q -f "$WT/$2" "${@:3}" -t "$REG/$1:$SHA" "$WT" >/dev/null; }
build quantor-api deploy/Dockerfile.api --build-arg APP= "${next_args[@]}"
build quantor-web deploy/Dockerfile.next --build-arg APP=web "${next_args[@]}"
build quantor-admin deploy/Dockerfile.next --build-arg APP=admin "${next_args[@]}"
build quantor-cad-worker deploy/Dockerfile.cad-worker \
  --build-arg "API_IMAGE=$REG/quantor-api:$SHA" --build-arg "ENGINE_ARCHIVE_SHA256=$ARCHIVE_SHA"
[ "$BUILD_ONLY" = 1 ] && { echo "собрано: ${SHA}"; exit 0; }

images=("$REG/quantor-api:$SHA" "$REG/quantor-web:$SHA" "$REG/quantor-admin:$SHA" "$REG/quantor-cad-worker:$SHA")
echo "→ передача образов на ${SSH_HOST}"
docker save "${images[@]}" | gzip -1 | ssh -o LogLevel=ERROR "$SSH_HOST" 'gunzip | docker load' >/dev/null

# update.sh берётся из образа того же коммита: на сервере может лежать старый, без SKIP_PULL.
echo "→ update.sh на сервере"
ssh -o LogLevel=ERROR "$SSH_HOST" "set -e; cd $REMOTE_DIR; \
  h=\$(docker create $REG/quantor-api:$SHA true); docker cp \$h:/app/deploy/update.sh update.sh; \
  docker rm -f \$h >/dev/null; SKIP_PULL=1 ./update.sh $SHA"
