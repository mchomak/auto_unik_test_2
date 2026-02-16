"""Инициализация браузера Chrome с расширением SyncShare."""

import logging
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

import config

logger = logging.getLogger("test_automation")


class BrowserManager:
    """Управление жизненным циклом браузера Chrome.

    Запускает Chrome с загруженным расширением SyncShare,
    persistent-профилем и необходимыми настройками.
    """

    def __init__(self) -> None:
        self._driver: webdriver.Chrome | None = None

    # ── публичный API ─────────────────────────────────────────────────

    def start(self) -> webdriver.Chrome:
        """Создать и вернуть экземпляр Chrome WebDriver.

        Returns:
            Инициализированный WebDriver.

        Raises:
            FileNotFoundError: Если путь к расширению не существует.
            RuntimeError: Если не удалось запустить браузер.
        """
        self._validate_extension_path()

        options = self._build_options()
        service = Service()

        try:
            self._driver = webdriver.Chrome(service=service, options=options)
            self._driver.implicitly_wait(config.WAIT_TIMEOUT)
            logger.info("Браузер Chrome запущен успешно")
            return self._driver
        except Exception as exc:
            logger.exception("Не удалось запустить браузер Chrome")
            raise RuntimeError(f"Ошибка запуска Chrome: {exc}") from exc

    def quit(self) -> None:
        """Корректно закрыть браузер."""
        if self._driver:
            try:
                self._driver.quit()
                logger.info("Браузер закрыт")
            except Exception:
                logger.warning("Ошибка при закрытии браузера", exc_info=True)
            finally:
                self._driver = None

    @property
    def driver(self) -> webdriver.Chrome | None:
        """Текущий экземпляр WebDriver (None, если не запущен)."""
        return self._driver

    # ── приватные методы ──────────────────────────────────────────────

    def _validate_extension_path(self) -> None:
        """Проверить, что путь к расширению существует."""
        ext_path = Path(config.EXTENSION_PATH)
        if not ext_path.exists():
            raise FileNotFoundError(
                f"Путь к расширению не найден: {config.EXTENSION_PATH}. "
                f"Убедитесь, что расширение SyncShare распаковано по указанному пути."
            )
        logger.debug("Расширение найдено: %s", config.EXTENSION_PATH)

    def _build_options(self) -> Options:
        """Собрать ChromeOptions для запуска браузера.

        Returns:
            Настроенный объект Options.
        """
        options = Options()

        # Расширение (headless не поддерживает расширения)
        options.add_argument(f"--load-extension={os.path.abspath(config.EXTENSION_PATH)}")

        # Persistent профиль — сохраняет cookies и данные расширения
        profile_path = os.path.abspath(config.CHROME_PROFILE_PATH)
        options.add_argument(f"--user-data-dir={profile_path}")

        # Отключение уведомлений
        options.add_argument("--disable-notifications")

        # Отключение автозаполнения
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "autofill.profile_enabled": False,
        })

        # Игнорирование ошибок сертификатов
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")

        # Прочие полезные флаги
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        # Размер окна
        options.add_argument("--start-maximized")

        if config.HEADLESS:
            logger.warning(
                "HEADLESS=true, но расширения Chrome не работают в headless-режиме. "
                "Расширение SyncShare будет недоступно."
            )
            options.add_argument("--headless=new")

        logger.debug("ChromeOptions собраны")
        return options
