#!/usr/bin/env bash
# Deploy a commit of main on the demo server. Run as the ubuntu user:
#   ~/civic-pulse/infra/deploy/deploy.sh <commit-sha>
# The deploy workflow runs it through AWS SSM; it is safe to run by hand.
set -euo pipefail

SHA="${1:-origin/main}"
REPO="$HOME/civic-pulse"
COMPOSE=(sudo docker compose -f "$REPO/infra/deploy/compose.yml" --env-file "$HOME/deploy/.env")

git -C "$REPO" fetch --quiet origin main
git -C "$REPO" checkout --quiet --force "$SHA"
echo "Deploying $(git -C "$REPO" log --oneline -1)"

# Docker Hub rate-limits anonymous pulls from shared cloud IPs; take the
# base images from Google's mirror and tag them with the names the
# Dockerfiles and the compose file use.
for img in library/redis:7.4-alpine postgis/postgis:16-3.5 library/caddy:2 library/python:3.12-slim-bookworm; do
  sudo docker pull --quiet "mirror.gcr.io/$img" >/dev/null
  sudo docker tag "mirror.gcr.io/$img" "${img#library/}"
done

# Migrations run in the `migrate` service before api/worker/beat start.
"${COMPOSE[@]}" up -d --build --wait --remove-orphans
sudo docker image prune -f >/dev/null

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 https://13-207-212-110.sslip.io/health >/dev/null; then
    echo "Healthy."
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy" >&2
"${COMPOSE[@]}" logs --tail 80 api migrate >&2
exit 1
