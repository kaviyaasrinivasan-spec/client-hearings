"""
Send WhatsApp hearing reminders to clients, DAYS_BEFORE (2) days ahead.

Run daily at 11:00 AM by the scheduled task (schedule_task.ps1):

    python send_reminders.py              # send for hearings 2 days from today
    python send_reminders.py --dry-run    # show what would be sent, send nothing
    python send_reminders.py --date 2026-09-26   # hearings on a specific date
    python send_reminders.py --test-to 9876543210  # send one sample message

Each hearing is reminded once: successful sends are recorded in
data/sent_log.json, so a re-run the same day only retries the failures.
"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta

import config
from cases_api import CasesApiError, cases_with_hearing_on, hearing_date
from whatsapp import InvalidNumber, WhatsApp, WhatsAppError

log = logging.getLogger("reminders")


# ---- message ---------------------------------------------------------------
def build_message(case: dict) -> str:
    nh = case.get("next_hearing") or {}
    when = datetime.strptime(hearing_date(case), "%Y-%m-%d")
    client = (case.get("client") or {}).get("name") or "Client"

    return (
        f"*Hearing Reminder*\n\n"
        f"Dear {client},\n"
        f"This is a reminder of your upcoming court hearing.\n\n"
        f"*Hearing Date:* {when.strftime('%d %B %Y (%A)')}\n"
        f"*Hearing Time:* {nh.get('time_label') or 'To be confirmed'}\n\n"
        f"- {config.FIRM_NAME}"
    )


# ---- phone numbers ---------------------------------------------------------
def normalise_phone(raw: str | None) -> str | None:
    """
    Turn a stored number into WhatsApp's digits-with-country-code form.
    '9789939792' / '09789939792' / '+91 97899 39792' -> '919789939792'.
    Returns None when the number cannot be a mobile.
    """
    if not raw:
        return None
    has_plus = raw.strip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    cc = config.DEFAULT_COUNTRY_CODE

    if has_plus:
        # Explicit international number; trust it if it is a sensible length.
        return digits if 10 <= len(digits) <= 15 else None
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith(cc):
        digits = digits[len(cc):]
    if len(digits) == 10:
        # Indian mobiles start 6-9; anything else is a landline or placeholder.
        if cc == "91" and digits[0] not in "6789":
            return None
        return cc + digits
    return None


# ---- sent log --------------------------------------------------------------
def load_sent() -> dict:
    try:
        return json.loads(config.SENT_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_sent(sent: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.SENT_LOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(sent, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.SENT_LOG)


def sent_key(case: dict) -> str:
    nh = case.get("next_hearing") or {}
    # Hearing id + date: a rescheduled hearing gets a fresh reminder.
    return f"case{case['id']}-hearing{nh.get('id', 'x')}-{hearing_date(case)}"


# ---- main ------------------------------------------------------------------
def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (
        logging.FileHandler(config.LOG_DIR / "reminders.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def run(target: date, dry_run: bool) -> int:
    log.info("=== Reminders for hearings on %s (sender %s)%s ===",
             target.isoformat(), config.SENDER_NUMBER, " [DRY RUN]" if dry_run else "")

    try:
        cases = cases_with_hearing_on(target)
    except CasesApiError as e:
        log.error("%s", e)
        return 1
    log.info("%d case(s) have a hearing on %s", len(cases), target.isoformat())

    sent = load_sent()
    todo = []
    for case in cases:
        label = f"{case.get('case_no') or case.get('uid')} ({case.get('case_name')})"
        if sent_key(case) in sent:
            log.info("SKIP   %s - already reminded", label)
            continue
        raw = (case.get("client") or {}).get("phone")
        phone = normalise_phone(raw)
        if not phone:
            log.warning("SKIP   %s - no usable client mobile number (%r)", label, raw)
            continue
        todo.append((case, phone, label))

    if not todo:
        log.info("Nothing to send.")
        return 0

    if dry_run:
        for case, phone, label in todo:
            log.info("WOULD SEND to +%s  %s\n%s\n", phone, label, build_message(case))
        return 0

    failures = 0
    try:
        with WhatsApp() as wa:
            wa.open()
            for i, (case, phone, label) in enumerate(todo):
                if i:
                    time.sleep(config.DELAY_BETWEEN_MESSAGES)
                try:
                    wa.send(phone, build_message(case))
                except InvalidNumber as e:
                    failures += 1
                    log.warning("FAIL   %s - %s", label, e)
                    continue
                except WhatsAppError as e:
                    failures += 1
                    log.error("FAIL   %s - %s", label, e)
                    continue
                sent[sent_key(case)] = {
                    "case_no": case.get("case_no"),
                    "case_name": case.get("case_name"),
                    "phone": phone,
                    "hearing_date": hearing_date(case),
                    "sent_at": datetime.now().isoformat(timespec="seconds"),
                }
                save_sent(sent)
                log.info("SENT   %s -> +%s", label, phone)
    except WhatsAppError as e:
        log.error("%s", e)
        return 1

    log.info("Finished: %d sent, %d failed.", len(todo) - failures, failures)
    return 1 if failures else 0


def send_test(number: str) -> int:
    phone = normalise_phone(number)
    if not phone:
        log.error("%r is not a usable mobile number.", number)
        return 1
    sample = {
        "id": 0, "case_no": "WP 1234/2026", "case_name": "Sample vs Test",
        "court": {"name": "District Court"}, "client": {"name": "Test Client"},
        "next_hearing": {"date": (date.today() + timedelta(days=config.DAYS_BEFORE)).isoformat(),
                         "time_label": "10:30 AM"},
    }
    try:
        with WhatsApp() as wa:
            wa.open()
            wa.send(phone, build_message(sample))
    except WhatsAppError as e:
        log.error("%s", e)
        return 1
    log.info("Test message sent to +%s", phone)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", help="hearing date to remind for (YYYY-MM-DD); default today + DAYS_BEFORE")
    parser.add_argument("--dry-run", action="store_true", help="print messages without sending")
    parser.add_argument("--test-to", metavar="PHONE", help="send one sample message to this number")
    args = parser.parse_args()

    setup_logging()

    if args.test_to:
        return send_test(args.test_to)

    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target = date.today() + timedelta(days=config.DAYS_BEFORE)
    return run(target, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
