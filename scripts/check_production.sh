#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=5).read()"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read()"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api alembic current
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api python -m app.cli.queue_status
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres df -h /var/lib/postgresql/data || true
