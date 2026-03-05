"""
API для парсинга плейлистов Яндекс.Музыки и хранения результатов в PostgreSQL.

Эндпоинты:
  GET /parse?url=<url>  — запуск парсера по ссылке на плейлист, запись в БД.
  GET /tracks           — получение всех треков из таблицы БД в виде JSON.
"""

import importlib.util
import os
import re
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

# Загружаем переменные из .env (пароль и хост БД задаются там)
load_dotenv(Path(__file__).resolve().parent / ".env")

# Загружаем парсер из task 3 (папка с пробелом в имени)
_TASK3_DIR = Path(__file__).resolve().parent.parent / "task 3"
_parser_path = _TASK3_DIR / "yandex_music_playlist_parser.py"
_spec = importlib.util.spec_from_file_location("playlist_parser", _parser_path)
_parser_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_parser_module)
run_parser = _parser_module.run_parser

app = Flask(__name__)

# Подключение к PostgreSQL: задайте DATABASE_URL в .env или в переменной окружения
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit(
        "Задайте DATABASE_URL (пароль и БД). Пример:\n"
        "  В файле task 4/.env строка: DATABASE_URL=postgresql://postgres:ВАШ_ПАРОЛЬ@localhost:5432/postgres\n"
        "  Или в консоли: set DATABASE_URL=postgresql://postgres:ВАШ_ПАРОЛЬ@localhost:5432/postgres"
    )

# Допустимый формат ссылки на плейлист Яндекс.Музыки
YANDEX_PLAYLIST_PATTERN = re.compile(
    r"^https?://(?:music\.yandex\.(?:ru|com)|yandex\.ru/music)/playlists/[\w.-]+",
    re.IGNORECASE,
)


def normalize_playlist_url(url):
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url if YANDEX_PLAYLIST_PATTERN.match(url) else None


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Создаёт таблицу, если её ещё нет."""
    sql = """
    CREATE TABLE IF NOT EXISTS yandex_playlist_tracks (
        id SERIAL PRIMARY KEY,
        playlist_url TEXT NOT NULL,
        position INT NOT NULL,
        title TEXT,
        artists TEXT,
        duration TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def save_tracks_to_db(playlist_url, tracks):
    """Записывает список треков в PostgreSQL."""
    if not tracks:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO yandex_playlist_tracks (playlist_url, position, title, artists, duration)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        playlist_url,
                        t.get("position", 0),
                        t.get("title") or "",
                        t.get("artists") or "",
                        t.get("duration") or "",
                    )
                    for t in tracks
                ],
            )
        conn.commit()
    return len(tracks)


def get_tracks_from_db():
    """Читает все треки из таблицы и возвращает список словарей."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, playlist_url, position, title, artists, duration, created_at
                FROM yandex_playlist_tracks
                ORDER BY created_at DESC, position ASC
                """
            )
            rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "playlist_url": r[1],
            "position": r[2],
            "title": r[3],
            "artists": r[4],
            "duration": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


@app.route("/parse", methods=["GET"])
def parse_playlist():
    """
    Запускает парсер по ссылке на плейлист Яндекс.Музыки и сохраняет результат в БД.
    Обязательный параметр: url — ссылка на плейлист (например music.yandex.ru/playlists/...).
    """
    url_param = request.args.get("url")
    playlist_url = normalize_playlist_url(url_param)

    if not playlist_url:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Передайте корректную ссылку на плейлист Яндекс.Музыки в параметре url (например: music.yandex.ru/playlists/...)",
                }
            ),
            400,
        )

    try:
        tracks = run_parser(
            use_auth=True,
            headless=True,
            playlist_url=playlist_url,
            save_csv=False,
        )
    except Exception as e:
        return (
            jsonify({"ok": False, "error": f"Ошибка парсинга: {str(e)}"}),
            500,
        )

    try:
        count = save_tracks_to_db(playlist_url, tracks)
    except Exception as e:
        return (
            jsonify({"ok": False, "error": f"Ошибка записи в БД: {str(e)}"}),
            500,
        )

    return jsonify(
        {
            "ok": True,
            "playlist_url": playlist_url,
            "tracks_parsed": len(tracks),
            "tracks_saved": count,
        }
    )


@app.route("/tracks", methods=["GET"])
def get_tracks():
    """Возвращает все записи из таблицы yandex_playlist_tracks в виде JSON."""
    try:
        data = get_tracks_from_db()
    except Exception as e:
        return (
            jsonify({"ok": False, "error": f"Ошибка чтения из БД: {str(e)}"}),
            500,
        )
    return jsonify({"ok": True, "tracks": data, "count": len(data)})


@app.route("/", methods=["GET"])
def index():
    return jsonify(
        {
            "api": "Yandex Music Playlist Parser API",
            "endpoints": {
                "parse": "GET /parse?url=<yandex_music_playlist_url> — запуск парсера, запись в БД",
                "tracks": "GET /tracks — все треки из БД в JSON",
            },
        }
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
