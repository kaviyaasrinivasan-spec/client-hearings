"""
Settings, read from the .env file next to this script (or the environment).

Nothing here needs editing in code — change .env instead.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    """Minimal .env reader: KEY=value lines, # comments, no dependencies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")

# ---- Cases API -------------------------------------------------------------
API_BASE = os.environ.get("CASES_API_BASE", "https://cases.abilawfirm.in/api/v1").rstrip("/")
APP_KEY = os.environ.get("CASES_APP_KEY", "")

# ---- Reminder rule ---------------------------------------------------------
# Send DAYS_BEFORE days ahead of the hearing. The 11:00 AM send time is set
# by the Windows scheduled task (see schedule_task.ps1).
DAYS_BEFORE = int(os.environ.get("DAYS_BEFORE", "2"))

# Numbers without a country code are treated as this country.
DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "91")

# The WhatsApp account that is logged in (by QR) and sends the messages.
SENDER_NUMBER = os.environ.get("SENDER_NUMBER", "8124035811")

FIRM_NAME = os.environ.get("FIRM_NAME", "ABI Law Firm")

# ---- WhatsApp Web / Selenium ----------------------------------------------
# Chrome profile that holds the logged-in WhatsApp Web session.
SESSION_DIR = Path(os.environ.get("SESSION_DIR", BASE_DIR / "whatsapp_session"))
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

# Seconds to wait between messages, to look less like a bot to WhatsApp.
DELAY_BETWEEN_MESSAGES = int(os.environ.get("DELAY_BETWEEN_MESSAGES", "8"))

# ---- Files -----------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
SENT_LOG = DATA_DIR / "sent_log.json"
