"""Bulk-ingest a Gmail Takeout .mbox into the library (Postgres at scale).

Run this LOCALLY, pointed at Fly Postgres through the proxy, so your GBs of mail
never upload to Fly — your Mac reads the file, embeds, and streams rows to the
cloud DB:

  # terminal 1: open the proxy to the cloud database
  fly mpg proxy kyzl60xzmzmrpj9g -p 16380

  # terminal 2: ingest (source tags where it came from)
  export DATABASE_URL="postgresql://fly-user:PASSWORD@127.0.0.1:16380/fly-db"
  python -m jobs.ingest_mbox ~/Downloads/all-mail.mbox --source gmail:personal

It's resumable: the backend dedups by content fingerprint, so re-running after a
Ctrl-C skips what's already in. Use --skip N to jump ahead, --limit N to cap.
"""

from __future__ import annotations

import argparse

from ernest import library, mbox
from ernest.audit import log_event
from ernest.config import load
from ernest.store import connect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="path to the .mbox file")
    parser.add_argument("--source", default="mbox",
                        help="label for these messages, e.g. gmail:personal")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip", type=int, default=0)
    args = parser.parse_args()

    cfg = load()
    conn = connect()
    if not cfg.database_url:
        print("⚠️  DATABASE_URL not set — ingesting into local SQLite, not Postgres.\n"
              "   Start the proxy and export DATABASE_URL to fill the cloud DB.")

    processed = ingested = 0
    try:
        for m in mbox.iter_messages(args.path, args.limit, args.skip):
            title = f"{m['subject']} — {m['sender']}"[:200]
            n = library.add_document(conn, cfg, args.source, title, m["body_text"])
            processed += 1
            ingested += 1 if n else 0
            if processed % 50 == 0:
                print(f"  processed {processed} · ingested {ingested} new", flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted — progress is saved; re-run to continue.")
    log_event("ingest_mbox", "done",
              {"source": args.source, "processed": processed, "ingested": ingested})
    print(f"\ndone — processed {processed}, ingested {ingested} new messages.")


if __name__ == "__main__":
    main()
