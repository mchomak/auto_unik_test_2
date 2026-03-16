"""Authentication and cookie management for lms.mospolytech.ru."""

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

logger = logging.getLogger("test_automation")

# Moodle's standard login page path (used for direct navigation, avoiding SSO loops)
_MOODLE_LOGIN_PATH = "/login/index.php"


class AuthManager:
    """Manage authentication: cookies, form login, session validation.

    Attributes:
        driver: Chrome WebDriver instance.
        wait: WebDriverWait with timeout from config.
    """

    def __init__(self, driver: webdriver.Chrome) -> None:
        self.driver = driver
        self.wait = WebDriverWait(driver, config.WAIT_TIMEOUT)
        self._cookies_path = Path(config.COOKIES_FILE)

    # ── public API ────────────────────────────────────────────────────

    def ensure_logged_in(self, check_url: str) -> bool:
        """Ensure the user is authenticated before accessing check_url.

        Strategy:
        1. Navigate to the BASE DOMAIN (homepage) — not check_url.
           Going directly to a protected URL triggers the SSO redirect chain
           and leaves SSO-state cookies in the browser.  Adding saved cookies
           on top of those state cookies causes ERR_TOO_MANY_REDIRECTS on the
           second navigation.
        2. Clear all existing cookies, then load saved cookies.
        3. Navigate to check_url once, with a clean cookie jar.
        4. If a redirect loop still occurs, catch it and fall back to a
           direct form login (bypassing SSO redirect entirely).

        Args:
            check_url: A protected URL that requires authentication.

        Returns:
            True if authentication succeeded.
        """
        base_url = _base_url(check_url)
        login_url = base_url + _MOODLE_LOGIN_PATH

        logger.info("Auth start | target: %s", check_url)

        # Step 1: land on the base domain to set up a cookie context
        # without triggering the SSO redirect chain.
        self._navigate_safe(base_url)
        logger.debug("Base domain loaded | url: %s", self.driver.current_url)

        if self._load_cookies():
            # Step 2: try the protected URL with saved session cookies
            success = self._navigate_safe(check_url)
            logger.info("After cookie restore | url: %s", self.driver.current_url)

            if success and self._is_logged_in():
                logger.info("Auth via saved cookies: SUCCESS")
                return True

            logger.warning(
                "Saved cookies did not produce a valid session "
                "(url=%s) — falling back to form login",
                self.driver.current_url,
            )
            # Wipe everything before attempting a fresh login
            self.driver.delete_all_cookies()

        # Step 3: go directly to Moodle's login page — no SSO redirect chain
        self._navigate_safe(login_url)
        logger.debug("Login page loaded | url: %s", self.driver.current_url)

        return self._perform_login(return_url=check_url)

    # ── private methods ───────────────────────────────────────────────

    def _navigate_safe(self, url: str) -> bool:
        """Navigate to url, recovering from ERR_TOO_MANY_REDIRECTS.

        If a redirect loop is detected, all cookies are cleared and
        navigation is retried once from scratch.

        Args:
            url: Target URL.

        Returns:
            True if navigation completed without a redirect-loop error.
        """
        try:
            self.driver.get(url)
            return True
        except WebDriverException as exc:
            err = str(exc)
            if "ERR_TOO_MANY_REDIRECTS" in err or "too many redirects" in err.lower():
                logger.warning(
                    "ERR_TOO_MANY_REDIRECTS on %s — "
                    "clearing cookies and retrying once",
                    url,
                )
                try:
                    self.driver.delete_all_cookies()
                    self.driver.get(url)
                    return True
                except WebDriverException:
                    logger.error(
                        "Redirect loop persists after cookie clear for %s", url
                    )
                    return False
            raise

    def _load_cookies(self) -> bool:
        """Load cookies from the pickle file into the browser.

        Clears ALL existing browser cookies first to prevent stale
        cookies from conflicting with the saved session.

        Returns:
            True if at least one cookie was added successfully.
        """
        if not self._cookies_path.exists():
            logger.debug("No cookie file found: %s", self._cookies_path)
            return False

        try:
            cookies: List[Dict[str, Any]] = pickle.loads(
                self._cookies_path.read_bytes()
            )
        except Exception:
            logger.warning("Failed to read cookie file", exc_info=True)
            return False

        # Critical: wipe the current jar before adding saved cookies.
        # Leftover browser cookies (e.g. from SSO initiation) would
        # conflict with the saved session and cause redirect loops.
        self.driver.delete_all_cookies()

        loaded = 0
        skipped = 0
        for cookie in cookies:
            # Selenium rejects these attributes; strip them before adding.
            cookie.pop("sameSite", None)
            cookie.pop("httpOnly", None)
            try:
                self.driver.add_cookie(cookie)
                loaded += 1
            except Exception as exc:
                logger.debug("Skipped cookie %r: %s", cookie.get("name"), exc)
                skipped += 1

        domains = {c.get("domain") for c in self.driver.get_cookies()}
        logger.info(
            "Cookies restored: %d loaded, %d skipped | domains: %s",
            loaded,
            skipped,
            domains,
        )
        return loaded > 0

    def _save_cookies(self) -> None:
        """Persist current browser cookies to the pickle file."""
        try:
            cookies = self.driver.get_cookies()
            self._cookies_path.write_bytes(pickle.dumps(cookies))
            domains = {c.get("domain") for c in cookies}
            logger.info(
                "Cookies saved: %d cookies | domains: %s",
                len(cookies),
                domains,
            )
        except Exception:
            logger.warning("Failed to save cookies", exc_info=True)

    def _is_logged_in(self) -> bool:
        """Check whether the browser is currently showing an authenticated page.

        Detection strategy:
        1. URL check — Moodle's login page has a well-known path.
           Intentionally avoids broad patterns like "auth" that would
           falsely match SSO callback URLs (/auth/saml2/...).
        2. DOM check — presence of a password input indicates the login form.

        Returns:
            True if the session appears to be authenticated.
        """
        current_url = self.driver.current_url
        lower_url = current_url.lower()

        # Match Moodle's actual login page paths only
        login_paths = (
            "/login/index.php",
            "/login/index",
        )
        if any(p in lower_url for p in login_paths):
            logger.debug("Login page URL detected: %s", current_url)
            return False

        try:
            self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            logger.debug("Password field found on %s — not logged in", current_url)
            return False
        except NoSuchElementException:
            logger.debug("No password field on %s — logged in", current_url)
            return True

    def _perform_login(self, return_url: str | None = None) -> bool:
        """Fill and submit the Moodle login form.

        Expects the browser to already be on the login page.
        After a successful login Moodle redirects to the dashboard;
        if return_url is provided, we navigate there explicitly.

        Args:
            return_url: URL to navigate to after a successful login.

        Returns:
            True if login succeeded.
        """
        logger.info("Starting form login | url: %s", self.driver.current_url)

        try:
            login_field = self.wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input[type='text'], input[type='email'], input[name='username']",
                ))
            )
            login_field.clear()
            login_field.send_keys(config.LOGIN)
            logger.debug("Username entered")

            password_field = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='password']"
            )
            password_field.clear()
            password_field.send_keys(config.PASSWORD)
            logger.debug("Password entered")

            url_before = self.driver.current_url
            submit_btn = self._find_submit_button()
            submit_btn.click()
            logger.debug("Submit clicked | was at: %s", url_before)

            # Wait for the password field to disappear (form submitted / redirected)
            self.wait.until(
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, "input[type='password']")
                )
            )

            url_after_submit = self.driver.current_url
            logger.info("After submit | url: %s", url_after_submit)

            # Navigate to the intended page if Moodle landed elsewhere
            if return_url:
                self._navigate_safe(return_url)
                logger.info(
                    "Navigated to target after login | url: %s",
                    self.driver.current_url,
                )

            if self._is_logged_in():
                logger.info(
                    "Form login: SUCCESS | final url: %s",
                    self.driver.current_url,
                )
                self._save_cookies()
                return True

            logger.error(
                "Form login: FAILED | final url: %s | title: %s",
                self.driver.current_url,
                self.driver.title,
            )
            return False

        except TimeoutException:
            logger.error(
                "Login timeout — form elements not found | url: %s | title: %s",
                self.driver.current_url,
                self.driver.title,
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected login error | url: %s", self.driver.current_url
            )
            return False

    def _find_submit_button(self):
        """Locate the login form's submit button.

        Returns:
            WebElement of the submit button.

        Raises:
            NoSuchElementException: If no button is found.
        """
        for sel in ("button[type='submit']", "input[type='submit']"):
            try:
                return self.driver.find_element(By.CSS_SELECTOR, sel)
            except NoSuchElementException:
                continue

        for kw in ("Войти", "Login", "Вход", "Sign in", "Log in"):
            try:
                return self.driver.find_element(
                    By.XPATH, f"//button[contains(text(), '{kw}')]"
                )
            except NoSuchElementException:
                continue

        raise NoSuchElementException("Submit button not found on login page")


# ── helpers ───────────────────────────────────────────────────────────────────

def _base_url(url: str) -> str:
    """Extract scheme + host from a full URL."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"