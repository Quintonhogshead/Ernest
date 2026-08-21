"""Manually ingest files into the library.

  python -m jobs.ingest notes.md ./manuscripts/  → recurse dirs, ingest .md/.txt
"""

from __future__ import annotations

import os
import sys

from ernest import library
from ernest.config import load
from ernest.store import connect

_EXTS = {".md", ".txt", ".markdown"}


def _files(paths: list[str]) -> list[str]:
    found: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                found.extend(os.path.join(root, n) for n in names)
        else:
            found.append(p)
    return found


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m jobs.ingest <path>...")
        sys.exit(1)
    cfg = load()
    conn = connect()
    added = skipped = 0
    for path in _files(sys.argv[1:]):
        ext = os.path.splitext(path)[1].lower()
        if ext not in _EXTS:
            print(f"skip (unsupported): {path}")
            skipped += 1
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print(f"skip (unreadable): {path} — {exc}")
            skipped += 1
            continue
        n = library.add_document(conn, cfg, f"file:{path}", os.path.basename(path), text)
        print(f"{'ingested' if n else 'already ingested'} ({n} chunks): {path}")
        added += n
    print(f"\ndone — {added} chunks added, {skipped} files skipped.")


if __name__ == "__main__":
    main()
