import csv
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


OUTPUT_DIR = Path(__file__).resolve().parent
CSV_PATH = OUTPUT_DIR / "yandex_music_tracks.csv"
AUTH_STATE_PATH = OUTPUT_DIR / "yandex_music_auth_state.json"

# URL для парсинга (публичный чарт)
CHART_URL = "https://music.yandex.ru/chart"

PAGINATION_SCROLL_COUNT = 1
SCROLL_PAUSE_SEC = 0.5


def extract_tracks_via_js(page):
    """
    Извлекает треки через JavaScript: ищет строки по ссылкам на /track/ и собирает
    текст из контейнера. Работает при любой вёрстке, если есть ссылки на треки.
    """
    try:
        data = page.evaluate(
            """
            () => {
                const timeRe = /^\\d{1,2}:\\d{2}(?::\\d{2})?$/;
                function findDurationInRow(row) {
                    const durEl = row.querySelector('[class*="duration"], [class*="Duration"], [class*="time"], [class*="Time"]');
                    if (durEl) {
                        const t = (durEl.textContent || '').trim();
                        if (timeRe.test(t)) return t;
                    }
                    const walk = (el) => {
                        const t = (el.textContent || '').trim();
                        if (t && timeRe.test(t) && !el.querySelector('*')) return t;
                        for (const c of el.children) {
                            const r = walk(c);
                            if (r) return r;
                        }
                        return null;
                    };
                    const found = walk(row);
                    if (found) return found;
                    const match = (row.innerText || '').match(/\\b(\\d{1,2}:\\d{2}(?::\\d{2})?)\\b/);
                    return match ? match[1] : null;
                }
                const tracks = [];
                const links = document.querySelectorAll('a[href*="/track/"]');
                const seen = new Set();
                for (const a of links) {
                    const row = a.closest('[class*="track"]') || a.closest('tr') || a.closest('[class*="Row"]') || a.closest('li') || a.closest('div[class*="Item"]') || (a.parentElement && a.parentElement.parentElement && a.parentElement.parentElement.parentElement);
                    if (!row || seen.has(row)) continue;
                    seen.add(row);
                    const text = row.innerText || '';
                    if (!text || text.length < 2) continue;
                    const parts = text.split('\\n').map(s => s.trim()).filter(Boolean);
                    let title = (a.textContent || '').trim() || (parts[0] || '—');
                    let artists = parts.length >= 2 ? parts[1] : '—';
                    let duration = '—';
                    for (let r = row, depth = 0; r && depth < 8; r = r.parentElement, depth++) {
                        duration = findDurationInRow(r) || '—';
                        if (duration !== '—') break;
                    }
                    const href = (a.getAttribute('href') || '').trim();
                    const trackId = (href.match(/\\/track\\/(\\d+)/) || [])[1];
                    if (duration === '—' && trackId && typeof window.__STATE_SNAPSHOT__ !== 'undefined') {
                        const str = JSON.stringify(window.__STATE_SNAPSHOT__);
                        const pos = str.indexOf(trackId);
                        if (pos >= 0) {
                            const block = str.slice(Math.max(0, pos - 50), pos + 400);
                            const dm = block.match(/durationMs\\\\s*:\\\\s*(\\\\d+)/);
                            if (dm) {
                                const ms = parseInt(dm[1], 10);
                                const min = Math.floor(ms / 60000);
                                const sec = Math.floor((ms % 60000) / 1000);
                                duration = min + ':' + (sec < 10 ? '0' : '') + sec;
                            }
                        }
                    }
                    tracks.push({ title, artists, duration });
                }
                return tracks;
            }
        """
        )
        if data and isinstance(data, list) and len(data) > 0:
            result = []
            for i, t in enumerate(data):
                result.append(
                    {
                        "position": i + 1,
                        "title": (t.get("title") or "—").strip() or "—",
                        "artists": (t.get("artists") or "—").strip() or "—",
                        "duration": (t.get("duration") or "—").strip() or "—",
                    }
                )
            return result
    except Exception:
        pass
    return []


def _set_scroll_markers(page):
    """Помечает прокручиваемый контейнер со списком треков (overflow-y: auto/scroll или первый с scrollHeight > clientHeight)."""
    page.evaluate(
        """
        () => {
            const trackLink = document.querySelector('a[href*="/track/"]');
            if (!trackLink) return;
            let el = trackLink;
            let fallback = null;
            while (el && el !== document.body) {
                if (el.scrollHeight > el.clientHeight + 10) {
                    const style = window.getComputedStyle(el);
                    const oy = style.overflowY || style.overflow;
                    if (oy === 'auto' || oy === 'scroll' || oy === 'overlay') {
                        el.setAttribute('data-scroll-id', 'scroll-container-0');
                        return;
                    }
                    if (!fallback) fallback = el;
                }
                el = el.parentElement;
            }
            if (fallback) fallback.setAttribute('data-scroll-id', 'scroll-container-0');
        }
        """
    )


def scroll_for_pagination(
    page,
    scroll_count=PAGINATION_SCROLL_COUNT,
    pause=SCROLL_PAUSE_SEC,
    headless=True,
):
    # Сначала пробуем прокручивать окно (для страниц без внутреннего скролла)
    doc_scrollable = page.evaluate(
        "() => document.documentElement.scrollHeight > document.documentElement.clientHeight + 50"
    )
    if doc_scrollable:
        for i in range(scroll_count):
            page.evaluate(
                "window.scrollTo({ top: document.body.scrollHeight, behavior: '%s' })"
                % ("smooth" if not headless else "auto")
            )
            time.sleep(pause)
        return

    # Ищем внутренний прокручиваемый контейнер
    _set_scroll_markers(page)
    container = page.locator("[data-scroll-id^='scroll-container-']").first
    try:
        if not container.count():
            # Fallback: всё равно крутим окно
            for _ in range(scroll_count):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(pause)
            return
    except Exception:
        for _ in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(pause)
        return

    # Прокручиваем контейнер до конца несколько раз (подгрузка при бесконечном скролле)
    smooth = "smooth" if not headless else "auto"
    for step in range(scroll_count):
        page.evaluate(
            """
            (behavior) => {
                const el = document.querySelector('[data-scroll-id^="scroll-container-"]');
                if (!el) return;
                el.scrollTo({ top: el.scrollHeight, behavior });
            }
            """,
            smooth,
        )
        time.sleep(pause)


def save_to_csv(rows, path):
    if not rows:
        print("Нет данных для записи в CSV.")
        return
    fieldnames = ["position", "title", "artists", "duration"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Записано треков в CSV: {len(rows)} — {path}")


def run_parser(use_auth=False, headless=True):
    all_tracks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_options = {"viewport": {"width": 1280, "height": 720}}
        if use_auth and AUTH_STATE_PATH.exists():
            context_options["storage_state"] = str(AUTH_STATE_PATH)
        context = browser.new_context(**context_options)
        page = context.new_page()

        try:
            page.goto(CHART_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            print(
                "Таймаут загрузки страницы. Возможна блокировка по региону или нужна авторизация."
            )

        time.sleep(2)
        # Ждём появления хотя бы одной ссылки на трек (чат загружен)
        try:
            page.wait_for_selector('a[href*="/track/"]', timeout=10000)
        except PlaywrightTimeout:
            pass

        # Пагинация (передаём headless, чтобы при --visible была плавная видимая прокрутка)
        scroll_for_pagination(page, headless=headless)

        # Сбор треков: сначала через JS (работает при любой вёрстке)
        all_tracks = extract_tracks_via_js(page)

        save_to_csv(all_tracks, CSV_PATH)

        context.close()
        browser.close()

    return all_tracks


def save_auth_state():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.goto("https://music.yandex.ru/", wait_until="domcontentloaded")
        input(
            "Войдите в аккаунт в браузере и нажмите Enter здесь для сохранения сессии..."
        )
        context.storage_state(path=str(AUTH_STATE_PATH))
        print(f"Сессия сохранена: {AUTH_STATE_PATH}")
        context.close()
        browser.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Парсер Яндекс.Музыки (Playwright)")
    parser.add_argument(
        "--auth", action="store_true", help="Использовать сохранённую авторизацию"
    )
    parser.add_argument(
        "--visible", action="store_true", help="Запуск браузера в видимом режиме"
    )
    parser.add_argument(
        "--save-auth",
        action="store_true",
        help="Режим сохранения авторизации (ручной вход)",
    )
    args = parser.parse_args()
    if args.save_auth:
        save_auth_state()
    else:
        run_parser(use_auth=args.auth, headless=not args.visible)


if __name__ == "__main__":
    main()
