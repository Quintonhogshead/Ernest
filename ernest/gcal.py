"""Google Calendar — one OAuth token per account, read AND write.

Unlike gmail.py (gmail.readonly only), this module can create, update, and
delete events — but ONLY ever on the one calendar Ernest itself owns (see
get_or_create_calendar). Your real work/personal calendars are read sources
here, never write targets. Calendar scope lives in its own token file
(gcal_token_<account>.json) so adding it never touches existing Gmail auth.

Run ``scripts/authorize.py gcal <account>`` once per account to mint a token;
this module never starts an interactive flow.
"""

from __future__ import annotations

import hashlib
import os

from . import ErnestError
from .config import Config

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_CALENDAR_NAME = "Ernest"


class GcalAuthError(ErnestError):
    """A token file is missing or unusable for an account."""


def _token_path(cfg: Config, account: str) -> str:
    return os.path.join(cfg.google_credentials_dir, f"gcal_token_{account}.json")


def has_token(cfg: Config, account: str) -> bool:
    return os.path.exists(_token_path(cfg, account))


def _service(cfg: Config, account: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    path = _token_path(cfg, account)
    if not os.path.exists(path):
        raise GcalAuthError(f"run scripts/authorize.py gcal {account}")
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _normalize(raw: dict) -> dict:
    start = raw.get("start", {})
    end = raw.get("end", {})
    return {
        "id": raw.get("id", ""),
        "title": raw.get("summary", "") or "(untitled)",
        "start": start.get("dateTime") or start.get("date") or "",
        "end": end.get("dateTime") or end.get("date") or "",
        "location": raw.get("location", "") or "",
        "updated": raw.get("updated", ""),
    }


def fingerprint(title: str, start: str, end: str, location: str) -> str:
    return hashlib.sha256(f"{title}|{start}|{end}|{location}".encode("utf-8")).hexdigest()


def get_or_create_calendar(cfg: Config, account: str, name: str = _CALENDAR_NAME) -> str:
    """Idempotent: return the existing "Ernest" calendar's id, creating it if absent."""
    svc = _service(cfg, account)
    page_token = None
    while True:
        resp = svc.calendarList().list(pageToken=page_token).execute()
        for cal in resp.get("items", []):
            if cal.get("summary") == name:
                return cal["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    created = svc.calendars().insert(body={"summary": name}).execute()
    return created["id"]


def list_events(cfg: Config, account: str, calendar_id: str,
                 time_min: str, time_max: str) -> list[dict]:
    """Events on ``calendar_id`` in [time_min, time_max] (RFC3339), normalized."""
    svc = _service(cfg, account)
    out: list[dict] = []
    page_token = None
    while True:
        resp = svc.events().list(
            calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy="startTime", pageToken=page_token,
        ).execute()
        out.extend(_normalize(e) for e in resp.get("items", []) if e.get("status") != "cancelled")
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _event_body(event: dict) -> dict:
    def _when(value: str) -> dict:
        return {"date": value} if len(value) == 10 else {"dateTime": value}

    body = {
        "summary": event.get("title", ""),
        "start": _when(event["start"]),
        "end": _when(event["end"]),
    }
    if event.get("location"):
        body["location"] = event["location"]
    if event.get("notes"):
        body["description"] = event["notes"]
    return body


def create_event(cfg: Config, account: str, calendar_id: str, event: dict) -> dict:
    svc = _service(cfg, account)
    created = svc.events().insert(calendarId=calendar_id, body=_event_body(event)).execute()
    return _normalize(created)


def update_event(cfg: Config, account: str, calendar_id: str, event_id: str,
                  event: dict) -> dict:
    svc = _service(cfg, account)
    updated = svc.events().update(
        calendarId=calendar_id, eventId=event_id, body=_event_body(event)
    ).execute()
    return _normalize(updated)


def delete_event(cfg: Config, account: str, calendar_id: str, event_id: str) -> None:
    svc = _service(cfg, account)
    try:
        svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as exc:  # already gone — treat as success
        if "404" not in str(exc) and "410" not in str(exc):
            raise
