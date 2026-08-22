"""Multi-account, multi-provider mail dispatch (read-only).

Each entry in ERNEST_ACCOUNTS is ``provider:name`` — e.g.
``gmail:work,gmail:personal,outlook:job,outlook:side``. A bare ``name`` (no
prefix) defaults to gmail, so older configs keep working. This module is the one
place that knows which provider a given account uses.
"""

from __future__ import annotations

from . import ErnestError
from .config import Config

PROVIDERS = ("gmail", "outlook")


class UnknownProvider(ErnestError):
    pass


def accounts(cfg: Config) -> list[tuple[str, str]]:
    """Return [(provider, name), …] parsed from cfg.accounts."""
    out: list[tuple[str, str]] = []
    for entry in cfg.accounts:
        if ":" in entry:
            provider, name = entry.split(":", 1)
        else:
            provider, name = "gmail", entry
        provider, name = provider.strip().lower(), name.strip()
        if provider not in PROVIDERS:
            raise UnknownProvider(
                f"unknown mail provider {provider!r} in account {entry!r}"
            )
        if name:
            out.append((provider, name))
    return out


def unread(cfg: Config, provider: str, account: str, max_results: int = 25) -> list[dict]:
    if provider == "gmail":
        from . import gmail

        return gmail.unread(cfg, account, max_results)
    if provider == "outlook":
        from . import outlook

        return outlook.unread(cfg, account, max_results)
    raise UnknownProvider(f"unknown mail provider: {provider}")


def sent(cfg: Config, provider: str, account: str, max_results: int = 12) -> list[dict]:
    if provider == "gmail":
        from . import gmail

        return gmail.sent(cfg, account, max_results)
    if provider == "outlook":
        from . import outlook

        return outlook.sent(cfg, account, max_results)
    raise UnknownProvider(f"unknown mail provider: {provider}")


def recent(cfg: Config, provider: str, account: str, max_results: int = 100) -> list[dict]:
    if provider == "gmail":
        from . import gmail

        return gmail.recent(cfg, account, max_results)
    if provider == "outlook":
        from . import outlook

        return outlook.recent(cfg, account, max_results)
    raise UnknownProvider(f"unknown mail provider: {provider}")
