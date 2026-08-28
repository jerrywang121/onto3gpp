"""Tests for AI merge judge + embedding-guided ABox merge."""

from onto3gpp.embed import EmbeddingIndex, HashEmbedder
from onto3gpp.ingest.merge_judge import MergeDecision, MergeJudge, _denied, _normalize, decide
from onto3gpp.ingest.merge import merge_abox
from onto3gpp.ontology.abox import ABox, ABoxConcept


def _concept(cid, canonical, ctype="network_function"):
    return ABoxConcept(id=cid, canonical=canonical, type=ctype)


def test_normalize_sorted_tokens_and_collapse():
    assert _normalize("NG-AP") == "ap ng"
    assert _normalize("  ng  ap  ") == "ap ng"
    assert _normalize("DCI-1-0") == "0 1 dci"
    assert _normalize("DCI_1_0") == "0 1 dci"
    assert _normalize("E-UTRAN") == "e utran"


def test_denied_dci_variants_not_merged():
    assert _denied("dci-1-0", "dci-0-1") is True
    assert _denied("DCI-1-0", "DCI-0-1") is True
    assert _denied("dci_1_0", "dci_0_1") is True
    # Same denylisted token set via normalized should also be denied
    assert _denied("DCI-1-0", "DCI-1-0") is True  # same denylisted set both ways trivially denied? Actually frozenset in _DENYLIST_NORMALIZE
    # Non-denylisted pair not denied
    assert _denied("NGAP", "NG-AP") is False
    assert _denied("ACTIVE", "INACTIVE") is False


def test_judge_deterministic_merges_when_normalized():
    judge = MergeJudge(llm_client=None)
    # NGAP and NG-AP have same sorted tokens "ap ng" vs "ngap"? Wait NGAP normalized is "ngap", NG-AP is "ap ng" — not equal!
    # So deterministic won't merge hyphen-concatenated forms — that's expected; LLM needed for that.
    # Use a truly normalized-equal pair: "QoS Flow" vs "qos  flow"
    res = judge.judge("QoS Flow", "concept", [{"id": "a", "canonical": "qos  flow", "type": "concept", "cosine": 0.9}])
    assert res["decision"] == "MERGE"
    assert res["target"] == "a"


def test_judge_deterministic_add_when_distinct():
    judge = MergeJudge(llm_client=None)
    res = judge.judge("ACTIVE", "concept", [{"id": "a", "canonical": "INACTIVE", "type": "concept", "cosine": 0.9}])
    assert res["decision"] == "ADD"
    assert res["target"] is None


def test_judge_no_neighbours_is_add():
    judge = MergeJudge(llm_client=None)
    res = judge.judge("NGAP", "concept", [])
    assert res["decision"] == "ADD"


def test_decide_respects_threshold():
    e = HashEmbedder(dim=64)
    idx = EmbeddingIndex(dim=64, embedder=e)
    idx.add_many([("a", "NGAP")])
    judge = MergeJudge(llm_client=None)
    # Very high threshold filters out even close match → ADD
    dec = decide("NGAP", "concept", idx, judge, top_k=5, threshold=0.99, id_to_canonical={"a": "NGAP"}, id_to_type={"a": "concept"})
    # NGAP exact should still be 1.0, so with threshold 0.99 it passes — should MERGE
    assert dec.decision == "MERGE"
    # Now with threshold 1.01 (above max) → empty neighbours → ADD
    dec2 = decide("NGAP", "concept", idx, judge, top_k=5, threshold=1.01, id_to_canonical={"a": "NGAP"}, id_to_type={"a": "concept"})
    assert dec2.decision == "ADD"


def test_merge_abox_with_judge_alias_merges():
    # Use the new embedding-guided merge path
    from onto3gpp.ingest.merge import merge_abox_with_judge

    e = HashEmbedder(dim=64)
    idx = EmbeddingIndex(dim=64, embedder=e)
    idx.add_many([("qos", "QoS Flow")])
    judge = MergeJudge(llm_client=None)
    # Need index also containing existing for retrieval; merge_abox_with_judge will search idx
    existing = ABox(concepts=[_concept("qos", "QoS Flow")], relations=[])
    incoming = ABox(concepts=[_concept("qos2", "qos  flow")], relations=[])
    result = merge_abox_with_judge(existing, incoming, index=idx, judge=judge, threshold=0.0, top_k=5)
    assert result.merged_concepts == 1
    assert result.added_concepts == 0
    # distinct stays ADD
    existing2 = ABox(concepts=[_concept("active", "ACTIVE")], relations=[])
    e2 = HashEmbedder(dim=64)
    idx2 = EmbeddingIndex(dim=64, embedder=e2)
    idx2.add_many([("active", "ACTIVE")])
    incoming2 = ABox(concepts=[_concept("inactive", "INACTIVE")], relations=[])
    result2 = merge_abox_with_judge(existing2, incoming2, index=idx2, judge=judge, threshold=0.0, top_k=5)
    assert result2.added_concepts == 1
    assert result2.merged_concepts == 0


def test_llm_hallucinated_id_falls_back_to_add(monkeypatch):
    class FakeClient:
        def __init__(self):
            from types import SimpleNamespace

            self.config = SimpleNamespace(enabled=True)

        def complete(self, prompt: str) -> str:
            return '{"decision": "MERGE", "target": "not-a-neighbour", "reason": "hallucinated"}'

    judge = MergeJudge(llm_client=FakeClient())
    res = judge.judge("NGAP", "concept", [{"id": "a", "canonical": "UPF", "type": "concept", "cosine": 0.4}])
    assert res["decision"] == "ADD"
    assert res["target"] is None


def test_llm_disabled_path_uses_deterministic():
    class FakeClient:
        def __init__(self):
            from types import SimpleNamespace

            self.config = SimpleNamespace(enabled=False)

        def complete(self, prompt: str) -> str:
            return '{"decision": "MERGE", "target": "a", "reason": "should not be called"}'

    judge = MergeJudge(llm_client=FakeClient())
    # With LLM disabled, should fall back to normalized match; this pair matches
    res = judge.judge("QoS Flow", "concept", [{"id": "a", "canonical": "qos flow", "type": "concept", "cosine": 0.9}])
    assert res["decision"] == "MERGE"
    # Distinct should be ADD even though LLM would say MERGE
    res2 = judge.judge("ACTIVE", "concept", [{"id": "a", "canonical": "INACTIVE", "type": "concept", "cosine": 0.9}])
    assert res2["decision"] == "ADD"
