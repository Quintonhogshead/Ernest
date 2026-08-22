"""Gmail — read-only, one OAuth token per account.

Scope is ``gmail.readonly`` only; this module cannot send, draft, or modify
labels — the trust ladder is enforced in the credential, not just the prompt.
Run ``scripts/authorize.py <account>`` once per account to mint a token; this
module never starts an interactive flow.
"""

from __future__ import annotations

import base64
import os

from . import ErnestError
from .config import Config

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_BODY_LIMIT = 1500


class GmailAuthError(ErnestError):
    """A token file is missing or unusable for an account."""


def _token_path(cfg: Config, account: str) -> str:
    return os.path.join(cfg.google_credentials_dir, f"token_{account}.json")


def _service(cfg: Config, account: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    path = _token_path(cfg, account)
    if not os.path.exists(path):
        raise GmailAuthError(f"run scripts/authorize.py {account}")
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(payload: dict) -> str:
    """Return the first text/plain part, base64url-decoded and truncated."""
    stack = [payload]
    while stack:
        part = stack.pop()
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                raw = base64.urlsafe_b64decode(data + "===").decode(
                    "utf-8", errors="replace"
                )
                return raw[:_BODY_LIMIT]
        stack.extend(part.get("parts", []) or [])
    return ""


def sent(cfg: Config, account: str, max_results: int = 12) -> list[dict]:
    """Recent messages you've sent — used to learn your writing voice."""
    svc = _service(cfg, account)
    listing = (
        svc.users().messages()
        .list(userId="me", q="in:sent", maxResults=max_results).execute()
    )
    out: list[dict] = []
    for ref in listing.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        payload = msg.get("payload", {})
        out.append({
            "subject": _header(payload.get("headers", []), "Subject"),
            "body_text": _decode_body(payload) or msg.get("snippet", ""),
        })
    return out


def unread(cfg: Config, account: str, max_results: int = 25) -> list[dict]:
    svc = _service(cfg, account)
    listing = (
        svc.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=max_results)
        .execute()
    )
    out: list[dict] = []
    for ref in listing.get("messages", []):
        msg = (
            svc.users()
            .messages()
            .get(userId="me", id=ref["id"], format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        body = _decode_body(payload)
        out.append(
            {
                "id": msg["id"],
                "thread_id": msg.get("threadId", ""),
                "account": account,
                "sender": _header(headers, "From"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
                "body_text": body or msg.get("snippet", ""),
            }
        )
    return out
