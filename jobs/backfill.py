"""Backfill the library with recent mail history (read + unread).

Triage only sees new/unread mail, so the library stays shallow. This imports the
newest N messages per account into the library so Ernest actually knows your
history — for chat, ask, and drafting context. Read-only; idempotent (already-
ingested messages are skipped by content fingerprint).

  python -m jobs.backfill                 # default 60 per account
  python -m jobs.backfill --limit 200     # go deeper (slower)
"""

from __future__ import annotations

import argparse

from ernest import library, mail
from ernest.audit import log_event
from ernest.config import load
from ernest.store import connect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()

    cfg = load()
    conn = connect()
    total = 0
    for provider, account in mail.accounts(cfg):
        try:
            msgs = mail.recent(cfg, provider, account, max_results=args.limit)
        except Exception as exc:
            print(f"[{provider}:{account}] {exc}")
            log_event("backfill", "fetch_failed",
                      {"account": account, "error": str(exc)})
            continue
        added = 0
        for m in msgs:
            # No local seen-gate: the library backend dedups by content
            # fingerprint, so this stays correct across backend switches and
            # re-runs (already-stored messages return 0).
            n = library.add_document(
                conn, cfg, f"{provider}:{account}",
                f"{m.get('subject','')} — {m.get('sender','')}", m.get("body_text", ""),
            )
            added += 1 if n else 0
        total += added
        print(f"[{provider}:{account}] ingested {added} of {len(msgs)} fetched")
        log_event("backfill", "account_done", {"account": account, "ingested": added})
    print(f"\ndone — {total} messages added to the library.")


if __name__ == "__main__":
    main()
