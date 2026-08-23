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


def _meeting_code(raw: dict) -> str:
    """The Meet meeting code from a calendar event's conferenceData, if any.

    Used to correlate a scheduled event with its Meet conferenceRecord (whose
    space carries the same code). Falls back to parsing the hangoutLink path.
    """
    conf = raw.get("conferenceData") or {}
    for ep in conf.get("entryPoints", []) or []:
        code = ep.get("meetingCode")
        if code:
            return code
    link = raw.get("hangoutLink", "") or ""
    return link.rstrip("/").rsplit("/", 1)[-1] if link else ""


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
        "meet_url": raw.get("hangoutLink", "") or "",
        "meeting_code": _meeting_code(raw),
        "attendees": [a.get("email", "") for a in raw.get("attendees", []) or []
                      if a.get("email")],
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


def list_calendars(cfg: Config, account: str) -> list[dict]:
    """Every calendar on the account: {id, summary, selected, primary}.

    ``selected`` mirrors the checkbox in the Google Calendar UI, so reading the
    selected ones shows the user exactly what they see — including secondary
    calendars like "Ernest" where Ernest books events, not just ``primary``.
    """
    svc = _service(cfg, account)
    out: list[dict] = []
    page_token = None
    while True:
        resp = svc.calendarList().list(pageToken=page_token).execute()
        for cal in resp.get("items", []):
            out.append({
                "id": cal["id"],
                "summary": cal.get("summary", "") or "",
                "selected": bool(cal.get("selected", False)),
                "primary": bool(cal.get("primary", False)),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


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
    tz = event.get("timezone")

    def _when(value: str) -> dict:
        if len(value) == 10:  # bare date → all-day
            return {"date": value}
        when = {"dateTime": value}
        # If the timestamp is naive (no offset/Z), tell Google which zone it's in
        # so it applies the correct DST rules — instead of us baking an offset the
        # model might get wrong across a daylight-saving boundary.
        clock = value[10:]
        if tz and "+" not in clock and "-" not in clock and not value.endswith("Z"):
            when["timeZone"] = tz
        return when

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
