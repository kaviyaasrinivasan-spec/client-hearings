"""
One-time WhatsApp Web login.

    python login_whatsapp.py                 # log in with a code (default)
    python login_whatsapp.py --headless      # same, with no browser window (server)
    python login_whatsapp.py --number 98xxxxxxxx   # a different sending number
    python login_whatsapp.py --qr            # scan a QR code instead

With the code: the script prints an 8-character code such as ABCD-EFGH. On
the sending phone open WhatsApp > Settings > Linked devices > Link a device >
"Link with phone number instead", and type the code.

The session is saved in the whatsapp_session folder and reused by
send_reminders.py, so this only needs doing again if WhatsApp logs it out.
"""
import argparse
import sys
import time

import config
from send_reminders import normalise_phone
from whatsapp import WHATSAPP_URL, WhatsApp, WhatsAppError

LOGIN_WAIT_SECONDS = 180


def wait_for_login(wa: WhatsApp, watch_code: bool) -> bool:
    """Wait for the phone to confirm; reprint the code if WhatsApp renews it."""
    shown = None
    deadline = time.time() + LOGIN_WAIT_SECONDS
    while time.time() < deadline:
        if wa.is_logged_in():
            # Give WhatsApp a moment to write the session to disk.
            print("Logged in. Saving the session...")
            time.sleep(10)
            print("Done. The session is saved.")
            return True
        if watch_code:
            code = wa.read_link_code()
            if code and code != shown:
                if shown:
                    print(f"WhatsApp renewed the code. New code:  {code}")
                shown = code
        time.sleep(2)
    return False


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # show progress live, even when piped
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--number", default=config.SENDER_NUMBER,
                        help=f"sending WhatsApp number (default {config.SENDER_NUMBER})")
    parser.add_argument("--qr", action="store_true", help="scan a QR code instead of entering a code")
    parser.add_argument("--headless", action="store_true", help="run Chrome with no window")
    args = parser.parse_args()

    if args.qr and args.headless:
        print("ERROR: a QR code needs a visible window; use the code login with --headless.")
        return 1

    phone = normalise_phone(args.number)
    if not phone:
        print(f"ERROR: {args.number!r} is not a usable mobile number.")
        return 1

    print(f"Opening WhatsApp Web (session folder: {config.SESSION_DIR})")
    try:
        wa = WhatsApp(headless=args.headless)
    except WhatsAppError as e:
        print(f"ERROR: {e}")
        return 1

    with wa:
        wa.driver.get(WHATSAPP_URL)
        try:
            screen = wa.wait_for_screen()
        except WhatsAppError as e:
            print(f"ERROR: {e}")
            return 1
        if screen == "chats":
            print("Already logged in. To switch numbers, delete the whatsapp_session "
                  "folder first, then run this again.")
            return 0

        if args.qr:
            print(f"Scan the QR code with the WhatsApp account {args.number}.")
        else:
            try:
                code = wa.link_with_phone_number(phone)
            except WhatsAppError as e:
                print(f"ERROR: {e}")
                config.LOG_DIR.mkdir(parents=True, exist_ok=True)
                wa.driver.save_screenshot(str(config.LOG_DIR / "login_error.png"))
                print(f"A screenshot of the page is in {config.LOG_DIR / 'login_error.png'}")
                return 1
            print()
            print(f"    Login code:  {code}")
            print()
            print(f"On the phone with +{phone}:")
            print("  WhatsApp > Settings > Linked devices > Link a device >")
            print('  "Link with phone number instead", then type the code.')

        print(f"Waiting up to {LOGIN_WAIT_SECONDS} seconds...")
        if wait_for_login(wa, watch_code=not args.qr):
            return 0

        print("Timed out waiting for the phone. Run this again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
