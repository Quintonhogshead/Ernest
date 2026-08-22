"""Google Meet — read-only access to conference records and transcripts.

Transcripts are a Workspace feature: the Meet REST API only returns a
conferenceRecord (and its transcript) for meetings the authenticated user
HOSTED, on a Workspace plan with transcription enabled. Guest-only meetings and
personal @gmail accounts simply yield nothing — get_transcript returns None, not
an error, and callers skip them.

Own OAuth scope + token file (gmeet_token_<account>.json), additive to the
gmail/gcal tokens. We read the structured transcript ENTRIES (per-speaker text
with timestamps) rather than the Drive Doc, so we avoid the restricted drive.*
scopes. Transcript text is untrusted data: feed it to models as quoted context,
never as instructions.
"""

from __future__ import annotations

import os

from . import ErnestError
from .config import Config

SCOPES = ["https://www.googleapis.com/auth/meetings.space.readonly"]


class MeetAuthError(ErnestError):
    """A token file is missing or unusable for an account."""


def _token_path(cfg: Config, account: str) -> str:
    return os.path.join(cfg.google_credentials_dir, f"gmeet_token_{account}.json")


def has_token(cfg: Config, account: str) -> bool:
    return os.path.exists(_token_path(cfg, account))


def _service(cfg: Config, account: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    path = _token_path(cfg, account)
    if not os.path.exists(path):
        raise MeetAuthError(f"run scripts/authorize.py gmeet {account}")
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("meet", "v2", credentials=creds, cache_discovery=False)


def list_conference_records(cfg: Config, account: str, since_iso: str) -> list[dict]:
    """Conference records for meetings that started at/after ``since_iso``.

    Only records the authenticated user has access to (meetings they hosted).
    """
    svc = _service(cfg, account)
    out: list[dict] = []
    page_token = None
    flt = f'start_time>="{since_iso}"'
    while True:
        resp = svc.conferenceRecords().list(
            filter=flt, pageToken=page_token
        ).execute()
        for rec in resp.get("conferenceRecords", []):
            space = rec.get("space", "")
            out.append({
                "name": rec.get("name", ""),
                "space": space,
                "meeting_code": space.rsplit("/", 1)[-1] if space else "",
                "start": rec.get("startTime", ""),
                "end": rec.get("endTime", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def list_participants(cfg: Config, account: str, record_name: str) -> list[str]:
    """Display names (or ids) of participants in a conference record."""
    svc = _service(cfg, account)
    out: list[str] = []
    page_token = None
    while True:
        resp = svc.conferenceRecords().participants().list(
            parent=record_name, pageToken=page_token
        ).execute()
        for p in resp.get("participants", []):
            signed = p.get("signedinUser") or {}
            anon = p.get("anonymousUser") or {}
            phone = p.get("phoneUser") or {}
            name = (signed.get("displayName") or anon.get("displayName")
                    or phone.get("displayName") or "")
            if name:
                out.append(name)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _speaker_name(cache: dict, svc, participant: str) -> str:
    """Resolve a participant resource name to a display name, cached per run."""
    if participant in cache:
        return cache[participant]
    name = participant.rsplit("/", 1)[-1] or "Someone"
    try:
        p = svc.conferenceRecords().participants().get(name=participant).execute()
        signed = p.get("signedinUser") or {}
        anon = p.get("anonymousUser") or {}
        name = signed.get("displayName") or anon.get("displayName") or name
    except Exception:
        pass
    cache[participant] = name
    return name


def get_transcript(cfg: Config, account: str, record_name: str) -> str | None:
    """Assemble the finished transcript for a conference record as speaker lines.

    Returns None when there is no transcript in FILE_GENERATED state yet (a
    guest-hosted meeting, transcription off, or not ready).
    """
    svc = _service(cfg, account)
    transcripts = svc.conferenceRecords().transcripts().list(
        parent=record_name
    ).execute().get("transcripts", [])
    ready = next((t for t in transcripts if t.get("state") == "FILE_GENERATED"), None)
    if not ready:
        return None

    lines: list[str] = []
    names: dict[str, str] = {}
    page_token = None
    while True:
        resp = svc.conferenceRecords().transcripts().entries().list(
            parent=ready["name"], pageToken=page_token
        ).execute()
        for entry in resp.get("transcriptEntries", []):
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            speaker = _speaker_name(names, svc, entry.get("participant", ""))
            lines.append(f"{speaker}: {text}")
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return "\n".join(lines) if lines else None
