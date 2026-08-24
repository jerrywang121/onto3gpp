"""Tests for the eval harness metrics."""

from onto3gpp.evaluate.metrics import mrr, ndcg_at_k, recall_at_k


def test_mrr() -> None:
    # Relevant at rank 2 → MRR = 1/2
    assert mrr([0, 1, 0]) == 0.5
    # No relevant → 0
    assert mrr([0, 0, 0]) == 0.0
    # Relevant at rank 1 → 1.0
    assert mrr([1, 0]) == 1.0


def test_recall_at_k() -> None:
    # 2 relevant total, 1 in top-3 → 0.5
    assert recall_at_k([0, 1, 0], k=3, total_relevant=2) == 0.5
    # k=1, relevant at rank 2 → 0
    assert recall_at_k([0, 1, 0], k=1, total_relevant=2) == 0.0


def test_ndcg_at_k() -> None:
    # Perfect ranking → NDCG = 1.0
    assert ndcg_at_k([1, 1, 1], k=3) == 1.0
    # No relevant → 0
    assert ndcg_at_k([0, 0, 0], k=3) == 0.0
