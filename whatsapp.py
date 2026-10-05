"""
WhatsApp Web driven by Selenium, with the login kept in a Chrome profile.

Log in once with login_whatsapp.py (phone-number code or QR); after that
every run reuses the saved profile in SESSION_DIR and is already logged in.
"""
import re
import sys
import time
import urllib.parse

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException, TimeoutException, WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

import config

WHATSAPP_URL = "https://web.whatsapp.com"

# WhatsApp changes its markup often; each of these has fallbacks.
CHAT_LIST = (By.CSS_SELECTOR, "#pane-side, div[aria-label='Chat list']")
QR_CODE = (By.CSS_SELECTOR, "canvas[aria-label*='Scan'], div[data-ref] canvas")
COMPOSE_BOX = (By.CSS_SELECTOR, "footer div[contenteditable='true']")
POPUP = (By.CSS_SELECTOR, "div[role='dialog']")
DISMISS_LABELS = ("continue", "ok", "close", "got it", "not now", "dismiss")

# WhatsApp redraws the page constantly, so an element found a moment ago can
# vanish before it is read. Waits just look again when that happens.
REDRAWN = (StaleElementReferenceException,)

# Our own messages carry a "You:" label plus a status label (Sent/Delivered/Read).
LAST_OUTGOING_JS = """
const rows = [...document.querySelectorAll('#main [role=row]')];
for (let i = rows.length - 1; i >= 0; i--) {
  const r = rows[i];
  const labels = [...r.querySelectorAll('[aria-label]')]
    .map(e => (e.getAttribute('aria-label') || '').trim().toLowerCase());
  if (labels.includes('you:') || r.querySelector('.message-out')) {
    const idEl = r.querySelector('[data-id]');
    return {id: idEl ? idEl.getAttribute('data-id') : '', text: r.innerText, labels: labels};
  }
}
return null;
"""

# "Log in with phone number" screens.
PHONE_LOGIN_LINK = (By.XPATH, "//*[@data-testid='link_device_qr_phone_number_link']"
                              " | //div[@role='button'][contains(., 'phone number')]")
PHONE_INPUT = (By.CSS_SELECTOR, "input[data-testid='phone-number-input'], "
                                "input[aria-label*='phone number']")
NEXT_BUTTON = (By.XPATH, "//button[normalize-space(.)='Next']")
LINK_CODE = (By.CSS_SELECTOR, "[data-link-code]")


class WhatsAppError(RuntimeError):
    pass


class InvalidNumber(WhatsAppError):
    pass


class WhatsApp:
    def __init__(self, headless: bool = config.HEADLESS):
        config.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        opts = webdriver.ChromeOptions()
        opts.add_argument(f"--user-data-dir={config.SESSION_DIR}")
        opts.add_argument("--profile-directory=Default")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--window-size=1200,900")
        if sys.platform.startswith("linux"):
            # Chrome will not start as root without --no-sandbox, and Docker/VPS
            # machines often have a tiny /dev/shm that crashes it mid-run.
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
        if headless:
            opts.add_argument("--headless=new")
        try:
            # Selenium Manager downloads the matching chromedriver itself.
            self.driver = webdriver.Chrome(options=opts)
        except WebDriverException as e:
            if "user data directory is already in use" in str(e).lower():
                raise WhatsAppError(
                    "The WhatsApp session is open in another Chrome window. "
                    "Close it and run again."
                ) from e
            raise

        if headless:
            # WhatsApp refuses the "HeadlessChrome" user agent; present the
            # installed Chrome's own one instead, so the version always matches.
            ua = self.driver.execute_script("return navigator.userAgent")
            self.driver.execute_cdp_cmd("Network.setUserAgentOverride",
                                        {"userAgent": ua.replace("HeadlessChrome", "Chrome")})

    # ---- session -----------------------------------------------------------
    def open(self, wait_for_login: int = 60) -> None:
        """Open WhatsApp Web and wait until the chat list shows (logged in)."""
        self.driver.get(WHATSAPP_URL)
        try:
            WebDriverWait(self.driver, wait_for_login).until(
                lambda d: d.find_elements(*CHAT_LIST)
            )
        except TimeoutException:
            if self.driver.find_elements(*QR_CODE):
                raise WhatsAppError(
                    "WhatsApp Web is logged out: the saved session has expired. "
                    "Run login_whatsapp.py to log in again."
                )
            raise WhatsAppError("WhatsApp Web did not finish loading.")
        time.sleep(2)
        self.dismiss_popups()

    def wait_for_screen(self, timeout: int = 90) -> str:
        """After loading WhatsApp Web: 'chats' if logged in, 'login' if not."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                lambda d: "chats" if d.find_elements(*CHAT_LIST)
                else "login" if d.find_elements(*QR_CODE) else False
            )
        except TimeoutException:
            raise WhatsAppError("WhatsApp Web did not finish loading.")

    def is_logged_in(self) -> bool:
        return bool(self.driver.find_elements(*CHAT_LIST))

    def qr_visible(self) -> bool:
        return bool(self.driver.find_elements(*QR_CODE))

    def link_with_phone_number(self, phone: str, timeout: int = 60) -> str:
        """
        From the login screen, choose "Log in with phone number", enter
        `phone` (digits with country code) and return the 8-character code
        WhatsApp shows, e.g. "ABCD-EFGH".
        """
        wait = WebDriverWait(self.driver, timeout)
        try:
            # The QR panel must finish loading before the link responds.
            wait.until(lambda d: d.find_elements(*QR_CODE))
            link = wait.until(lambda d: d.find_elements(*PHONE_LOGIN_LINK))
            self.driver.execute_script("arguments[0].click()", link[-1])

            box = wait.until(lambda d: d.find_elements(*PHONE_INPUT))[0]
            box.click()
            box.send_keys(Keys.CONTROL, "a")
            box.send_keys(Keys.BACKSPACE)
            box.send_keys("+" + phone)
            time.sleep(1)

            wait.until(lambda d: d.find_elements(*NEXT_BUTTON))[0].click()
            return wait.until(lambda d: self.read_link_code())
        except TimeoutException:
            raise WhatsAppError("WhatsApp Web did not show a login code. "
                                "Check the number and try again.")

    def read_link_code(self) -> str | None:
        """The code on the "Enter code on phone" screen, or None if not shown."""
        found = self.driver.find_elements(*LINK_CODE)
        raw = found[0].get_attribute("data-link-code") if found else ""
        if not raw:
            # Fallback if the attribute is renamed: the code as page text.
            text = self.driver.find_element(By.TAG_NAME, "body").text
            match = re.search(r"\b([A-Z0-9]{4})[\s-]*([A-Z0-9]{4})\b", text)
            raw = "".join(match.groups()) if match else ""
        code = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        return f"{code[:4]}-{code[4:]}" if len(code) == 8 else None

    # ---- popups ------------------------------------------------------------
    def dismiss_popups(self) -> None:
        """
        Close WhatsApp's own dialogs ("What's new on WhatsApp Web" and the
        like). They sit over the chat and swallow the Enter key.
        """
        for popup in self.driver.find_elements(*POPUP):
            try:
                if "invalid" in popup.text.lower():
                    continue  # the "not on WhatsApp" notice; send() reports it
                for button in popup.find_elements(By.XPATH, ".//button"):
                    label = (button.text or button.get_attribute("aria-label") or "").strip().lower()
                    if label in DISMISS_LABELS:
                        button.click()
                        time.sleep(1)
                        break
            except WebDriverException:
                # Closed or redrawn while we looked at it; nothing to do.
                continue

    # ---- sending -----------------------------------------------------------
    def _last_outgoing(self) -> dict | None:
        """The newest message we sent in the open chat: its id, text and labels."""
        return self.driver.execute_script(LAST_OUTGOING_JS)

    def send(self, phone: str, message: str, timeout: int = 60) -> None:
        """
        Send `message` to `phone` (digits with country code, e.g. 919876543210).
        Returns only once the message shows in the chat as Sent, Delivered or
        Read; raises WhatsAppError otherwise.
        """
        url = f"{WHATSAPP_URL}/send?phone={phone}&text={urllib.parse.quote(message)}"
        self.driver.get(url)

        # Either the chat opens with the text pre-filled, or a popup says the
        # number is not on WhatsApp. Anything else in the way gets closed.
        def ready(d):
            for popup in d.find_elements(*POPUP):
                if "invalid" in popup.text.lower():
                    return "invalid"
            self.dismiss_popups()
            box = d.find_elements(*COMPOSE_BOX)
            if box and box[0].text.strip() and not d.find_elements(*POPUP):
                return box[0]
            return False

        try:
            box = WebDriverWait(self.driver, timeout, ignored_exceptions=REDRAWN).until(ready)
        except TimeoutException:
            raise WhatsAppError(f"The chat for {phone} did not open in {timeout}s.")

        if box == "invalid":
            raise InvalidNumber(f"{phone} is not on WhatsApp.")

        time.sleep(2)  # let the chat history and pre-filled text settle
        before = self._last_outgoing()
        before_id = before["id"] if before else None
        # A line of the message to recognise it by, without WhatsApp's *bold* marks.
        marker = next(l for l in message.replace("*", "").splitlines() if l.strip()).strip()

        # Find the box afresh: WhatsApp may have redrawn it during the pause.
        box = self.driver.find_elements(*COMPOSE_BOX)[0]
        box.send_keys(Keys.ENTER)

        def delivered(d):
            last = self._last_outgoing()
            if not last or last["id"] == before_id or marker not in last["text"]:
                return False
            return any(s in last["labels"] for s in ("sent", "delivered", "read"))

        try:
            WebDriverWait(self.driver, 90, ignored_exceptions=REDRAWN).until(delivered)
        except TimeoutException:
            last = self._last_outgoing()
            if last and last["id"] != before_id and marker in last["text"]:
                raise WhatsAppError(f"The message to {phone} is stuck as pending: "
                                    "check the sending phone has internet.")
            raise WhatsAppError(f"The message to {phone} did not appear in the chat.")

        time.sleep(2)  # let WhatsApp finish syncing before the browser closes

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
