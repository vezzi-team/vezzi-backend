#!/usr/bin/env bash
# Резервная копия PostgreSQL (N04). Запуск из корня репозитория: ./deploy/backup.sh
# Для ежедневного запуска добавьте в crontab пользователя deploy:
#   15 3 * * * cd /home/deploy/vezzi-backend && ./deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail

BACKUP_DIR="$(pwd)/backups"
KEEP_DAYS="${KEEP_DAYS:-14}"
FILE="$BACKUP_DIR/vezzi-$(date +%Y%m%d-%H%M%S).dump"

mkdir -p "$BACKUP_DIR"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$FILE"
echo "$(date -Iseconds) копия сохранена: $FILE ($(du -h "$FILE" | cut -f1))"

find "$BACKUP_DIR" -name 'vezzi-*.dump' -mtime +"$KEEP_DAYS" -delete
