"""Ручная авторизация — открывает браузер для входа и сохраняет cookies.

Использование:
    python save_cookies.py [URL]

Если URL не указан, используется домен первого теста из TEST_URLS в .env.
После запуска:
    1. Откроется браузер Chrome с расширением SyncShare.
    2. Войдите в систему вручную.
    3. Вернитесь в терминал и нажмите Enter.
    4. Cookies будут сохранены в файл (COOKIES_FILE из .env).
"""

import pickle
import sys
from pathlib import Path
from urllib.parse import urlparse

import config
from bot.browser import BrowserManager

logger = config.setup_logging()


def main() -> None:
    """Запустить браузер, дождаться ручного логина, сохранить cookies."""

    # Определить URL для открытия
    if len(sys.argv) > 1:
        url = sys.argv[1]
    elif config.TEST_URLS:
        parsed = urlparse(config.TEST_URLS[0])
        url = f"{parsed.scheme}://{parsed.netloc}"
    else:
        logger.error("Укажите URL аргументом или заполните TEST_URLS в .env")
        sys.exit(1)

    logger.info("Открываю браузер для ручной авторизации...")
    logger.info("URL: %s", url)

    browser = BrowserManager()
    driver = browser.start()

    try:
        driver.get(url)

        print()
        print("=" * 60)
        print("  Браузер открыт. Войдите в систему вручную.")
        print("  После успешного входа вернитесь сюда")
        print("  и нажмите Enter для сохранения cookies.")
        print("=" * 60)
        print()
        input(">>> Нажмите Enter после авторизации... ")

        # Сохранить cookies
        cookies = driver.get_cookies()
        cookies_path = Path(config.COOKIES_FILE)
        cookies_path.write_bytes(pickle.dumps(cookies))

        logger.info("Сохранено %d cookies в %s", len(cookies), cookies_path)
        print(f"\nCookies сохранены: {cookies_path.resolve()} ({len(cookies)} шт.)")

    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
    except Exception:
        logger.exception("Ошибка при сохранении cookies")
        sys.exit(1)
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
