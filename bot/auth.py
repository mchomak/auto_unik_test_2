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
        4. If cookies are stale, fall back to a fresh login.  Navigate to
           check_url again (not /login/index.php directly) to let Moodle's
           wantsurl flow redirect us to the login/SSO page without looping.

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

        # Step 3: navigate to check_url (not login_url directly).
        #
        # Going directly to /login/index.php can cause ERR_TOO_MANY_REDIRECTS
        # when the SSO configuration redirects /login/index.php → SSO → back
        # to /login/index.php in a loop.  Navigating to check_url goes through
        # Moodle's normal wantsurl flow, which correctly sets up the SSO
        # context and then lands on the login page / SSO provider without
        # looping.  (We already observed check_url redirecting cleanly to
        # /login/index.php with stale cookies a few lines above.)
        self._navigate_safe(check_url)
        logger.debug("After redirect | url: %s", self.driver.current_url)

        return self._perform_login(return_url=check_url)

    # ── private methods ───────────────────────────────────────────────

    def _navigate_safe(self, url: str) -> bool:
        """Navigate to url, recovering from ERR_TOO_MANY_REDIRECTS.

        ChromeDriver does NOT raise an exception for redirect loops — it
        renders the chrome-error:// page and returns normally. We therefore
        detect the condition by inspecting the resulting URL/title in
        addition to catching WebDriverException (which some driver versions
        do raise).

        If a redirect loop is detected, all cookies and browser storage are
        cleared, the browser is reset to about:blank, and navigation is
        retried once.

        Args:
            url: Target URL.

        Returns:
            True if navigation completed without a redirect-loop error.
        """
        def _is_redirect_loop() -> bool:
            try:
                cur = self.driver.current_url or ""
                if cur.startswith("chrome-error://"):
                    return True
                title = self.driver.title or ""
                if "ERR_TOO_MANY_REDIRECTS" in title or "ERR_TOO_MANY_REDIRECTS" in cur:
                    return True
                src = self.driver.page_source or ""
                if "ERR_TOO_MANY_REDIRECTS" in src:
                    return True
            except Exception:
                pass
            return False

        def _recover_and_retry() -> bool:
            logger.warning(
                "ERR_TOO_MANY_REDIRECTS on %s — "
                "clearing cookies/storage and retrying once",
                url,
            )
            try:
                self.driver.delete_all_cookies()
            except Exception:
                pass
            try:
                # Reset to a neutral page to clear Chrome's internal redirect
                # cache before the retry.
                self.driver.get("about:blank")
                try:
                    self.driver.execute_script(
                        "window.localStorage.clear(); window.sessionStorage.clear();"
                    )
                except Exception:
                    pass
                self.driver.get(url)
                if _is_redirect_loop():
                    logger.error(
                        "Redirect loop persists after cookie clear for %s", url
                    )
                    return False
                return True
            except WebDriverException:
                logger.error(
                    "Redirect loop persists after cookie clear for %s", url
                )
                return False

        try:
            self.driver.get(url)
            if _is_redirect_loop():
                return _recover_and_retry()
            return True
        except WebDriverException as exc:
            err = str(exc)
            if "ERR_TOO_MANY_REDIRECTS" in err or "too many redirects" in err.lower():
                return _recover_and_retry()
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
        """Fill and submit the Moodle login form or click SSO button.

        Expects the browser to already be on the login page.
        Detects quickly whether the page has a username/password form
        or only an SSO button.  If SSO-only, clicks the SSO button and
        waits for the external IdP to authenticate (requires valid saved
        cookies from save_cookies.py — without them the user must log in
        manually in the browser window that opens).

        Args:
            return_url: URL to navigate to after a successful login.

        Returns:
            True if login succeeded.
        """
        current = self.driver.current_url
        logger.info("Starting form login | url: %s", current)

        # After navigating to /login/index.php, Moodle may have redirected
        # us to an external SSO provider (Keycloak, ADFS, etc.).
        # Detect this: if we're no longer on the Moodle login page path.
        on_sso_provider = _MOODLE_LOGIN_PATH not in current

        if on_sso_provider:
            logger.info(
                "Redirected away from Moodle login to: %s — "
                "this is an external SSO provider page",
                current,
            )
            return self._perform_sso_provider_login(return_url)

        # Quick check (3 s) for a username field.  SSO-only pages won't have one.
        quick_wait = WebDriverWait(self.driver, 3)
        has_form = True
        try:
            quick_wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input[name='username'], input[type='email']",
                ))
            )
        except TimeoutException:
            has_form = False

        if not has_form:
            logger.info(
                "No username/password form on login page — "
                "trying SSO button (mospolytech IdP)"
            )
            return self._perform_sso_login(return_url)

        try:
            login_field = self.driver.find_element(
                By.CSS_SELECTOR,
                "input[name='username'], input[type='email']",
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

    def _perform_sso_provider_login(self, return_url: str | None = None) -> bool:
        """Handle login on an external SSO provider page (Keycloak, ADFS, etc.).

        When Moodle's /login/index.php redirects to an external IdP,
        we land on that provider's login form. This method fills in
        username/password on the SSO provider's page and submits.
        """
        current = self.driver.current_url
        logger.info("SSO provider login | url: %s", current)

        # Log page source snippet for debugging
        try:
            title = self.driver.title
            logger.info("SSO page title: %s", title)
        except Exception:
            pass

        # Wait up to 10 s for any login form on the SSO provider page
        sso_wait = WebDriverWait(self.driver, 10)
        try:
            sso_wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input[name='username'], input[name='login'], "
                    "input[type='email'], input[id='username'], "
                    "input[id='login-username'], input[name='UserName']",
                ))
            )
        except TimeoutException:
            logger.error(
                "No login form found on SSO provider page: %s\n"
                "  → Запустите save_cookies.py, войдите вручную и повторите запуск бота.",
                current,
            )
            return False

        # Find username field (try multiple common SSO form field names)
        login_field = None
        for sel in [
            "input[name='username']", "input[name='login']",
            "input[type='email']", "input[id='username']",
            "input[id='login-username']", "input[name='UserName']",
        ]:
            try:
                login_field = self.driver.find_element(By.CSS_SELECTOR, sel)
                logger.info("SSO username field found: %s", sel)
                break
            except NoSuchElementException:
                continue

        if not login_field:
            logger.error("SSO username field not found on %s", current)
            return False

        login_field.clear()
        login_field.send_keys(config.LOGIN)
        logger.debug("SSO: username entered")

        # Find password field
        try:
            password_field = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='password']"
            )
            password_field.clear()
            password_field.send_keys(config.PASSWORD)
            logger.debug("SSO: password entered")
        except NoSuchElementException:
            # Some SSO providers have a two-step flow: username first, then password
            logger.info("No password field yet — submitting username first")
            try:
                submit = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "button[type='submit'], input[type='submit']",
                )
                submit.click()
                logger.debug("SSO: username submitted, waiting for password field")
                sso_wait.until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR, "input[type='password']",
                    ))
                )
                password_field = self.driver.find_element(
                    By.CSS_SELECTOR, "input[type='password']"
                )
                password_field.clear()
                password_field.send_keys(config.PASSWORD)
                logger.debug("SSO: password entered (step 2)")
            except (NoSuchElementException, TimeoutException):
                logger.error(
                    "SSO: could not complete two-step login on %s",
                    self.driver.current_url,
                )
                return False

        # Submit the SSO form
        try:
            submit = self.driver.find_element(
                By.CSS_SELECTOR,
                "button[type='submit'], input[type='submit']",
            )
            url_before = self.driver.current_url
            submit.click()
            logger.info("SSO: submit clicked | was at: %s", url_before)
        except NoSuchElementException:
            # Try pressing Enter on the password field
            from selenium.webdriver.common.keys import Keys
            password_field.send_keys(Keys.RETURN)
            logger.info("SSO: submitted via Enter key")

        # Wait for redirect back to Moodle (up to 30 s)
        redirect_wait = WebDriverWait(self.driver, 30)
        try:
            redirect_wait.until(
                lambda d: self._is_logged_in()
            )
            logger.info(
                "SSO provider login: SUCCESS | final url: %s",
                self.driver.current_url,
            )

            if return_url:
                self._navigate_safe(return_url)
                logger.info(
                    "Navigated to target after SSO provider login | url: %s",
                    self.driver.current_url,
                )

            self._save_cookies()
            return True

        except TimeoutException:
            logger.error(
                "SSO provider login: FAILED — not redirected back to Moodle "
                "within 30 s.\n"
                "  → final url: %s\n"
                "  → title: %s\n"
                "  → Проверьте LOGIN и PASSWORD в config, или запустите "
                "save_cookies.py для ручного входа.",
                self.driver.current_url,
                self.driver.title,
            )
            return False

    def _perform_sso_login(self, return_url: str | None = None) -> bool:
        """Click the SSO button and wait for authentication via external IdP.

        lms.mospolytech.ru uses an external SSO provider (Keycloak / SAML2).
        The Moodle login page shows only an SSO button — no username/password
        fields.  This method clicks that button, then waits up to 120 seconds
        for the browser to land on an authenticated Moodle page.

        If no SSO button is found, or authentication does not succeed within
        the timeout, the user is instructed to run save_cookies.py to
        manually refresh their session cookies.

        Args:
            return_url: URL to navigate to after a successful login.

        Returns:
            True if SSO login succeeded.
        """
        sso_selectors = [
            # Moodle auth_saml2 / Keycloak typical button labels
            "//a[contains(@href, 'saml2') or contains(@href, 'sso') "
            "or contains(@href, 'oauth2') or contains(@href, 'oidc')]",
            "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),'войти через')]",
            "//a[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),'войти через')]",
            "//button[contains(@class,'btn-secondary') or contains(@class,'sso')]",
            "//a[contains(@class,'btn-secondary') or contains(@class,'sso')]",
        ]

        sso_btn = None
        for xpath in sso_selectors:
            try:
                sso_btn = self.driver.find_element(By.XPATH, xpath)
                logger.info("SSO button found: %s", sso_btn.text or sso_btn.get_attribute("href"))
                break
            except NoSuchElementException:
                continue

        if sso_btn is None:
            logger.error(
                "SSO button not found and no username/password form present.\n"
                "  → Сохранённые cookies устарели или файл cookies не существует.\n"
                "  → Запустите save_cookies.py, войдите вручную и повторите запуск бота."
            )
            return False

        try:
            sso_btn.click()
            logger.info("SSO button clicked — waiting for authentication (up to 120 s)…")

            # Wait until we land on an authenticated Moodle page
            sso_wait = WebDriverWait(self.driver, 120)
            sso_wait.until(lambda d: self._is_logged_in())

            logger.info(
                "SSO login: SUCCESS | final url: %s", self.driver.current_url
            )

            if return_url:
                self._navigate_safe(return_url)
                logger.info(
                    "Navigated to target after SSO | url: %s",
                    self.driver.current_url,
                )

            self._save_cookies()
            return True

        except TimeoutException:
            logger.error(
                "SSO login timed out (120 s) — not authenticated.\n"
                "  → Запустите save_cookies.py, войдите вручную и повторите запуск бота.\n"
                "  → final url: %s",
                self.driver.current_url,
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected SSO login error | url: %s", self.driver.current_url
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