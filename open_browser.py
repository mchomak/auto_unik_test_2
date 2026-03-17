"""Открыть браузер с расширением на сайте и подождать 30 секунд.

Использование:
    python open_browser.py
"""

import time

import config
from bot.browser import BrowserManager

logger = config.setup_logging()

URL = "https://lms.mospolytech.ru/"
WAIT = 30


def main() -> None:
    browser = BrowserManager()
    driver = browser.start()

    try:
        logger.info("Открываю %s ...", URL)
        driver.get(URL)
        logger.info("Текущий URL: %s", driver.current_url)

        print()
        print("=" * 60)
        print(f"  Браузер открыт. Текущий URL: {driver.current_url}")
        print(f"  Ожидание {WAIT} секунд...")
        print("=" * 60)

        for i in range(WAIT, 0, -1):
            print(f"\r  Осталось: {i} сек   ", end="", flush=True)
            time.sleep(1)

        print()
        logger.info("Итоговый URL: %s", driver.current_url)
        logger.info("Заголовок страницы: %s", driver.title)

        print()
        print("=" * 60)
        print(f"  Итоговый URL:     {driver.current_url}")
        print(f"  Заголовок:        {driver.title}")
        print("=" * 60)

    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
    except Exception:
        logger.exception("Ошибка")
    finally:
        input("\nНажмите Enter чтобы закрыть браузер... ")
        browser.quit()


if __name__ == "__main__":
    main()
