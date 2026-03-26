#!/usr/bin/env bash
set -euo pipefail

# stop.sh - Stop and remove task 7 containers and network

NETWORK="yandex-music-net"
DB_CONTAINER="yandex-music-db"
APP_CONTAINER="yandex-music-app"
NGINX_CONTAINER="yandex-music-nginx"

echo "Removing containers..."
docker rm -f "${APP_CONTAINER}" 2>/dev/null || true
docker rm -f "${DB_CONTAINER}" 2>/dev/null || true
docker rm -f "${NGINX_CONTAINER}" 2>/dev/null || true

echo "Removing network '${NETWORK}'..."
docker network rm "${NETWORK}" 2>/dev/null || true

echo "Done."
