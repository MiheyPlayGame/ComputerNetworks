# run_proxied.ps1 - Launch three Docker containers (no docker-compose)
#   1. yandex-music-db    - PostgreSQL
#   2. yandex-music-app   - Flask API  (host port 8080 -> container 5000)
#   3. yandex-music-nginx - nginx reverse proxy (host port 80 -> app:5000)
# All containers share the bridge network: yandex-music-net

$NETWORK         = "yandex-music-net"
$DB_CONTAINER    = "yandex-music-db"
$APP_CONTAINER   = "yandex-music-app"
$NGINX_CONTAINER = "yandex-music-nginx"
$APP_IMAGE       = "yandex-music-api"
$NGINX_IMAGE     = "yandex-music-nginx-geoip"
$HOST_PORT       = 8080
$APP_PORT        = 5000
$NGINX_CONF      = Join-Path $PSScriptRoot "nginx.conf"
$NGINX_DOCKERFILE = Join-Path $PSScriptRoot "Dockerfile.nginx"
$GEOIP_DIR       = Join-Path $PSScriptRoot "geoip"
$GEOIP_DB        = Join-Path $GEOIP_DIR "GeoLite2-Country.mmdb"
$GEOIP_DB_URL    = "https://raw.githubusercontent.com/P3TERX/GeoLite.mmdb/download/GeoLite2-Country.mmdb"

$DB_USER     = "postgres"
$DB_PASSWORD = "postgres"
$DB_NAME     = "postgres"

$AUTH_STATE = Join-Path $PSScriptRoot "..\task 3\yandex_music_auth_state.json"
$AUTH_STATE = [System.IO.Path]::GetFullPath($AUTH_STATE)

# --- Step 1: Create network ---
Write-Host "=== Step 1: Create network '$NETWORK' ===" -ForegroundColor Cyan
$existingNet = docker network ls --filter "name=^${NETWORK}$" --format "{{.Name}}" 2>$null
if ($existingNet -eq $NETWORK) {
    Write-Host "  Network already exists, skipping." -ForegroundColor Yellow
} else {
    docker network create $NETWORK
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create network."; exit 1 }
    Write-Host "  Network created." -ForegroundColor Green
}

# --- Step 2: Start DB container ---
Write-Host ""
Write-Host "=== Step 2: Start DB container '$DB_CONTAINER' ===" -ForegroundColor Cyan
$existingDb = docker ps -a --filter "name=^${DB_CONTAINER}$" --format "{{.Names}}" 2>$null
if ($existingDb -eq $DB_CONTAINER) {
    Write-Host "  Container already exists, starting it..." -ForegroundColor Yellow
    docker start $DB_CONTAINER | Out-Null
} else {
    docker run -d `
        --name $DB_CONTAINER `
        --network $NETWORK `
        -e POSTGRES_USER=$DB_USER `
        -e POSTGRES_PASSWORD=$DB_PASSWORD `
        -e POSTGRES_DB=$DB_NAME `
        postgres:16
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to start DB container."; exit 1 }
    Write-Host "  DB container started." -ForegroundColor Green
}

# --- Step 3: Wait for PostgreSQL ---
Write-Host ""
Write-Host "=== Step 3: Waiting for PostgreSQL (up to 30s) ===" -ForegroundColor Cyan
$ready = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 2
    $check = docker exec $DB_CONTAINER pg_isready -U $DB_USER 2>&1
    if ($check -match "accepting connections") {
        $ready = $true
        Write-Host "  PostgreSQL is ready." -ForegroundColor Green
        break
    }
    Write-Host "  Attempt $i/15 - not ready yet..."
}
if (-not $ready) {
    Write-Warning "PostgreSQL did not respond in 30s, continuing anyway..."
}

# --- Step 4: Build app image ---
Write-Host ""
Write-Host "=== Step 4: Build app image '$APP_IMAGE' ===" -ForegroundColor Cyan
Push-Location $PSScriptRoot
docker build --pull=false -t $APP_IMAGE .
if ($LASTEXITCODE -ne 0) { Write-Error "Image build failed."; exit 1 }
Pop-Location
Write-Host "  Image built." -ForegroundColor Green

# --- Step 5: Start app container ---
Write-Host ""
Write-Host "=== Step 5: Start app container '$APP_CONTAINER' ===" -ForegroundColor Cyan
$existingApp = docker ps -a --filter "name=^${APP_CONTAINER}$" --format "{{.Names}}" 2>$null
if ($existingApp -eq $APP_CONTAINER) {
    Write-Host "  Container exists, removing and recreating..." -ForegroundColor Yellow
    docker rm -f $APP_CONTAINER | Out-Null
}

$DATABASE_URL = "postgresql://${DB_USER}:${DB_PASSWORD}@${DB_CONTAINER}:5432/${DB_NAME}"

if (Test-Path $AUTH_STATE) {
    Write-Host "  Auth state file found, mounting as volume." -ForegroundColor Green
    docker run -d `
        --name $APP_CONTAINER `
        --network $NETWORK `
        -p "${HOST_PORT}:${APP_PORT}" `
        -e "DATABASE_URL=$DATABASE_URL" `
        -v "${AUTH_STATE}:/app/yandex_music_auth_state.json:ro" `
        $APP_IMAGE
} else {
    Write-Host "  No auth state file, starting without auth." -ForegroundColor Yellow
    docker run -d `
        --name $APP_CONTAINER `
        --network $NETWORK `
        -p "${HOST_PORT}:${APP_PORT}" `
        -e "DATABASE_URL=$DATABASE_URL" `
        $APP_IMAGE
}

if ($LASTEXITCODE -ne 0) { Write-Error "Failed to start app container."; exit 1 }
Write-Host "  App container started." -ForegroundColor Green

# --- Step 6: Start nginx container ---
Write-Host ""
Write-Host "=== Step 6: Start nginx container '$NGINX_CONTAINER' ===" -ForegroundColor Cyan
$existingNginx = docker ps -a --filter "name=^${NGINX_CONTAINER}$" --format "{{.Names}}" 2>$null
if ($existingNginx -eq $NGINX_CONTAINER) {
    Write-Host "  Container exists, removing and recreating..." -ForegroundColor Yellow
    docker rm -f $NGINX_CONTAINER | Out-Null
}

# --- Step 6.1: Prepare GeoIP database ---
if (-not (Test-Path $GEOIP_DIR)) {
    New-Item -ItemType Directory -Path $GEOIP_DIR | Out-Null
}
if (-not (Test-Path $GEOIP_DB)) {
    Write-Host "  GeoIP DB not found, downloading..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $GEOIP_DB_URL -OutFile $GEOIP_DB
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $GEOIP_DB)) {
        Write-Error "Failed to download GeoIP DB."
        exit 1
    }
}

# --- Step 6.2: Build nginx image with GeoIP2 module ---
Write-Host "  Building nginx image '$NGINX_IMAGE'..." -ForegroundColor Cyan
Push-Location $PSScriptRoot
docker build --pull=false -f $NGINX_DOCKERFILE -t $NGINX_IMAGE .
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to build nginx image."; exit 1 }
Pop-Location

docker run -d `
    --name $NGINX_CONTAINER `
    --network $NETWORK `
    -p 80:80 `
    -v "${NGINX_CONF}:/etc/nginx/conf.d/default.conf:ro" `
    -v "${GEOIP_DB}:/etc/nginx/geoip/GeoLite2-Country.mmdb:ro" `
    $NGINX_IMAGE
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to start nginx container."; exit 1 }
Write-Host "  nginx container started." -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " API ready at: http://localhost:$HOST_PORT  (direct)" -ForegroundColor Green
Write-Host " API ready at: http://localhost:80           (via nginx)" -ForegroundColor Green
Write-Host ""
Write-Host " Endpoints:"
Write-Host "   GET http://localhost/"
Write-Host "   GET http://localhost/tracks"
Write-Host "   GET http://localhost/parse?url=<playlist_url>"
Write-Host ""
Write-Host " App logs:   docker logs -f $APP_CONTAINER"
Write-Host " DB  logs:   docker logs -f $DB_CONTAINER"
Write-Host " Nginx logs: docker logs -f $NGINX_CONTAINER"
Write-Host " Stop all:   .\stop.bat"
Write-Host "============================================================" -ForegroundColor Green
