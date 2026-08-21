"""Canvas LMS — read-only.

Personal-access-token auth (Canvas → Account → Settings → New Access Token).
Read-only by design: Ernest never submits coursework, posts, or messages
instructors. Every list endpoint follows the ``Link: rel="next"`` header.
"""

from __future__ import annotations

import requests

from . import ConfigError, ErnestError
from .config import Config

_TIMEOUT = 20


class CanvasAuthError(ErnestError):
    """Canvas rejected the token (401)."""


def _get(cfg: Config, path: str, params: dict | None = None) -> list | dict:
    if not cfg.canvas_base_url or not cfg.canvas_token:
        raise ConfigError("CANVAS_BASE_URL and CANVAS_TOKEN are required")
    url = f"{cfg.canvas_base_url}/api/v1{path}"
    headers = {"Authorization": f"Bearer {cfg.canvas_token}"}
    merged: list = []
    first: dict | None = None
    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=_TIMEOUT)
        params = None  # only on the first request
        if resp.status_code == 401:
            raise CanvasAuthError("Canvas token invalid or expired")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            merged.extend(data)
        else:
            first = data
            break
        url = _next_link(resp.headers.get("Link", ""))
    return first if first is not None else merged


def _next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        url = section[0].strip().lstrip("<").rstrip(">")
        if any('rel="next"' in s for s in section[1:]):
            return url
    return None


def upcoming_events(cfg: Config) -> list:
    return _get(cfg, "/users/self/upcoming_events")  # type: ignore[return-value]


def todo(cfg: Config) -> list:
    return _get(cfg, "/users/self/todo")  # type: ignore[return-value]


def courses(cfg: Config) -> list:
    return _get(cfg, "/courses", {"enrollment_state": "active", "per_page": 50})  # type: ignore[return-value]


def announcements(cfg: Config, course_ids: list[str], days_back: int = 7) -> list:
    if not course_ids:
        return []
    params = [("context_codes[]", f"course_{cid}") for cid in course_ids]
    # requests encodes a list of tuples as repeated params; add the window
    import datetime as _dt

    start = (_dt.datetime.utcnow() - _dt.timedelta(days=days_back)).date().isoformat()
    url = f"{cfg.canvas_base_url}/api/v1/announcements"
    headers = {"Authorization": f"Bearer {cfg.canvas_token}"}
    resp = requests.get(
        url, headers=headers, params=params + [("start_date", start)], timeout=_TIMEOUT
    )
    if resp.status_code == 401:
        raise CanvasAuthError("Canvas token invalid or expired")
    resp.raise_for_status()
    return resp.json()
