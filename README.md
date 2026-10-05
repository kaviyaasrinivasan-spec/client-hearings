# ABI Hearing WhatsApp Reminders

Sends each client a WhatsApp reminder **2 days before** their hearing, at **11:00 AM**,
from the WhatsApp account **7904815625**, using WhatsApp Web driven by Selenium.

Data comes from the CRM Cases API (`GET /api/v1/app/cases`, `X-App-Key` header):
Case No, Case Name, Court Name, Hearing Date, Hearing Time, and the client's mobile (`client.phone`).

## Setup (once)

```powershell
pip install -r requirements.txt
copy .env.example .env        # then fill in CASES_APP_KEY (already filled if .env exists)
python login_whatsapp.py      # prints a login code (see below)
powershell -ExecutionPolicy Bypass -File schedule_task.ps1   # daily 11:00 AM task
```

### Logging in to WhatsApp

`python login_whatsapp.py` prints an 8-character code such as `ABCD-EFGH`. On the sending phone:
**WhatsApp > Settings > Linked devices > Link a device > "Link with phone number instead"**, then type the code.
The script waits up to 3 minutes and reprints the code if WhatsApp renews it.

- `--headless` runs with no browser window (for a server or Remote Desktop-less machine).
- `--number 98xxxxxxxx` links a different number (defaults to `SENDER_NUMBER` in `.env`).
- `--qr` shows a QR code to scan instead (needs a visible window).

The login is saved in `whatsapp_session/` (a Chrome profile) and reused on every run.
Re-run `login_whatsapp.py` only if the log says the session expired.

**Changing the sending number:** log the old phone out of Linked devices, delete the
`whatsapp_session` folder, set `SENDER_NUMBER` in `.env`, then run `login_whatsapp.py` again.

**On a server:** don't copy `whatsapp_session` from another machine; log in on the server itself
with `python login_whatsapp.py --headless`.

## Daily run

At 11:00 AM the task runs `send_reminders.py`, which:

1. Gets every open case whose next hearing is today + 2 days (all pages).
2. Converts the client's phone to international format (`9789939792` becomes `919789939792`).
3. Opens the chat in WhatsApp Web and sends the message.
4. Records the send in `data/sent_log.json`, so no hearing is reminded twice.

Cases with no client number, or a number that can't be a mobile, are skipped with a warning.
Everything goes to `logs/reminders.log`.

## Manual commands

```powershell
python send_reminders.py --dry-run                  # preview today's reminders, send nothing
python send_reminders.py --date 2026-10-12 --dry-run
python send_reminders.py --test-to 9876543210       # send one sample message
python send_reminders.py                            # run now (safe to repeat; failures retry)
```

## Notes

- The PC must be on and logged in, and the sending phone must have internet. If the PC was off
  at 11:00, the task runs as soon as it's back.
- Close any Chrome window that is using `whatsapp_session` before the task runs.
- Settings (days before, country code, delay between messages, headless) are in `.env`.
