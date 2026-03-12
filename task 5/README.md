# Task 5 — Docker: два контейнера без docker-compose

## Запуск

### Windows (PowerShell)
```powershell
.\run.ps1
```

После запуска API доступно по адресу: **http://localhost:8080**

## Эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/` | Информация об API |
| GET | `/tracks` | Все треки из БД в JSON |
| GET | `/parse?url=<url>` | Запуск парсера и запись в БД |

Пример запроса:
```
GET http://localhost:8080/parse?url=https://music.yandex.ru/playlists/lk.0c977663-be2c-4be3-b48c-f12ff1fbea57
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

# Логи БД
docker logs -f yandex-music-db

# Подключиться к БД напрямую
docker exec -it yandex-music-db psql -U postgres

# Посмотреть сеть
docker network inspect yandex-music-net
```

## Архитектура сети

```
  ┌─────────────────────────────────────────────────┐
  │           Docker network: yandex-music-net      │
  │                                                 │
  │  ┌──────────────────┐   ┌──────────────────────┐│
  │  │  yandex-music-app│──>│  yandex-music-db     ││
  │  │  (Flask, :5000)  │   │  (PostgreSQL, :5432) ││
  │  └──────────────────┘   └──────────────────────┘│
  └─────────────────────────────────────────────────┘
           ▲
     хост :8080
```
