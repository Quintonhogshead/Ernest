"""Dispatch a research job and deliver the briefing.

  python -m jobs.research "distribution options for indie audiobook publishers"
  python -m jobs.research "..." --with-library   # blend the owner's own corpus
  python -m jobs.research "..." --send           # DM the executive summary

Runs on the frontier research model with web search; saves the full briefing to
research/ and ingests it into the library.
"""

from __future__ import annotations

import argparse

from ernest import chan, library, research
from ernest.audit import log_event
from ernest.config import load
from ernest.store import connect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    parser.add_argument("--with-library", action="store_true",
                        help="prepend relevant chunks from your own corpus")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    cfg = load()
    conn = connect()

    context = ""
    if args.with_library:
        hits = library.search(conn, cfg, args.topic, k=6)
        context = "\n\n".join(f"({h['source']}) {h['chunk']}" for h in hits)

    print(f"researching: {args.topic}\nmodel: {cfg.research_model}\n(this can take a while)…")
    result = research.run(cfg, args.topic, context)

    # Ingest the finished briefing so follow-ups build on it.
    library.add_document(conn, cfg, f"research:{args.topic}",
                         f"Briefing: {args.topic}", result["briefing"])

    print(f"\nsaved: {result['path']}\n")
    print(result["briefing"])

    if args.send:
        chan.send(cfg, f"**🔬 Research: {args.topic}**\n\n{result['summary']}\n\n"
                       f"_Full briefing saved to {result['path']} and added to the library._")
    log_event("research", "delivered", {"topic": args.topic, "path": result["path"]})


if __name__ == "__main__":
    main()
