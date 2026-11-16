#!/usr/bin/env bash
# Ежедневный срез каталога. Запуск из корня репозитория на сервере:
#   ./deploy/refresh_catalog.sh [файл.xlsx]      по умолчанию data/catalog.xlsx
#
# Пока данные синтетические, каждую ночь загружается одна и та же таблица со сдвигом времени:
# самая свежая цена становится «сейчас», и цены не устаревают (docs/decisions.md, решение 5).
# Когда появятся настоящие суточные данные, сюда нужно класть новый срез и убрать оба флага.
#
# Для ежедневного запуска добавьте в crontab пользователя deploy (после резервной копии в 03:15):
#   30 3 * * * cd /home/deploy/vezzi-backend && ./deploy/refresh_catalog.sh >> backups/catalog.log 2>&1
set -euo pipefail

FILE="${1:-data/catalog.xlsx}"

dc() {
  docker compose -f compose.yaml -f deploy/compose.prod.yaml --profile routing "$@"
}

# Своё имя файла в контейнере: /tmp/catalog.xlsx после ручной загрузки через docker cp принадлежит root.
TARGET=/tmp/nightly-catalog.xlsx

echo "$(date -Iseconds) загружаю $FILE"
trap 'dc exec -T api rm -f "$TARGET"' EXIT
# Копируем через stdin, а не docker cp: так файл принадлежит пользователю контейнера и удаляется без root.
dc exec -T api sh -c "cat > $TARGET" < "$FILE"
dc exec -T api vezzi import-catalog "$TARGET" --synthetic --shift-timestamps
