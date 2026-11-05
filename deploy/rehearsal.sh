#!/usr/bin/env bash
# Генеральная репетиция на своём компьютере: те же образы и настройки, что на сервере,
# только адрес localhost и отдельный проект Docker. Базу для разработки не трогает.
#
#   ./deploy/rehearsal.sh <каталог.xlsx>   поднять всё, загрузить каталог, пройти проверку
#   ./deploy/rehearsal.sh --clean          остановить и удалить данные репетиции
#
# Перед запуском нужен граф карты: ./deploy/osrm/prepare.sh
set -euo pipefail

export API_DOMAIN=localhost
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-rehearsal-password}"
# Цены в таблице команды растянуты на 10 дней. На настоящих суточных данных будет 24.
export OFFER_MAX_AGE_HOURS="${OFFER_MAX_AGE_HOURS:-264}"
BUILD_COMMIT="$(git rev-parse --short HEAD)"
export BUILD_COMMIT

compose() {
  docker compose -p vezzi-rehearsal -f compose.yaml -f deploy/compose.prod.yaml --profile routing "$@"
}

if [ "${1:-}" = "--clean" ]; then
  compose down --volumes --remove-orphans
  exit 0
fi

CATALOG="${1:?Укажите файл каталога: ./deploy/rehearsal.sh <каталог.xlsx>}"

compose up -d --build --wait --wait-timeout 180 api caddy osrm
compose cp "$CATALOG" api:/tmp/catalog.xlsx
compose exec -T api vezzi import-catalog /tmp/catalog.xlsx --synthetic --shift-timestamps
uv run python deploy/smoke_test.py https://localhost --insecure
echo "Swagger: https://localhost/docs (браузер предупредит о локальном сертификате)"
