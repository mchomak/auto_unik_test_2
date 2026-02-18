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

# ID кнопки навигации «Следующая страница» / «Закончить попытку»
NEXT_BUTTON_ID = "mod_quiz-next-nav"

# Ключевые слова кнопки завершения
FINISH_KEYWORDS = ("Закончить", "Завершить", "Finish", "Submit")

# Максимальное время ожидания появления кнопок расширения (сек)
EXTENSION_WAIT = 15


class TestSolver:
    """Автоматическое прохождение теста с помощью рекомендаций SyncShare.

    Расширение SyncShare создаёт свои элементы (кнопки-«палочки» и
    контекстные меню) внутри shadow DOM.  Для доступа к ним используются
    JavaScript-запросы через ``execute_script``.
    """

    def __init__(self, driver: webdriver.Chrome) -> None:
        self.driver = driver
        self.wait = WebDriverWait(driver, config.WAIT_TIMEOUT)

    # ── публичный API ─────────────────────────────────────────────────

    def solve(self, test_url: str) -> None:
        """Пройти один тест от начала до конца."""
        logger.info("Открываю тест: %s", test_url)
        self.driver.get(test_url)

        if not self._click_start_button():
            logger.error("Не удалось начать тест — кнопка старта не найдена")
            return

        question_num = 0
        while True:
            question_num += 1
            logger.info("── Вопрос %d ──", question_num)

            # Найти кнопки расширения внутри shadow DOM
            ext_buttons = self._find_extension_buttons()
            logger.info("Найдено кнопок расширения: %d", len(ext_buttons))

            for idx, btn in enumerate(ext_buttons, start=1):
                self._process_extension_button(btn, idx)

            should_stop = self._handle_navigation()
            if should_stop:
                break

            time.sleep(config.QUESTION_DELAY)

        logger.info("Тест завершён: %s", test_url)

    # ── навигация ─────────────────────────────────────────────────────

    def _click_start_button(self) -> bool:
        """Найти и нажать кнопку «Пройти тест»."""
        selectors = [
            "//button[contains(text(), 'Пройти тест')]",
            "//input[@value='Пройти тест']",
            "//button[contains(text(), 'Attempt quiz')]",
            "//button[contains(text(), 'Продолжить попытку')]",
            "//button[contains(text(), 'Continue your attempt')]",
            "//button[contains(text(), 'Начать попытку')]",
            "//input[contains(@value, 'Пройти тест')]",
        ]
        try:
            for xpath in selectors:
                try:
                    btn = self.driver.find_element(By.XPATH, xpath)
                    btn.click()
                    logger.info("Кнопка старта нажата")
                    return True
                except NoSuchElementException:
                    continue

            # Попробуем кнопку по типу submit
            btn = self.wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "form button[type='submit'], form input[type='submit']")
                )
            )
            btn.click()
            logger.info("Кнопка старта (submit) нажата")
            return True
        except TimeoutException:
            pass

        # Возможно, тест уже начат
        try:
            self.driver.find_element(By.ID, NEXT_BUTTON_ID)
            logger.info("Тест уже начат — кнопка навигации обнаружена")
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

        button_text = next_btn.get_attribute("value") or next_btn.text or ""
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

    # ── работа с расширением SyncShare (shadow DOM) ───────────────────

    def _find_extension_buttons(self) -> List[WebElement]:
        """Найти все кнопки-«палочки» расширения SyncShare.

        Кнопки расширения (span.icon с SVG) находятся внутри
        open shadow root элементов вопросов.  Метод ждёт до
        EXTENSION_WAIT секунд, пока расширение обработает страницу.

        Returns:
            Список WebElement иконок расширения.
        """
        js_find_icons = """
            const icons = [];
            document.querySelectorAll('div.que').forEach(q => {
                q.querySelectorAll('*').forEach(el => {
                    if (el.shadowRoot) {
                        const icon = el.shadowRoot.querySelector('span.icon');
                        if (icon) icons.push(icon);
                    }
                });
            });
            return icons;
        """

        elapsed = 0
        poll = 1
        while elapsed < EXTENSION_WAIT:
            icons = self.driver.execute_script(js_find_icons) or []
            if icons:
                return icons
            time.sleep(poll)
            elapsed += poll

        logger.warning(
            "Кнопки расширения не найдены за %d сек. "
            "Расширение могло не получить рекомендации для этого вопроса.",
            EXTENSION_WAIT,
        )
        return []

    def _process_extension_button(self, icon: WebElement, index: int) -> None:
        """Кликнуть кнопку расширения и выбрать рекомендованный ответ.

        1. Кликнуть иконку → появится контекстное меню (в shadow DOM на body).
        2. Найти пункт «Рекомендации» → навести → открыть подменю.
        3. Кликнуть первый вариант (расширение сортирует по убыванию уверенности).
        """
        try:
            icon.click()
            time.sleep(0.5)

            # Найти видимое контекстное меню в shadow root на body
            rec_item = self._find_recommendations_item()
            if rec_item is None:
                logger.warning("Кнопка #%d: пункт «Рекомендации» не найден", index)
                self._hide_context_menu()
                return

            # Навести курсор на «Рекомендации» чтобы появилось подменю
            ActionChains(self.driver).move_to_element(rec_item).perform()
            time.sleep(0.5)

            # Принудительно показать подменю (на случай если hover не сработал)
            self.driver.execute_script("""
                const sub = arguments[0].querySelector('ul.sub-menu');
                if (sub) sub.style.setProperty('display', 'flex', 'important');
            """, rec_item)
            time.sleep(0.3)

            # Выбрать лучший ответ из подменю
            answer = self._select_best_answer(rec_item)
            if answer is None:
                logger.warning("Кнопка #%d: варианты ответов не найдены", index)
                self._hide_context_menu()
                return

            answer_text = self.driver.execute_script(
                "return (arguments[0].querySelector('span.item-label') || arguments[0]).textContent;",
                answer,
            )
            answer.click()
            time.sleep(0.5)

            logger.info("Кнопка #%d: выбран ответ «%s»", index, (answer_text or "").strip())

        except StaleElementReferenceException:
            logger.warning("Кнопка #%d: элемент устарел (StaleElement)", index)
        except Exception:
            logger.exception("Кнопка #%d: ошибка при обработке", index)

    def _find_recommendations_item(self) -> Optional[WebElement]:
        """Найти пункт «Рекомендации» в контекстном меню расширения.

        Контекстное меню (ul.syncshare-cm) находится в shadow root
        на document.body.  Ищем видимое (не hidden) меню и внутри —
        пункт со словом «Рекомендации» или иконкой «bolt».

        Returns:
            WebElement пункта «Рекомендации» или None.
        """
        result = self.driver.execute_script("""
            const root = document.body.shadowRoot;
            if (!root) return null;

            // Найти видимое меню
            const menus = root.querySelectorAll('ul.syncshare-cm');
            let visibleMenu = null;
            for (const m of menus) {
                if (!m.hidden) { visibleMenu = m; break; }
            }
            if (!visibleMenu) return null;

            // Найти пункт «Рекомендации»
            const items = visibleMenu.querySelectorAll(':scope > li.menu-item');
            for (const item of items) {
                const label = item.querySelector('span.item-label');
                if (!label) continue;
                const text = label.textContent || '';
                if (text.includes('Рекомендации') || text.includes('Recommendations')
                    || text.includes('Suggestions')) {
                    return item;
                }
            }

            // Fallback: пункт с иконкой bolt (⚡)
            for (const item of items) {
                const svg = item.querySelector('svg');
                if (svg && svg.innerHTML.includes('bolt')) return item;
            }

            // Fallback: первый пункт с подменю
            for (const item of items) {
                if (item.querySelector('ul.sub-menu')) return item;
            }

            return null;
        """)
        return result

    def _select_best_answer(self, rec_item: WebElement) -> Optional[WebElement]:
        """Выбрать лучший ответ из подменю «Рекомендации».

        Расширение сортирует варианты по убыванию уверенности,
        поэтому первый пункт — лучший.

        Args:
            rec_item: WebElement пункта меню «Рекомендации».

        Returns:
            WebElement лучшего варианта или None.
        """
        items = self.driver.execute_script("""
            const sub = arguments[0].querySelector('ul.sub-menu');
            if (!sub) return [];
            return Array.from(sub.querySelectorAll(':scope > li.menu-item'));
        """, rec_item)

        if not items:
            return None

        # Первый пункт — лучший ответ (наибольшая уверенность)
        return items[0]

    def _hide_context_menu(self) -> None:
        """Скрыть все открытые контекстные меню расширения."""
        self.driver.execute_script("""
            const root = document.body.shadowRoot;
            if (!root) return;
            root.querySelectorAll('ul.syncshare-cm').forEach(m => {
                m.hidden = true;
                m.style.setProperty('display', 'none', 'important');
            });
        """)