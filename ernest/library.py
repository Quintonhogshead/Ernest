"""The library: hybrid keyword + semantic retrieval over everything Ernest sees.

Chunks live in ``state/ernest.db``: an FTS5 table for keyword search and a
packed-float32 embedding column for semantic search. Queries run both and merge
by reciprocal-rank fusion. Embeddings are best-effort — if no OpenAI key is
configured, ingestion still stores chunks and search falls back to FTS only.

Retrieved chunks are untrusted data: callers must feed them to the model as
quoted context, never as instructions.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from .audit import log_event
from .config import Config
from .embed import cosine, embed, pack, unpack
from .store import has_fts, mark_seen

_RRF_K = 60


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Split on paragraph boundaries, packing paragraphs up to ~size chars."""
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(buf) + len(para) + 2 <= size:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            if buf:
                chunks.append(buf)
            if len(para) <= size:
                buf = para
            else:  # a single huge paragraph: hard-split with overlap
                step = size - overlap
                for i in range(0, len(para), step):
                    chunks.append(para[i : i + size])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def add_document(
    conn: sqlite3.Connection, cfg: Config, source: str, title: str, text: str
) -> int:
    """Ingest one document. Returns chunks added (0 if empty or already seen).

    Routes to Postgres+pgvector when DATABASE_URL is set, else the SQLite backend.
    """
    if cfg.database_url:
        from . import pgstore

        try:
            return pgstore.add_document(cfg, source, title, text)
        except Exception as exc:  # never let a library write break a job
            log_event("library", "pg_add_failed", {"source": source, "error": str(exc)})
            return 0
    text = (text or "").strip()
    if not text:
        return 0
    if not mark_seen(conn, "doc", _fingerprint(text)):
        return 0
    chunks = chunk_text(text)
    if not chunks:
        return 0

    vectors: list[bytes | None] = [None] * len(chunks)
    if cfg.openai_api_key:
        try:
            vectors = [pack(v) for v in embed(cfg, chunks)]
        except Exception as exc:  # embeddings are best-effort
            log_event("library", "embed_failed", {"source": source, "error": str(exc)})
            vectors = [None] * len(chunks)

    now = datetime.now(timezone.utc).isoformat()
    fts = has_fts(conn)
    for chunk, vec in zip(chunks, vectors):
        cur = conn.execute(
            "INSERT INTO library (source, title, chunk, embedding, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, title, chunk, vec, now),
        )
        if fts:
            conn.execute(
                "INSERT INTO library_fts (rowid, chunk, title, source) "
                "VALUES (?, ?, ?, ?)",
                (cur.lastrowid, chunk, title, source),
            )
    conn.commit()
    log_event("library", "ingested", {"source": source, "chunks": len(chunks)})
    return len(chunks)


def _fts_query(query: str) -> str:
    """Build a safe FTS5 MATCH string: quote each term, OR them for recall.

    Quoting each token individually neutralizes FTS operators without forcing a
    strict phrase match (which quoting the whole query would do). OR keeps recall
    high; bm25 still ranks documents matching more terms higher.
    """
    import re

    terms = re.findall(r"\w+", query)
    return " OR ".join(f'"{t}"' for t in terms)


def _fts_ranked(conn: sqlite3.Connection, query: str, limit: int) -> list[int]:
    if not has_fts(conn):
        return []
    safe = _fts_query(query)
    if not safe:
        return []
    try:
        rows = conn.execute(
            "SELECT rowid FROM library_fts WHERE library_fts MATCH ? "
            "ORDER BY bm25(library_fts) LIMIT ?",
            (safe, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r["rowid"] for r in rows]


def _semantic_ranked(conn: sqlite3.Connection, cfg: Config, query: str, limit: int):
    if not cfg.openai_api_key:
        return []
    try:
        qvec = embed(cfg, [query])[0]
    except Exception as exc:
        log_event("library", "query_embed_failed", {"error": str(exc)})
        return []
    scored: list[tuple[float, int]] = []
    for row in conn.execute("SELECT id, embedding FROM library WHERE embedding IS NOT NULL"):
        scored.append((cosine(qvec, unpack(row["embedding"])), row["id"]))
    scored.sort(reverse=True)
    return [rid for _, rid in scored[:limit]]


def search(conn: sqlite3.Connection, cfg: Config, query: str, k: int = 8) -> list[dict]:
    """Hybrid search: FTS + semantic, merged by reciprocal-rank fusion.

    When ``cfg.rerank`` is on, a wider candidate pool is fetched and an LLM
    reranker reorders it to the top-k (see ``ernest.rerank``); otherwise the
    fused top-k is returned directly. Routes to Postgres+pgvector when
    DATABASE_URL is set, else the SQLite backend.
    """
    pool = max(k, cfg.rerank_candidates) if cfg.rerank else k
    hits = _hybrid(conn, cfg, query, pool)
    if cfg.rerank and len(hits) > 1:
        from . import rerank as _rerank

        return _rerank.rerank(cfg, query, hits, k)
    return hits[:k]


def _hybrid(conn: sqlite3.Connection, cfg: Config, query: str, k: int) -> list[dict]:
    """Fused FTS + semantic candidates, top-k by RRF (no reranking)."""
    if cfg.database_url:
        from . import pgstore

        try:
            return pgstore.search(cfg, query, k)
        except Exception as exc:
            log_event("library", "pg_search_failed", {"error": str(exc)})
            return []
    per = max(20, k)
    fused: dict[int, float] = {}
    for ranked in (_fts_ranked(conn, query, per), _semantic_ranked(conn, cfg, query, per)):
        for rank, rid in enumerate(ranked):
            fused[rid] = fused.get(rid, 0.0) + 1.0 / (_RRF_K + rank)
    if not fused:
        return []
    top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
    out: list[dict] = []
    for rid, score in top:
        row = conn.execute(
            "SELECT source, title, chunk FROM library WHERE id = ?", (rid,)
        ).fetchone()
        if row:
            out.append(
                {"source": row["source"], "title": row["title"],
                 "chunk": row["chunk"], "score": round(score, 5)}
            )
    return out


def recent_notes(conn: sqlite3.Connection, cfg: Config, n: int = 10) -> list[dict]:
    """The things Quinton told Ernest to remember, newest first (source='note')."""
    if cfg.database_url:
        from . import pgstore

        try:
            return pgstore.recent_notes(cfg, n)
        except Exception:
            return []
    rows = conn.execute(
        "SELECT chunk, ts FROM library WHERE source='note' ORDER BY ts DESC LIMIT ?",
        (n,),
    ).fetchall()
    return [{"chunk": r["chunk"], "ts": r["ts"]} for r in rows]
