import csv
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


OUTPUT_DIR = Path(__file__).resolve().parent
CSV_PATH = OUTPUT_DIR / "yandex_music_tracks.csv"
AUTH_STATE_PATH = OUTPUT_DIR / "yandex_music_auth_state.json"

# URL для парсинга (плейлист)
CHART_URL = "https://music.yandex.ru/playlists/lk.0c977663-be2c-4be3-b48c-f12ff1fbea57"

PAGINATION_MAX_SCROLLS = 100  # max scroll attempts to avoid infinite loop
SCROLL_PAUSE_SEC = 0.8
NO_NEW_CONTENT_SCROLLS = 5  # stop after this many scrolls with no new tracks
SCROLL_STEP_PX = (
    350  # scroll by this many px per step (virtualized list needs small steps)
)


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


def scroll_one_step(page, step_px=SCROLL_STEP_PX, headless=True):
    """
    Прокручивает страницу или внутренний контейнер на step_px пикселей вниз.
    Возвращает True, если ещё есть куда крутить, False если уже внизу.
    Небольшие шаги нужны для виртуализированных списков — иначе в DOM только последние элементы.
    """
    behavior = "smooth" if not headless else "auto"
    result = page.evaluate(
        """
        ([stepPx, behavior]) => {
            // Сначала пробуем внутренний контейнер со списком треков
            const container = document.querySelector('[data-scroll-id^="scroll-container-"]');
            if (container) {
                const before = container.scrollTop;
                const maxScroll = container.scrollHeight - container.clientHeight;
                if (maxScroll <= 0) return { atBottom: true, scrolled: false };
                const next = Math.min(before + stepPx, maxScroll);
                container.scrollTo({ top: next, behavior });
                return { atBottom: next >= maxScroll - 2, scrolled: true };
            }
            // Fallback: прокрутка окна
            const doc = document.documentElement;
            const before = window.scrollY || doc.scrollTop;
            const maxScroll = Math.max(doc.scrollHeight, document.body.scrollHeight) - window.innerHeight;
            if (maxScroll <= 0) return { atBottom: true, scrolled: false };
            const next = Math.min(before + stepPx, maxScroll);
            window.scrollTo({ top: next, behavior });
            return { atBottom: next >= maxScroll - 2, scrolled: true };
        }
        """,
        [step_px, behavior],
    )
    return result.get("atBottom", True)


def scroll_for_pagination(page, scroll_count=1, pause=SCROLL_PAUSE_SEC, headless=True):
    """Делает scroll_count шагов прокрутки (каждый шаг = SCROLL_STEP_PX)."""
    for _ in range(scroll_count):
        scroll_one_step(page, step_px=SCROLL_STEP_PX, headless=headless)
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


def run_parser(use_auth=False, headless=True, playlist_url=None, save_csv=True):
    """
    Запуск парсера. playlist_url — ссылка на плейлист Яндекс.Музыки;
    если не передана, используется CHART_URL по умолчанию.
    save_csv — сохранять ли результат в CSV (при вызове из API можно False).
    """
    url = (playlist_url or CHART_URL).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    all_tracks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_options = {"viewport": {"width": 1280, "height": 720}}
        if use_auth and AUTH_STATE_PATH.exists():
            context_options["storage_state"] = str(AUTH_STATE_PATH)
        context = browser.new_context(**context_options)
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            print(
                "Таймаут загрузки страницы. Возможна блокировка по региону или нужна авторизация."
            )

        time.sleep(2)
        try:
            page.wait_for_selector('a[href*="/track/"]', timeout=10000)
        except PlaywrightTimeout:
            pass

        _set_scroll_markers(page)

        accumulated = []
        seen_keys = set()
        no_new_count = 0
        at_bottom = False
        for _ in range(PAGINATION_MAX_SCROLLS):
            at_bottom = scroll_one_step(page, step_px=SCROLL_STEP_PX, headless=headless)
            time.sleep(SCROLL_PAUSE_SEC)
            tracks = extract_tracks_via_js(page)
            new_in_step = 0
            for t in tracks:
                key = (t.get("title") or "", t.get("artists") or "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                accumulated.append(t)
                new_in_step += 1
            if new_in_step == 0:
                no_new_count += 1
                if no_new_count >= NO_NEW_CONTENT_SCROLLS:
                    break
            else:
                no_new_count = 0
            if at_bottom and len(accumulated) > 0:
                break

        all_tracks = [{**t, "position": i + 1} for i, t in enumerate(accumulated)]

        if save_csv:
            save_to_csv(all_tracks, CSV_PATH)
        else:
            print(f"Треков распознано: {len(all_tracks)}")

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
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Не сохранять результат в CSV (только вывести количество треков)",
    )
    args = parser.parse_args()
    if args.save_auth:
        save_auth_state()
    else:
        run_parser(
            use_auth=args.auth,
            headless=not args.visible,
            save_csv=not args.no_csv,
        )


if __name__ == "__main__":
    main()
