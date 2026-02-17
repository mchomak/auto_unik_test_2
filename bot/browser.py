"""Инициализация браузера Chrome с расширением SyncShare."""

import json
import logging
import os
import shutil
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
        self._clean_stale_profile()

        options = self._build_options()
        service = Service()

        try:
            self._driver = webdriver.Chrome(service=service, options=options)
            self._driver.implicitly_wait(config.WAIT_TIMEOUT)
            logger.info("Браузер Chrome запущен успешно")
            self._verify_extension_loaded()
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
        """Проверить, что путь к расширению корректен, и подготовить папку.

        Удаляет папку _metadata (если есть) — Chrome молча отказывается
        загружать расширение через --load-extension, если она присутствует.
        """
        ext_path = Path(config.EXTENSION_PATH)
        if not ext_path.exists():
            raise FileNotFoundError(
                f"Путь к расширению не найден: {config.EXTENSION_PATH}\n"
                f"Убедитесь, что расширение SyncShare распаковано по указанному пути."
            )

        manifest = ext_path / "manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(
                f"Файл manifest.json не найден в {config.EXTENSION_PATH}\n"
                f"Убедитесь, что путь указывает на корневую папку расширения, "
                f"содержащую manifest.json."
            )

        # _metadata — служебная папка Chrome Web Store.
        # Если она осталась при копировании из Chrome\Extensions,
        # Chrome считает расширение «управляемым» и молча игнорирует --load-extension.
        metadata_dir = ext_path / "_metadata"
        if metadata_dir.exists():
            shutil.rmtree(metadata_dir)
            logger.info("Удалена папка _metadata из расширения (мешает загрузке)")

        # Очистка manifest.json от полей, несовместимых с --load-extension.
        # - update_url: Chrome считает расширение «из Web Store» и молча
        #   отказывается грузить его как распакованное.
        # - key: идентификатор CWS-расширения, не нужен для распакованного.
        # - browser_style: Firefox-специфичное свойство, Chrome может выдать
        #   предупреждение/ошибку при его наличии.
        self._sanitize_manifest(manifest)

        logger.info("Расширение найдено: %s (manifest.json ✓)", config.EXTENSION_PATH)

    def _clean_stale_profile(self) -> None:
        """Удалить старый профиль Chrome, если он мог закэшировать настройки без расширений."""
        profile_path = Path(config.CHROME_PROFILE_PATH)
        if profile_path.exists():
            try:
                shutil.rmtree(profile_path)
                logger.info("Старый профиль Chrome удалён: %s", profile_path)
            except Exception:
                logger.warning(
                    "Не удалось удалить профиль %s — возможно, Chrome ещё открыт. "
                    "Закройте все окна Chrome и перезапустите.",
                    profile_path,
                    exc_info=True,
                )

    @staticmethod
    def _sanitize_manifest(manifest_path: Path) -> None:
        """Удалить из manifest.json поля, мешающие загрузке через --load-extension.

        Chrome молча отказывается загружать расширение с ``update_url``,
        указывающим на Chrome Web Store, если оно подгружается как
        распакованное (--load-extension). Поле ``key`` также является
        CWS-артефактом и не нужно для локальной загрузки.
        ``browser_style`` — свойство Firefox, которое может вызвать ошибки.
        """
        try:
            text = manifest_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except Exception:
            logger.warning("Не удалось прочитать manifest.json для очистки", exc_info=True)
            return

        fields_to_remove = ("update_url", "key")
        removed = [f for f in fields_to_remove if f in data]

        # browser_style внутри action
        action = data.get("action", {})
        if "browser_style" in action:
            del action["browser_style"]
            removed.append("action.browser_style")

        if not removed:
            return

        for field in fields_to_remove:
            data.pop(field, None)

        try:
            manifest_path.write_text(
                json.dumps(data, indent=3, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "Из manifest.json удалены CWS/Firefox-поля: %s",
                ", ".join(removed),
            )
        except Exception:
            logger.warning("Не удалось обновить manifest.json", exc_info=True)

    def _verify_extension_loaded(self) -> None:
        """Проверить, что расширение реально загрузилось в Chrome."""
        try:
            self._driver.get("chrome://extensions/")
            # Дождаться загрузки страницы
            import time
            time.sleep(2)

            # extensions-manager содержит все расширения в shadow DOM
            ext_manager = self._driver.find_element(
                by="tag name", value="extensions-manager"
            )
            shadow = self._driver.execute_script(
                "return arguments[0].shadowRoot", ext_manager
            )
            items_list = shadow.find_element(by="id", value="items-list")
            shadow2 = self._driver.execute_script(
                "return arguments[0].shadowRoot", items_list
            )

            # Считаем расширения (extensions-item)
            extensions = shadow2.find_elements(by="css selector", value="extensions-item")
            ext_count = len(extensions)

            if ext_count > 0:
                logger.info("Расширений загружено в Chrome: %d", ext_count)
            else:
                logger.error(
                    "Расширение НЕ загрузилось! Проверьте:\n"
                    "  1. Удалите папку chrome_profile/ и запустите заново\n"
                    "  2. Убедитесь, что в папке расширения нет папки _metadata\n"
                    "  3. Закройте все окна Chrome перед запуском"
                )
        except Exception:
            logger.debug("Не удалось проверить расширения через chrome://extensions",
                         exc_info=True)

    def _build_options(self) -> Options:
        """Собрать ChromeOptions для запуска браузера.

        Returns:
            Настроенный объект Options.
        """
        options = Options()

        # ВАЖНО: ChromeDriver по умолчанию добавляет --disable-extensions,
        # что молча блокирует все расширения. Убираем этот флаг.
        options.add_experimental_option("excludeSwitches", [
            "enable-automation",
            "disable-extensions",
        ])

        # Расширение (на Windows заменяем \ на / для совместимости с Chrome)
        ext_abs_path = os.path.abspath(config.EXTENSION_PATH).replace("\\", "/")
        options.add_argument(f"--load-extension={ext_abs_path}")
        logger.info("Загрузка расширения: --load-extension=%s", ext_abs_path)

        # Явно разрешаем расширения
        options.add_argument("--enable-extensions")

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
            "extensions.ui.developer_mode": True,
        })

        # Игнорирование ошибок сертификатов
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")

        # Прочие полезные флаги
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")

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