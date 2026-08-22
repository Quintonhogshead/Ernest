"""Email triage across all configured accounts → one Discord digest.

Read-only: reads unread mail, classifies it, records the result, and DMs a
grouped digest. Urgent items get their own immediate message. Optionally ingests
substantive mail into the library. Never sends, drafts, or modifies anything.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ernest import chan, draft, library, mail, triage, voice
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
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cfg = load()
    limit = args.limit if args.limit is not None else cfg.triage_limit
    halt_if_paused(cfg, "triage")
    conn = connect()

    grouped: dict[str, dict[str, list[str]]] = {}
    urgent_msgs: list[str] = []
    draft_msgs: list[str] = []
    counts: dict[str, int] = {}
    drafts_made = 0

    for provider, account in mail.accounts(cfg):
        try:
            messages = mail.unread(cfg, provider, account, max_results=limit)
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
            reason = triage.priority_reason(cfg, msg)
            if reason:
                result["urgent"] = True  # your priority list overrides the model
            _record(conn, cfg, msg, result)
            line = f"• {msg['sender'][:40]} — {result['summary']}"
            grouped.setdefault(label, {}).setdefault(result["category"], []).append(line)
            if result.get("urgent"):
                tag = "⭐ Priority" if reason else "⚠️ Urgent"
                extra = f"\n_{reason}_" if reason else ""
                fallback = (
                    f"{tag} [{label}] {msg['sender'][:40]}\n{result['summary']}{extra}"
                )
                facts = (
                    f"Urgent email in {label} from {msg['sender'][:60]}.\n"
                    f"Subject: {msg['subject'][:100]}\n"
                    f"What it's about: {result['summary']}"
                    + (f"\nWhy it's flagged urgent: {reason}" if reason else "")
                )
                urgent_msgs.append((facts, fallback))
            if (cfg.draft_replies and result["category"] == "needs_reply"
                    and drafts_made < cfg.draft_max):
                try:
                    body = draft.draft_reply(cfg, conn, provider, account, msg)
                    draft_msgs.append(
                        f"✍️ **Draft reply** · {label}\n"
                        f"To: {msg['sender'][:50]} — re: {msg['subject'][:60]}\n\n"
                        f"{body}\n\n_Copy-paste to send. I did not send it._"
                    )
                    drafts_made += 1
                    log_event("triage", "drafted", {"account": account})
                except Exception as exc:
                    log_event("triage", "draft_failed",
                              {"account": account, "error": str(exc)})
        counts[label] = new
        log_event("triage", "account_done",
                  {"provider": provider, "account": account, "new": new})

    for facts, fallback in urgent_msgs:
        u = voice.compose(
            cfg,
            "Give Quinton a heads-up about this one urgent email, in a sentence "
            "or two — enough to know what it is and why it can't wait.",
            facts, fallback,
        )
        if args.dry_run:
            print(u + "\n")
        else:
            chan.send(cfg, u)

    # Drafts carry the actual reply text as the deliverable — sent verbatim, never
    # rewritten by the voice layer.
    for d in draft_msgs:
        if args.dry_run:
            print(d + "\n")
        else:
            chan.send(cfg, d)

    fallback = _format(grouped, cfg)
    if not fallback:
        print("nothing new to triage.")
        return
    digest = voice.compose(
        cfg,
        "Summarize Quinton's new mail across his accounts — what needs him and "
        "what you filed away. Keep it brief.",
        _digest_facts(grouped, cfg), fallback,
    )
    if args.dry_run:
        print(digest)
    else:
        chan.send(cfg, digest)
    log_event("triage", "digest_sent", {"counts": counts, "dry_run": args.dry_run})


def _digest_facts(grouped: dict, cfg) -> str:
    """Plain-text facts for the voice layer: same show/file policy as _format,
    but as labeled data (no emoji/markup) for the model to narrate."""
    show = set(cfg.digest_categories)
    lines: list[str] = []
    filed: dict[str, int] = {}
    for account, cats in grouped.items():
        actionable: list[str] = []
        for cat in _ORDER:
            if cat not in cats:
                continue
            if cat in show:
                name = _LABELS[cat].split(" ", 1)[-1].lower()
                for item in cats[cat]:
                    actionable.append(f"  - ({name}) {item.lstrip('• ').strip()}")
            else:
                filed[cat] = filed.get(cat, 0) + len(cats[cat])
        if actionable:
            lines.append(f"Account {account} — needs attention:")
            lines.extend(actionable)
    if filed:
        tally = ", ".join(f"{n} {_LABELS[c].split(' ', 1)[-1].lower()}"
                          for c, n in filed.items())
        lines.append(f"Filed quietly (no action needed): {tally}.")
    if not any(a.startswith("Account") for a in lines):
        lines.insert(0, "Nothing needs you this round.")
    return "\n".join(lines)


def _format(grouped: dict, cfg) -> str:
    if not grouped:
        return ""
    show = set(cfg.digest_categories)
    stamp = datetime.now(timezone.utc).strftime("%b %d")
    body: list[str] = []
    filed: dict[str, int] = {}
    for account, cats in grouped.items():
        shown: list[str] = []
        for cat in _ORDER:
            if cat not in cats:
                continue
            if cat in show:
                shown.append(_LABELS[cat])
                shown.extend(cats[cat])
            else:
                filed[cat] = filed.get(cat, 0) + len(cats[cat])
        if shown:
            body.append(f"\n__{account}__")
            body.extend(shown)

    tally = ", ".join(f"{n} {_LABELS[c].split(' ', 1)[-1].lower()}"
                      for c, n in filed.items()) if filed else ""

    if body:
        out = [f"**📬 Triage — {stamp}**", *body]
        if tally:
            out.append(f"\n_Filed quietly: {tally}._")
        return "\n".join(out)
    # nothing needs you — one quiet line instead of a wall of newsletters
    if tally:
        return f"**📬 Triage — {stamp}** · nothing needs you. _Filed: {tally}._"
    return ""


if __name__ == "__main__":
    main()
