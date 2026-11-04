#!/usr/bin/env bash
# Runs ON THE SERVER, started over SSH by .github/workflows/deploy.yml.
#
#   echo "$GITHUB_TOKEN" | ./deploy.sh <ghcr-owner> <image-tag> <ghcr-user>
#
# Pulls the new images, applies database migrations, restarts the stack and waits for /health.
set -euo pipefail

cd "$(dirname "$0")"

OWNER="${1:?ghcr owner}"
TAG="${2:?image tag}"
GH_USER="${3:?ghcr user}"
read -r GHCR_TOKEN   # the token arrives on stdin so it never appears in a process list

export GHCR_OWNER="$OWNER" IMAGE_TAG="$TAG"

[ -f .env ] || { echo "ERROR: .env is missing on the server (see deploy/env.example)"; exit 1; }

echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GH_USER" --password-stdin >/dev/null

dc="docker compose -f docker-compose.prod.yml"

echo "==> Pulling images ($TAG)"
$dc pull

echo "==> Starting the database"
$dc up -d postgres

echo "==> Applying migrations"
$dc run --rm backend alembic upgrade head

echo "==> Starting the stack"
$dc up -d --remove-orphans

DOMAIN="$(grep -E '^DOMAIN=' .env | head -n1 | cut -d= -f2- | tr -d '"'"'"' \r')"
echo "==> Waiting for https://$DOMAIN/health"
for _ in $(seq 1 36); do
  if curl -fsS --max-time 5 "https://$DOMAIN/health" >/dev/null 2>&1; then
    echo "Healthy. Deployed $TAG."
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 5
done

echo "ERROR: the app did not become healthy. Recent logs:"
$dc ps
$dc logs --tail=60 backend caddy
exit 1
