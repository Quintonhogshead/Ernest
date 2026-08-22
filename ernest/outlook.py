"""Outlook / Microsoft 365 mail — read-only via Microsoft Graph.

Uses MSAL (device-code flow) for auth with the delegated ``Mail.Read`` scope —
read-only by construction; this module cannot send or modify mail. One token
cache per account (``ms_token_<name>.json`` in the credentials dir), refreshed
silently. Run ``scripts/authorize.py outlook <account>`` once per account.
"""

from __future__ import annotations

import os

import requests

from . import ConfigError, ErnestError
from .config import Config
from .news import _strip_html  # reuse the HTML-to-text stripper

SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"
_BODY_LIMIT = 1500


class OutlookAuthError(ErnestError):
    """A token cache is missing or unusable for an account."""


def _authority(cfg: Config) -> str:
    return f"https://login.microsoftonline.com/{cfg.ms_tenant or 'common'}"


def cache_path(cfg: Config, account: str) -> str:
    return os.path.join(cfg.google_credentials_dir, f"ms_token_{account}.json")


def _load_cache(path: str):
    import msal

    cache = msal.SerializableTokenCache()
    if os.path.exists(path):
        cache.deserialize(open(path, encoding="utf-8").read())
    return cache


def _save_cache(path: str, cache) -> None:
    if cache.has_state_changed:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(cache.serialize())


def _access_token(cfg: Config, account: str) -> str:
    if not cfg.ms_client_id:
        raise ConfigError("MS_CLIENT_ID is required for Outlook accounts")
    import msal

    path = cache_path(cfg, account)
    if not os.path.exists(path):
        raise OutlookAuthError(f"run scripts/authorize.py outlook {account}")
    cache = _load_cache(path)
    app = msal.PublicClientApplication(
        cfg.ms_client_id, authority=_authority(cfg), token_cache=cache
    )
    accounts = app.get_accounts()
    if not accounts:
        raise OutlookAuthError(f"no cached account for {account}; re-authorize")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _save_cache(path, cache)
    if not result or "access_token" not in result:
        raise OutlookAuthError(f"token refresh failed for {account}; re-authorize")
    return result["access_token"]


def _body_text(message: dict) -> str:
    body = message.get("body", {}) or {}
    content = body.get("content", "") or ""
    if body.get("contentType", "").lower() == "html":
        content = _strip_html(content)
    return content[:_BODY_LIMIT] or message.get("bodyPreview", "")


def unread(cfg: Config, account: str, max_results: int = 25) -> list[dict]:
    token = _access_token(cfg, account)
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "$filter": "isRead eq false",
        "$top": str(max_results),
        "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body",
        "$orderby": "receivedDateTime desc",
    }
    resp = requests.get(
        f"{GRAPH}/me/mailFolders/inbox/messages",
        headers=headers, params=params, timeout=20,
    )
    if resp.status_code == 401:
        raise OutlookAuthError(f"Graph rejected the token for {account}; re-authorize")
    resp.raise_for_status()
    out: list[dict] = []
    for m in resp.json().get("value", []):
        sender = (m.get("from", {}) or {}).get("emailAddress", {}) or {}
        out.append(
            {
                "id": m["id"],
                "thread_id": m.get("conversationId", ""),
                "account": account,
                "sender": sender.get("address", "") or sender.get("name", ""),
                "subject": m.get("subject", ""),
                "date": m.get("receivedDateTime", ""),
                "snippet": m.get("bodyPreview", ""),
                "body_text": _body_text(m),
            }
        )
    return out
