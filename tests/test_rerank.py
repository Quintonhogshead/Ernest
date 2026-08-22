"""Rerank + eval-metric tests. No API keys needed: the reranker is monkeypatched."""

import math

import pytest

from ernest import eval as ev
from ernest import rerank
from ernest.config import Config


def _hits(n):
    return [{"source": "file:x", "title": f"t{i}", "chunk": f"chunk {i}"} for i in range(n)]


# ── rerank._clean_order: always a valid full permutation ─────────────────────

def test_clean_order_reorders():
    assert rerank._clean_order([2, 0, 1], 3) == [2, 0, 1]


def test_clean_order_appends_missing():
    # model only ranked index 2 → the rest follow in original order
    assert rerank._clean_order([2], 4) == [2, 0, 1, 3]


def test_clean_order_drops_bad_and_dupes():
    assert rerank._clean_order([5, 1, 1, -1, "x", 0], 3) == [1, 0, 2]


def test_rerank_reorders_via_model(monkeypatch):
    hits = _hits(4)
    monkeypatch.setattr(rerank, "complete_json",
                        lambda *a, **k: {"ranking": [3, 2, 1, 0]})
    out = rerank.rerank(Config(), "q", hits, k=2)
    assert [h["chunk"] for h in out] == ["chunk 3", "chunk 2"]


def test_rerank_fails_safe_to_original(monkeypatch):
    hits = _hits(3)
    def boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(rerank, "complete_json", boom)
    out = rerank.rerank(Config(), "q", hits, k=3)
    assert [h["chunk"] for h in out] == ["chunk 0", "chunk 1", "chunk 2"]


def test_rerank_trivial_pool_no_call(monkeypatch):
    monkeypatch.setattr(rerank, "complete_json",
                        lambda *a, **k: pytest.fail("should not call model"))
    assert rerank.rerank(Config(), "q", _hits(1), k=8) == _hits(1)
    assert rerank.rerank(Config(), "q", [], k=8) == []


# ── eval metrics ─────────────────────────────────────────────────────────────

def test_mrr():
    assert ev.mrr([0, 0, 1, 0]) == pytest.approx(1 / 3)
    assert ev.mrr([0, 0, 0]) == 0.0


def test_hit_and_precision():
    assert ev.hit_at_k([0, 1, 0], 3) == 1.0
    assert ev.hit_at_k([0, 0, 0], 3) == 0.0
    assert ev.precision_at_k([1, 0, 1, 1], 4) == 0.75


def test_ndcg_perfect_vs_reversed():
    ideal = [2, 1, 0]
    worst = [0, 1, 2]
    assert ev.ndcg_at_k(ideal, 3) == pytest.approx(1.0)
    assert ev.ndcg_at_k(worst, 3) < 1.0
    assert ev.ndcg_at_k([0, 0, 0], 3) == 0.0


def test_gold_grader_substring():
    grade = ev.make_gold_grader(["Garamond", "serif"])
    assert grade("q", {"chunk": "We used a Garamond typeface"}) == 1
    assert grade("q", {"chunk": "nothing relevant here"}) == 0


def test_mean_metrics_empty():
    assert ev.mean_metrics([])["ndcg@k"] == 0.0
