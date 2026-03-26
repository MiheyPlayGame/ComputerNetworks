#!/usr/bin/env bash
set -euo pipefail

# run.sh - Launch three Docker containers (no docker-compose)
#   1. yandex-music-db    - PostgreSQL
#   2. yandex-music-app   - Flask API  (host port 8080 -> container 5000)
#   3. yandex-music-nginx - nginx reverse proxy (host port 80 -> app:5000)
# All containers share the bridge network: yandex-music-net

NETWORK="yandex-music-net"
DB_CONTAINER="yandex-music-db"
APP_CONTAINER="yandex-music-app"
NGINX_CONTAINER="yandex-music-nginx"
APP_IMAGE="yandex-music-api"
NGINX_IMAGE="yandex-music-nginx-geoip"
HOST_PORT="8080"
APP_PORT="5000"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_CONF="${SCRIPT_DIR}/nginx.conf"
NGINX_DOCKERFILE="${SCRIPT_DIR}/Dockerfile.nginx"
GEOIP_DIR="${SCRIPT_DIR}/geoip"
GEOIP_DB="${GEOIP_DIR}/GeoLite2-Country.mmdb"
GEOIP_DB_URL="https://raw.githubusercontent.com/P3TERX/GeoLite.mmdb/download/GeoLite2-Country.mmdb"

DB_USER="postgres"
DB_PASSWORD="postgres"
DB_NAME="postgres"

AUTH_STATE="${SCRIPT_DIR}/../task 3/yandex_music_auth_state.json"
AUTH_STATE="$(realpath "${AUTH_STATE}" 2>/dev/null || true)"

echo "=== Step 1: Create network '${NETWORK}' ==="
if docker network ls --filter "name=^${NETWORK}$" --format "{{.Name}}" | grep -qx "${NETWORK}"; then
  echo "  Network already exists, skipping."
else
  docker network create "${NETWORK}"
  echo "  Network created."
fi

echo
echo "=== Step 2: Start DB container '${DB_CONTAINER}' ==="
if docker ps -a --filter "name=^${DB_CONTAINER}$" --format "{{.Names}}" | grep -qx "${DB_CONTAINER}"; then
  echo "  Container already exists, starting it..."
  docker start "${DB_CONTAINER}" >/dev/null
else
  docker run -d \
    --name "${DB_CONTAINER}" \
    --network "${NETWORK}" \
    -e POSTGRES_USER="${DB_USER}" \
    -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
    -e POSTGRES_DB="${DB_NAME}" \
    postgres:16
  echo "  DB container started."
fi

echo
echo "=== Step 3: Waiting for PostgreSQL (up to 30s) ==="
ready=false
for i in {1..15}; do
  sleep 2
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" 2>&1 | grep -q "accepting connections"; then
    ready=true
    echo "  PostgreSQL is ready."
    break
  fi
  echo "  Attempt ${i}/15 - not ready yet..."
done
if [[ "${ready}" != "true" ]]; then
  echo "  Warning: PostgreSQL did not respond in 30s, continuing anyway..."
fi

echo
echo "=== Step 4: Build app image '${APP_IMAGE}' ==="
docker build --pull=false -t "${APP_IMAGE}" "${SCRIPT_DIR}"
echo "  Image built."

echo
echo "=== Step 5: Start app container '${APP_CONTAINER}' ==="
if docker ps -a --filter "name=^${APP_CONTAINER}$" --format "{{.Names}}" | grep -qx "${APP_CONTAINER}"; then
  echo "  Container exists, removing and recreating..."
  docker rm -f "${APP_CONTAINER}" >/dev/null
fi

DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_CONTAINER}:5432/${DB_NAME}"

if [[ -n "${AUTH_STATE}" && -f "${AUTH_STATE}" ]]; then
  echo "  Auth state file found, mounting as volume."
  docker run -d \
    --name "${APP_CONTAINER}" \
    --network "${NETWORK}" \
    -p "${HOST_PORT}:${APP_PORT}" \
    -e "DATABASE_URL=${DATABASE_URL}" \
    -v "${AUTH_STATE}:/app/yandex_music_auth_state.json:ro" \
    "${APP_IMAGE}"
else
  echo "  No auth state file, starting without auth."
  docker run -d \
    --name "${APP_CONTAINER}" \
    --network "${NETWORK}" \
    -p "${HOST_PORT}:${APP_PORT}" \
    -e "DATABASE_URL=${DATABASE_URL}" \
    "${APP_IMAGE}"
fi
echo "  App container started."

echo
echo "=== Step 6: Start nginx container '${NGINX_CONTAINER}' ==="
if docker ps -a --filter "name=^${NGINX_CONTAINER}$" --format "{{.Names}}" | grep -qx "${NGINX_CONTAINER}"; then
  echo "  Container exists, removing and recreating..."
  docker rm -f "${NGINX_CONTAINER}" >/dev/null
fi

if [[ ! -d "${GEOIP_DIR}" ]]; then
  mkdir -p "${GEOIP_DIR}"
fi
if [[ ! -f "${GEOIP_DB}" ]]; then
  echo "  GeoIP DB not found, downloading..."
  curl -fL "${GEOIP_DB_URL}" -o "${GEOIP_DB}"
fi

echo "  Building nginx image '${NGINX_IMAGE}'..."
docker build --pull=false -f "${NGINX_DOCKERFILE}" -t "${NGINX_IMAGE}" "${SCRIPT_DIR}"

docker run -d \
  --name "${NGINX_CONTAINER}" \
  --network "${NETWORK}" \
  -p 80:80 \
  -v "${NGINX_CONF}:/etc/nginx/conf.d/default.conf:ro" \
  -v "${GEOIP_DB}:/etc/nginx/geoip/GeoLite2-Country.mmdb:ro" \
  "${NGINX_IMAGE}"
echo "  nginx container started."

echo
echo "============================================================"
echo " API ready at: http://localhost:${HOST_PORT}  (direct)"
echo " API ready at: http://localhost:80            (via nginx)"
echo
echo " Endpoints:"
echo "   GET http://localhost/"
echo "   GET http://localhost/tracks"
echo "   GET http://localhost/parse?url=<playlist_url>"
echo
echo " App logs:   docker logs -f ${APP_CONTAINER}"
echo " DB  logs:   docker logs -f ${DB_CONTAINER}"
echo " Nginx logs: docker logs -f ${NGINX_CONTAINER}"
echo " Stop all:   ./stop.sh"
echo "============================================================"
