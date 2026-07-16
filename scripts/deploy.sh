#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Create it from .env.production.example and fill placeholders." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d postgres

echo "Waiting for PostgreSQL health check..."
for _ in $(seq 1 60); do
  STATUS="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --format json postgres | grep -o '"Health":"[^"]*"' | head -n 1 || true)"
  if printf '%s' "$STATUS" | grep -q healthy; then
    break
  fi
  sleep 2
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm migrate
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d api inbound-worker outbound-worker

echo "Waiting for API readiness..."
for _ in $(seq 1 60); do
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read()" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
