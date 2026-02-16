"""Авторизация на платформе и управление cookies."""

import logging
import pickle
from pathlib import Path
from typing import List, Dict, Any

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

logger = logging.getLogger("test_automation")


class AuthManager:
    """Управление авторизацией: cookies, логин/пароль.

    Attributes:
        driver: Экземпляр WebDriver.
        wait: Объект WebDriverWait с таймаутом из конфигурации.
    """

    def __init__(self, driver: webdriver.Chrome) -> None:
        self.driver = driver
        self.wait = WebDriverWait(driver, config.WAIT_TIMEOUT)
        self._cookies_path = Path(config.COOKIES_FILE)

    # ── публичный API ─────────────────────────────────────────────────

    def ensure_logged_in(self, check_url: str) -> bool:
        """Убедиться, что пользователь авторизован.

        Загружает cookies (если есть), затем переходит на check_url
        и проверяет, не появилась ли форма логина. Если cookies
        невалидны — выполняет автоматический логин.

        Args:
            check_url: URL, требующий авторизации (реальная страница теста).
                       Используется и для привязки cookies к домену,
                       и для проверки валидности сессии.

        Returns:
            True, если авторизация успешна.
        """
        # Открыть URL, чтобы cookies привязались к домену
        self.driver.get(check_url)

        if self._load_cookies():
            # Перейти на целевую страницу — именно она покажет,
            # валидна ли сессия (сервер может редиректнуть на логин)
            self.driver.get(check_url)

            if self._is_logged_in():
                logger.info("Авторизация через cookies успешна")
                return True
            logger.warning("Cookies загружены, но сессия невалидна — выполняю логин")

        return self._perform_login()

    # ── приватные методы ──────────────────────────────────────────────

    def _load_cookies(self) -> bool:
        """Загрузить cookies из файла.

        Returns:
            True, если cookies успешно загружены.
        """
        if not self._cookies_path.exists():
            logger.debug("Файл cookies не найден: %s", self._cookies_path)
            return False

        try:
            cookies: List[Dict[str, Any]] = pickle.loads(
                self._cookies_path.read_bytes()
            )
            for cookie in cookies:
                # Selenium не принимает некоторые атрибуты
                cookie.pop("sameSite", None)
                cookie.pop("httpOnly", None)
                try:
                    self.driver.add_cookie(cookie)
                except Exception:
                    logger.debug("Пропущена cookie: %s", cookie.get("name"))
            logger.debug("Загружено %d cookies из файла", len(cookies))
            return True
        except Exception:
            logger.warning("Не удалось загрузить cookies", exc_info=True)
            return False

    def _save_cookies(self) -> None:
        """Сохранить текущие cookies в файл."""
        try:
            cookies = self.driver.get_cookies()
            self._cookies_path.write_bytes(pickle.dumps(cookies))
            logger.info("Cookies сохранены в %s (%d шт.)", self._cookies_path, len(cookies))
        except Exception:
            logger.warning("Не удалось сохранить cookies", exc_info=True)

    def _is_logged_in(self) -> bool:
        """Проверить, авторизован ли пользователь.

        Комбинированная эвристика:
        1. Если URL содержит login/auth — сервер перенаправил на логин.
        2. Если на странице есть форма с полем пароля — не авторизован.

        Returns:
            True, если пользователь авторизован.
        """
        current_url = self.driver.current_url.lower()
        login_indicators = ("login", "/auth", "signin", "sign-in", "logon")
        if any(indicator in current_url for indicator in login_indicators):
            logger.debug("URL содержит признак страницы логина: %s", current_url)
            return False

        try:
            self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            return False  # Форма логина видна → не авторизован
        except NoSuchElementException:
            return True  # Формы нет → авторизован

    def _perform_login(self) -> bool:
        """Выполнить авторизацию через форму логина.

        Returns:
            True, если логин успешен.
        """
        logger.info("Начинаю авторизацию через форму логина")

        try:
            # Поле логина
            login_field = self.wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input[type='text'], input[type='email'], input[name='username']"
                ))
            )
            login_field.clear()
            login_field.send_keys(config.LOGIN)
            logger.debug("Логин введён")

            # Поле пароля
            password_field = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='password']"
            )
            password_field.clear()
            password_field.send_keys(config.PASSWORD)
            logger.debug("Пароль введён")

            # Кнопка «Войти»
            submit_button = self._find_submit_button()
            submit_button.click()
            logger.debug("Кнопка «Войти» нажата")

            # Дождаться, пока форма логина исчезнет
            self.wait.until(
                EC.invisibility_of_element_located((
                    By.CSS_SELECTOR, "input[type='password']"
                ))
            )

            if self._is_logged_in():
                logger.info("Авторизация прошла успешно")
                self._save_cookies()
                return True

            logger.error("Авторизация не удалась: форма логина всё ещё видна")
            return False

        except TimeoutException:
            logger.error("Таймаут при авторизации — элементы формы не найдены")
            return False
        except Exception:
            logger.exception("Ошибка при авторизации")
            return False

    def _find_submit_button(self):
        """Найти кнопку отправки формы.

        Ищем по приоритету:
        1. button[type='submit']
        2. input[type='submit']
        3. Кнопка с текстом «Войти» / «Login» / «Вход»

        Returns:
            WebElement кнопки.

        Raises:
            NoSuchElementException: Если кнопка не найдена.
        """
        # type=submit
        selectors = [
            "button[type='submit']",
            "input[type='submit']",
        ]
        for sel in selectors:
            try:
                return self.driver.find_element(By.CSS_SELECTOR, sel)
            except NoSuchElementException:
                continue

        # По тексту
        keywords = ["Войти", "Login", "Вход", "Sign in", "Log in"]
        for kw in keywords:
            try:
                return self.driver.find_element(
                    By.XPATH, f"//button[contains(text(), '{kw}')]"
                )
            except NoSuchElementException:
                continue

        raise NoSuchElementException(
            "Не удалось найти кнопку «Войти» на странице"
        )