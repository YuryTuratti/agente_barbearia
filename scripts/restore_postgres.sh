#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
CONFIRM="${CONFIRM_RESTORE:-}"

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /path/to/backup.dump" >&2
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE." >&2
  exit 1
fi

if [ "$CONFIRM" != "yes" ]; then
  echo "Stop api, inbound-worker and outbound-worker before restore."
  printf "Type RESTORE to continue: "
  read answer
  if [ "$answer" != "RESTORE" ]; then
    echo "Restore cancelled." >&2
    exit 1
  fi
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' \
  < "$BACKUP_FILE"

echo "Restore finished. Run readiness checks before starting application containers."
