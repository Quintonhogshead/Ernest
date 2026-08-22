"""Evaluate retrieval quality — and prove whether reranking helps.

Runs every query in a gold set through the library twice (reranking off, then
on) and prints the ranking metrics side by side, so you can decide whether to
set ERNEST_RERANK=1 based on numbers rather than hope.

  python -m jobs.eval                      # default set, gold labels where present
  python -m jobs.eval --k 8                # cut metrics at rank 8
  python -m jobs.eval --judge              # force LLM-judge grading for every query
  python -m jobs.eval --queries path.jsonl # a custom gold set

Gold-set format — one JSON object per line:

  {"query": "cover font for the poetry book", "relevant": ["serif", "Garamond"]}
  {"query": "what did Karli say about Social Media Pro"}   # no labels → judged

A query with a non-empty "relevant" list is graded by substring match (grade 1
if any substring appears in a retrieved chunk). A query without labels — or every
query under --judge — is graded by the LLM judge (0/1/2).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

from ernest import eval as ev
from ernest.audit import log_event
from ernest.config import load
from ernest.library import search
from ernest.store import connect

_DEFAULT_QUERIES = os.path.join("state", "eval", "queries.jsonl")


def load_queries(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise SystemExit(
            f"No gold set at {path}. Create it (one JSON object per line) — see "
            "the module docstring for the format."
        )
    items: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if not items:
        raise SystemExit(f"{path} is empty.")
    return items


def _grader_for(cfg, item: dict, force_judge: bool):
    relevant = item.get("relevant") or item.get("relevant_substrings") or []
    if relevant and not force_judge:
        return ev.make_gold_grader(relevant), "gold"
    return ev.make_judge_grader(cfg), "judge"


def run_variant(conn, cfg, items, k, force_judge):
    """Return (mean_metrics, n_scored) for one config over the whole query set."""
    per_query = []
    for item in items:
        query = item["query"]
        grader, _ = _grader_for(cfg, item, force_judge)
        hits = search(conn, cfg, query, k=k)
        rels = ev.grade_hits(grader, query, hits)
        per_query.append(ev.metrics_for(rels, k))
    return ev.mean_metrics(per_query), len(per_query)


def _fmt_row(label: str, m: dict) -> str:
    return (f"  {label:<10} hit@k {m['hit@k']:.3f}   mrr {m['mrr']:.3f}   "
            f"ndcg@k {m['ndcg@k']:.3f}   prec@k {m['precision@k']:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default=_DEFAULT_QUERIES)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--judge", action="store_true",
                        help="grade every query with the LLM judge, ignoring labels")
    args = parser.parse_args()

    cfg = load()
    items = load_queries(args.queries)
    conn = connect()

    base_cfg = replace(cfg, rerank=False)
    base, n = run_variant(conn, base_cfg, items, args.k, args.judge)

    print(f"Retrieval eval — {n} queries, k={args.k}, "
          f"backend={'postgres' if cfg.database_url else 'sqlite'}")
    print(_fmt_row("baseline", base))

    rr_cfg = replace(cfg, rerank=True)
    rr, _ = run_variant(conn, rr_cfg, items, args.k, args.judge)
    print(_fmt_row("+rerank", rr))

    delta = {key: rr[key] - base[key] for key in base}
    print(_fmt_row("Δ", delta))
    verdict = "rerank helps" if delta["ndcg@k"] > 0 else (
        "no gain" if delta["ndcg@k"] == 0 else "rerank hurts")
    print(f"\n  → {verdict} (ndcg@k Δ {delta['ndcg@k']:+.3f})")
    log_event("eval", "ran", {"queries": n, "k": args.k,
                              "ndcg_delta": round(delta["ndcg@k"], 4)})


if __name__ == "__main__":
    main()
