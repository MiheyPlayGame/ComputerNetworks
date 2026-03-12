# stop.ps1 - Stop and remove task 5 containers and network

$NETWORK       = "yandex-music-net"
$DB_CONTAINER  = "yandex-music-db"
$APP_CONTAINER = "yandex-music-app"

Write-Host "Removing containers..." -ForegroundColor Cyan
docker rm -f $APP_CONTAINER 2>$null
docker rm -f $DB_CONTAINER  2>$null

Write-Host "Removing network '$NETWORK'..." -ForegroundColor Cyan
docker network rm $NETWORK 2>$null

Write-Host "Done." -ForegroundColor Green
