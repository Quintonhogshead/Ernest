"""Email triage across all configured accounts → one Discord digest.

Read-only: reads unread mail, classifies it, records the result, and DMs a
grouped digest. Urgent items get their own immediate message. Optionally ingests
substantive mail into the library. Never sends, drafts, or modifies anything.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ernest import chan, library, mail, triage
from ernest.audit import log_event
from ernest.config import load
from ernest.gmail import GmailAuthError
from ernest.guard import halt_if_paused
from ernest.outlook import OutlookAuthError
from ernest.store import connect, mark_seen

_ORDER = ["urgent", "needs_reply", "needs_action", "fyi", "newsletter", "cold",
          "needs_review"]
_LABELS = {
    "urgent": "🔴 Urgent", "needs_reply": "✉️ Needs reply",
    "needs_action": "📋 Needs action", "fyi": "ℹ️ FYI",
    "newsletter": "📰 Newsletter", "cold": "🧊 Cold", "needs_review": "❓ Review",
}
_INGEST_CATEGORIES = {"needs_reply", "needs_action", "fyi"}


def _record(conn, cfg, msg, result):
    conn.execute(
        "INSERT OR REPLACE INTO messages "
        "(gmail_id, account, sender, subject, category, summary, urgent, triaged_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (msg["id"], msg["account"], msg["sender"], msg["subject"],
         result["category"], result["summary"], int(bool(result["urgent"])),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    if cfg.ingest and result["category"] in _INGEST_CATEGORIES:
        library.add_document(
            conn, cfg, f"gmail:{msg['account']}", msg["subject"], msg["body_text"]
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "triage")
    conn = connect()

    grouped: dict[str, dict[str, list[str]]] = {}
    urgent_msgs: list[str] = []
    counts: dict[str, int] = {}

    for provider, account in mail.accounts(cfg):
        try:
            messages = mail.unread(cfg, provider, account, max_results=args.limit)
        except (GmailAuthError, OutlookAuthError) as exc:
            print(f"[{provider}:{account}] {exc}")
            log_event("triage", "auth_error",
                      {"provider": provider, "account": account, "error": str(exc)})
            continue
        label = f"{provider}:{account}"
        new = 0
        for msg in messages:
            if not mark_seen(conn, provider, msg["id"]):
                continue
            new += 1
            result = triage.classify(cfg, msg)
            _record(conn, cfg, msg, result)
            line = f"• {msg['sender'][:40]} — {result['summary']}"
            grouped.setdefault(label, {}).setdefault(result["category"], []).append(line)
            if result.get("urgent"):
                urgent_msgs.append(f"⚠️ [{label}] {msg['sender'][:40]}\n{result['summary']}")
        counts[label] = new
        log_event("triage", "account_done",
                  {"provider": provider, "account": account, "new": new})

    for u in urgent_msgs:
        if args.dry_run:
            print(u + "\n")
        else:
            chan.send(cfg, u)

    digest = _format(grouped)
    if not digest:
        print("nothing new to triage.")
        return
    if args.dry_run:
        print(digest)
    else:
        chan.send(cfg, digest)
    log_event("triage", "digest_sent", {"counts": counts, "dry_run": args.dry_run})


def _format(grouped: dict) -> str:
    if not grouped:
        return ""
    stamp = datetime.now(timezone.utc).strftime("%b %d")
    out = [f"**📬 Triage — {stamp}**"]
    for account, cats in grouped.items():
        out.append(f"\n__{account}__")
        for cat in _ORDER:
            if cat in cats:
                out.append(f"{_LABELS[cat]}")
                out.extend(cats[cat])
    return "\n".join(out)


if __name__ == "__main__":
    main()
