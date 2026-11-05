#!/usr/bin/env bash
# Готовит пешеходный граф OSRM для Санкт-Петербурга.
# Запуск из корня репозитория: ./deploy/osrm/prepare.sh
# Нужно около 1 ГБ RAM, 500 МБ диска и пару минут. Повторный запуск обновляет карту.
set -euo pipefail

EXTRACT_URL="${OSRM_EXTRACT_URL:-https://download.bbbike.org/osm/bbbike/SanktPetersburg/SanktPetersburg.osm.pbf}"
IMAGE="ghcr.io/project-osrm/osrm-backend:v6.0.0"
DATA_DIR="$(pwd)/data/osrm"

mkdir -p "$DATA_DIR"
echo "Скачиваю карту OpenStreetMap: $EXTRACT_URL"
curl -fL --retry 3 -o "$DATA_DIR/spb.osm.pbf" "$EXTRACT_URL"

echo "Строю пешеходный граф (профиль foot)"
docker run --rm -v "$DATA_DIR:/data" "$IMAGE" osrm-extract -p /opt/foot.lua /data/spb.osm.pbf
docker run --rm -v "$DATA_DIR:/data" "$IMAGE" osrm-partition /data/spb.osrm
docker run --rm -v "$DATA_DIR:/data" "$IMAGE" osrm-customize /data/spb.osrm

echo "Готово. Перезапустите OSRM: docker compose --profile routing restart osrm"
