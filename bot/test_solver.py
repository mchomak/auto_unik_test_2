"""Логика прохождения тестов с использованием расширения SyncShare."""

import logging
import time
from typing import List, Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

logger = logging.getLogger("test_automation")

# ID кнопки «Пройти тест» (Moodle quiz)
START_BUTTON_ID = "single_button699367099b08216"

# ID кнопки навигации «Следующая страница» / «Закончить попытку»
NEXT_BUTTON_ID = "mod_quiz-next-nav"

# Ключевые слова кнопки завершения
FINISH_KEYWORDS = ("Закончить", "Завершить", "Finish", "Submit")


class TestSolver:
    """Автоматическое прохождение теста с помощью рекомендаций SyncShare.

    Attributes:
        driver: Экземпляр WebDriver.
        wait: Объект WebDriverWait.
    """

    def __init__(self, driver: webdriver.Chrome) -> None:
        self.driver = driver
        self.wait = WebDriverWait(driver, config.WAIT_TIMEOUT)

    # ── публичный API ─────────────────────────────────────────────────

    def solve(self, test_url: str) -> None:
        """Пройти один тест от начала до конца.

        Args:
            test_url: URL страницы теста.
        """
        logger.info("Открываю тест: %s", test_url)
        self.driver.get(test_url)

        if not self._click_start_button():
            logger.error("Не удалось начать тест — кнопка старта не найдена")
            return

        question_num = 0
        while True:
            question_num += 1
            logger.info("── Вопрос %d ──", question_num)

            # Обработать кнопки расширения SyncShare
            ext_buttons = self._find_extension_buttons()
            logger.info("Найдено кнопок расширения: %d", len(ext_buttons))

            for idx, btn in enumerate(ext_buttons, start=1):
                self._process_extension_button(btn, idx)

            # Определить действие кнопки навигации
            should_stop = self._handle_navigation()
            if should_stop:
                break

            time.sleep(config.QUESTION_DELAY)

        logger.info("Тест завершён: %s", test_url)

    # ── навигация ─────────────────────────────────────────────────────

    def _click_start_button(self) -> bool:
        """Найти и нажать кнопку «Пройти тест».

        Returns:
            True, если кнопка найдена и нажата.
        """
        try:
            btn = self.wait.until(
                EC.element_to_be_clickable((By.ID, START_BUTTON_ID))
            )
            btn.click()
            logger.info("Кнопка «Пройти тест» нажата")
            return True
        except TimeoutException:
            # Возможно, тест уже начат — попробуем найти кнопку навигации
            try:
                self.driver.find_element(By.ID, NEXT_BUTTON_ID)
                logger.info("Тест уже начат — кнопка навигации обнаружена")
                return True
            except NoSuchElementException:
                pass

            # Попробовать универсальные селекторы
            try:
                btn = self.driver.find_element(
                    By.XPATH,
                    "//button[contains(text(), 'Пройти тест')] "
                    "| //input[@value='Пройти тест'] "
                    "| //button[contains(text(), 'Attempt quiz')]"
                )
                btn.click()
                logger.info("Кнопка «Пройти тест» (универсальный поиск) нажата")
                return True
            except NoSuchElementException:
                return False

    def _handle_navigation(self) -> bool:
        """Обработать кнопку навигации (следующий вопрос / завершение).

        Returns:
            True, если тест завершён и цикл нужно остановить.
        """
        try:
            next_btn = self.wait.until(
                EC.element_to_be_clickable((By.ID, NEXT_BUTTON_ID))
            )
        except TimeoutException:
            logger.warning("Кнопка навигации не найдена — завершаю")
            return True

        button_text = (
            next_btn.get_attribute("value")
            or next_btn.text
            or ""
        )
        is_finish = any(kw in button_text for kw in FINISH_KEYWORDS)

        if is_finish and config.TEST_MODE:
            logger.info(
                "ТЕСТОВЫЙ РЕЖИМ: обнаружена кнопка «%s» — браузер остаётся открытым",
                button_text,
            )
            input("Нажмите Enter для продолжения...")
            return True

        next_btn.click()
        logger.info("Нажата кнопка: «%s»", button_text)

        return is_finish

    # ── работа с расширением SyncShare ────────────────────────────────

    def _find_extension_buttons(self) -> List[WebElement]:
        """Найти все кнопки расширения SyncShare на текущей странице.

        Кнопки расширения — элементы <span> с id начинающимся на 'yui_',
        содержащие подменю с рекомендациями.

        Returns:
            Список WebElement кнопок расширения.
        """
        # Дождаться загрузки страницы
        time.sleep(1)

        candidates: List[WebElement] = self.driver.find_elements(
            By.XPATH, "//span[starts-with(@id, 'yui_')]"
        )

        buttons: List[WebElement] = []
        for el in candidates:
            if self._is_extension_button(el):
                buttons.append(el)

        return buttons

    @staticmethod
    def _is_extension_button(element: WebElement) -> bool:
        """Проверить, является ли элемент кнопкой расширения SyncShare.

        Args:
            element: WebElement для проверки.

        Returns:
            True, если элемент содержит подменю рекомендаций.
        """
        try:
            inner_html = element.get_attribute("innerHTML") or ""
            return "item-label" in inner_html or "Рекомендации" in inner_html
        except StaleElementReferenceException:
            return False

    def _process_extension_button(self, button: WebElement, index: int) -> None:
        """Обработать одну кнопку расширения: навести, выбрать рекомендацию.

        Args:
            button: WebElement кнопки расширения.
            index: Порядковый номер кнопки (для логирования).
        """
        actions = ActionChains(self.driver)

        try:
            # 1. Навести курсор на кнопку расширения
            actions.move_to_element(button).perform()
            time.sleep(0.5)

            # 2. Найти пункт «Рекомендации»
            recommendation = self._find_recommendation_item(button)
            if recommendation is None:
                logger.warning("Кнопка #%d: пункт «Рекомендации» не найден", index)
                return

            # 3. Навести на «Рекомендации» для открытия подменю
            ActionChains(self.driver).move_to_element(recommendation).perform()
            time.sleep(0.5)

            # 4. Выбрать лучший ответ из подменю
            answer = self._select_best_answer()
            if answer is None:
                logger.warning("Кнопка #%d: варианты ответов не найдены", index)
                return

            answer_text = answer.text.strip()
            answer.click()
            time.sleep(0.5)

            logger.info("Кнопка #%d: выбран ответ «%s»", index, answer_text)

        except StaleElementReferenceException:
            logger.warning("Кнопка #%d: элемент устарел (StaleElement)", index)
        except Exception:
            logger.exception("Кнопка #%d: ошибка при обработке", index)

    def _find_recommendation_item(self, button: WebElement) -> Optional[WebElement]:
        """Найти пункт меню «Рекомендации» внутри кнопки расширения.

        Args:
            button: WebElement кнопки расширения.

        Returns:
            WebElement пункта «Рекомендации» или None.
        """
        try:
            return button.find_element(By.CLASS_NAME, "item-label")
        except NoSuchElementException:
            pass

        # Fallback: поиск по тексту
        try:
            return button.find_element(
                By.XPATH, ".//*[contains(text(), 'Рекомендации')]"
            )
        except NoSuchElementException:
            return None

    def _select_best_answer(self) -> Optional[WebElement]:
        """Выбрать лучший ответ из подменю расширения.

        Ищем подменю (ul.sub-menu) и берём первый пункт — расширение
        сортирует ответы по убыванию вероятности.

        Returns:
            WebElement выбранного ответа или None.
        """
        try:
            submenu = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.sub-menu"))
            )
        except TimeoutException:
            logger.debug("Подменю ul.sub-menu не появилось")
            return None

        items: List[WebElement] = submenu.find_elements(
            By.CSS_SELECTOR, "li.menu-item span.item-label"
        )

        if not items:
            # Fallback: все li внутри подменю
            items = submenu.find_elements(By.CSS_SELECTOR, "li")

        if items:
            logger.debug(
                "Найдено %d вариантов ответа, выбираю первый: «%s»",
                len(items),
                items[0].text.strip(),
            )
            return items[0]

        return None
