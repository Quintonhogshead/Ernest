"""Postgres + pgvector backend for the library (scales to millions of chunks).

Activated when DATABASE_URL is set. Uses an HNSW index for approximate nearest-
neighbour vector search and a GIN full-text index for keyword search; results
are merged by reciprocal-rank fusion — the same hybrid strategy as the SQLite
backend, but with real indexes instead of a brute-force scan.

pgvector must be enabled on the cluster's Extensions page (non-superusers can't
CREATE EXTENSION); this module tolerates that and assumes it's enabled.
"""

from __future__ import annotations

import hashlib
import threading

from .audit import log_event
from .config import Config
from .embed import embed
from .library import chunk_text

_RRF_K = 60
_lock = threading.Lock()
_conn = None
_ready = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id         BIGSERIAL PRIMARY KEY,
  source     TEXT NOT NULL,
  title      TEXT,
  chunk      TEXT NOT NULL,
  doc_fp     TEXT NOT NULL,
  embedding  vector(1536),
  tsv        tsvector GENERATED ALWAYS AS
               (to_tsvector('english', coalesce(title,'') || ' ' || chunk)) STORED,
  ts         TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_doc_fp ON documents (doc_fp);
CREATE INDEX IF NOT EXISTS documents_tsv ON documents USING GIN (tsv);
CREATE INDEX IF NOT EXISTS documents_embed
  ON documents USING hnsw (embedding vector_cosine_ops);
"""


def _connect(cfg: Config):
    import psycopg
    from pgvector.psycopg import register_vector

    # prepare_threshold=None keeps us compatible with pgbouncer transaction pooling.
    conn = psycopg.connect(cfg.database_url, autocommit=True, prepare_threshold=None,
                           connect_timeout=20)
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception:
        pass  # non-superuser: assume enabled via the dashboard Extensions page
    register_vector(conn)
    return conn


def _get(cfg: Config):
    global _conn, _ready
    with _lock:
        if _conn is None:
            _conn = _connect(cfg)
        if not _ready:
            _conn.execute(_SCHEMA)
            _ready = True
        return _conn


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def add_document(cfg: Config, source: str, title: str, text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    doc_fp = _fingerprint(text)
    conn = _get(cfg)
    with _lock:
        exists = conn.execute("SELECT 1 FROM documents WHERE doc_fp=%s LIMIT 1",
                              (doc_fp,)).fetchone()
    if exists:
        return 0
    chunks = chunk_text(text)
    if not chunks:
        return 0
    try:
        vectors = embed(cfg, chunks)
    except Exception as exc:
        log_event("pgstore", "embed_failed", {"source": source, "error": str(exc)})
        vectors = [None] * len(chunks)
    with _lock:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents (source, title, chunk, doc_fp, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(source, title, c, doc_fp, v) for c, v in zip(chunks, vectors)],
            )
    log_event("pgstore", "ingested", {"source": source, "chunks": len(chunks)})
    return len(chunks)


def search(cfg: Config, query: str, k: int = 8) -> list[dict]:
    conn = _get(cfg)
    fused: dict[int, float] = {}
    rows_by_id: dict[int, dict] = {}
    per = max(20, k)  # pull a pool at least as wide as the requested k (reranking)

    # keyword (full-text) ranking
    with _lock:
        kw = conn.execute(
            "SELECT id, source, title, chunk FROM documents "
            "WHERE tsv @@ plainto_tsquery('english', %s) "
            "ORDER BY ts_rank(tsv, plainto_tsquery('english', %s)) DESC LIMIT %s",
            (query, query, per),
        ).fetchall()
    for rank, (rid, source, title, chunk) in enumerate(kw):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (_RRF_K + rank)
        rows_by_id[rid] = {"source": source, "title": title, "chunk": chunk}

    # vector (semantic) ranking via the HNSW index
    try:
        qvec = embed(cfg, [query])[0]
        with _lock:
            vec = conn.execute(
                "SELECT id, source, title, chunk FROM documents "
                "WHERE embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s",
                (qvec, per),
            ).fetchall()
        for rank, (rid, source, title, chunk) in enumerate(vec):
            fused[rid] = fused.get(rid, 0.0) + 1.0 / (_RRF_K + rank)
            rows_by_id[rid] = {"source": source, "title": title, "chunk": chunk}
    except Exception as exc:
        log_event("pgstore", "query_embed_failed", {"error": str(exc)})

    top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
    return [{**rows_by_id[rid], "score": round(score, 5)} for rid, score in top]


def count(cfg: Config) -> int:
    conn = _get(cfg)
    with _lock:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
