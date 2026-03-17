# Task 6 — Docker: три контейнера с nginx reverse proxy

## Запуск

### Windows (PowerShell)
```powershell
.\run_proxied.ps1
```

После запуска API доступно по двум адресам:
- **http://localhost** — через nginx reverse proxy (порт 80)
- **http://localhost:8080** — напрямую к Flask (порт 8080)

## Эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/` | Информация об API |
| GET | `/tracks` | Все треки из БД в JSON |
| GET | `/parse?url=<url>` | Запуск парсера и запись в БД |

Пример запроса:
```
GET http://localhost/parse?url=https://music.yandex.ru/playlists/lk.0c977663-be2c-4be3-b48c-f12ff1fbea57
```

## Остановка и удаление

### Windows
```powershell
.\stop.ps1
```

## Полезные команды

```bash
# Статус контейнеров
docker ps

# Логи приложения (в реальном времени)
docker logs -f yandex-music-app

# Логи nginx
docker logs -f yandex-music-nginx

# Логи БД
docker logs -f yandex-music-db

# Подключиться к БД напрямую
docker exec -it yandex-music-db psql -U postgres

# Посмотреть сеть
docker network inspect yandex-music-net
```

## Архитектура сети

```
  ┌──────────────────────────────────────────────────────────┐
  │              Docker network: yandex-music-net            │
  │                                                          │
  │  ┌─────────────────────┐   ┌──────────────────────────┐  │
  │  │ yandex-music-nginx  │──>│  yandex-music-app        │  │
  │  │ (nginx, :80)        │   │  (Flask, :5000)          │  │
  │  └─────────────────────┘   └──────────┬───────────────┘  │
  │                                       │                  │
  │                            ┌──────────▼───────────────┐  │
  │                            │  yandex-music-db         │  │
  │                            │  (PostgreSQL, :5432)     │  │
  │                            └──────────────────────────┘  │
  └──────────────────────────────────────────────────────────┘
           ▲                ▲
      хост :80         хост :8080
    (via nginx)        (direct)
```
