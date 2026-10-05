"""
Client for the CRM's Cases API (GET /api/v1/app/cases, X-App-Key auth).
"""
import json
import urllib.parse
import urllib.request
from datetime import date

import config


class CasesApiError(RuntimeError):
    pass


def _get(path: str, params: dict) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{config.API_BASE}{path}?{query}"
    req = urllib.request.Request(url, headers={
        "X-App-Key": config.APP_KEY,
        "Accept": "application/json",
        "User-Agent": "abi-hearing-reminders/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise CasesApiError(f"Cases API returned {e.code} for {path}: {body}") from e
    except urllib.error.URLError as e:
        raise CasesApiError(f"Could not reach the Cases API: {e.reason}") from e


def cases_with_hearing_on(day: date) -> list[dict]:
    """Every open case whose next hearing falls on `day`, across all pages."""
    if not config.APP_KEY:
        raise CasesApiError("CASES_APP_KEY is not set in .env")

    iso = day.isoformat()
    cases, page = [], 1
    while True:
        body = _get("/app/cases", {
            "hearing_from": iso,
            "hearing_to": iso,
            "per_page": 100,
            "page": page,
        })
        cases.extend(body.get("data", []))
        if page >= body.get("meta", {}).get("last_page", 1):
            break
        page += 1

    # The date filter runs on the case's cached next-hearing date; confirm it
    # against the hearing record itself so a stale cache never sends a reminder.
    return [c for c in cases if hearing_date(c) == iso]


def hearing_date(case: dict) -> str | None:
    nh = case.get("next_hearing") or {}
    return nh.get("date") or case.get("next_hearing_date")
