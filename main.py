"""Точка входа — запуск автоматического прохождения тестов."""

import sys
from urllib.parse import urlparse

import config
from bot.auth import AuthManager
from bot.browser import BrowserManager
from bot.test_solver import TestSolver

logger = config.setup_logging()


def _extract_base_url(url: str) -> str:
    """Извлечь базовый URL (scheme + netloc) из полного URL.

    Args:
        url: Полный URL.

    Returns:
        Базовый URL вида https://example.com.
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def main() -> None:
    """Основной цикл программы."""
    logger.info("=" * 60)
    logger.info("Запуск автоматизации тестов")
    logger.info("=" * 60)

    if not config.TEST_URLS:
        logger.error("Список TEST_URLS пуст — нечего проходить. Проверьте .env")
        sys.exit(1)

    logger.info("Тестов к прохождению: %d", len(config.TEST_URLS))
    for i, url in enumerate(config.TEST_URLS, start=1):
        logger.info("  %d. %s", i, url)

    browser = BrowserManager()
    driver = None

    try:
        driver = browser.start()

        # Авторизация — используем домен первого теста
        base_url = _extract_base_url(config.TEST_URLS[0])
        auth = AuthManager(driver)

        if not auth.ensure_logged_in(base_url):
            logger.error("Авторизация не удалась — завершаю работу")
            sys.exit(1)

        # Прохождение тестов
        solver = TestSolver(driver)

        for idx, test_url in enumerate(config.TEST_URLS, start=1):
            logger.info("─" * 60)
            logger.info("Тест %d/%d: %s", idx, len(config.TEST_URLS), test_url)
            logger.info("─" * 60)

            try:
                solver.solve(test_url)
            except KeyboardInterrupt:
                logger.info("Прервано пользователем (Ctrl+C)")
                break
            except Exception:
                logger.exception("Ошибка при прохождении теста: %s", test_url)
                continue

        logger.info("Все тесты обработаны")

    except KeyboardInterrupt:
        logger.info("Прервано пользователем (Ctrl+C)")
    except Exception:
        logger.exception("Критическая ошибка")
        sys.exit(1)
    finally:
        if driver and not config.TEST_MODE:
            browser.quit()
        elif config.TEST_MODE:
            logger.info("ТЕСТОВЫЙ РЕЖИМ: браузер остаётся открытым")

    logger.info("Программа завершена")


if __name__ == "__main__":
    main()
