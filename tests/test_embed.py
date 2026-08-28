"""Tests for pluggable embedding (hash/tf-idf/ollama/api) + cosine index."""

from onto3gpp.embed import EmbeddingIndex, HashEmbedder, TfIdfEmbedder, get_embedder


def test_hash_deterministic_and_normed():
    e = HashEmbedder(dim=32)
    v1 = e.embed(["NGAP"])[0]
    v2 = e.embed(["NGAP"])[0]
    assert v1 == v2
    # L2 ~ 1
    import math

    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-9


def test_hash_hyphen_variants_close():
    e = HashEmbedder(dim=128)
    v_ngap = e.embed(["NGAP"])[0]
    v_ng_ap = e.embed(["NG-AP"])[0]
    v_upf = e.embed(["UPF"])[0]

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    assert cos(v_ngap, v_ng_ap) > cos(v_ngap, v_upf)
    # also E-UTRAN vs EUTRAN
    v1 = e.embed(["E-UTRAN"])[0]
    v2 = e.embed(["EUTRAN"])[0]
    assert cos(v1, v2) > 0.55


def test_hash_empty_text_zero_vec():
    e = HashEmbedder(dim=16)
    v = e.embed([""])[0]
    assert v == [0.0] * 16
    v2 = e.embed(["   "])[0]
    assert v2 == [0.0] * 16


def test_tfidf_without_corpus_matches_hash():
    h = HashEmbedder(dim=32)
    t = TfIdfEmbedder(dim=32)
    assert h.embed(["NGAP"]) == t.embed(["NGAP"])


def test_tfidf_fit_changes_weights():
    t = TfIdfEmbedder(dim=32, corpus=["NGAP NGAP", "UPF", "UPF"])
    # fit should set idf
    assert t._idf is not None
    v = t.embed(["NGAP"])[0]
    import math

    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9


def test_index_add_and_search_returns_topk_sorted():
    e = HashEmbedder(dim=64)
    idx = EmbeddingIndex(dim=64, embedder=e)
    idx.add_many([("a", "NGAP"), ("b", "UPF"), ("c", "SMF")])
    # add is idempotent
    idx.add("a", "NGAP")
    assert len(idx.ids) == 3
    res = idx.search_text("NG-AP", top_k=2, threshold=0.0)
    assert len(res) == 2
    # sorted desc
    assert res[0][1] >= res[1][1]
    # NGAP should be top for NG-AP
    assert res[0][0] == "a"


def test_index_search_text_consistent_with_search():
    e = HashEmbedder(dim=32)
    idx = EmbeddingIndex(dim=32, embedder=e)
    idx.add_many([("a", "hello world"), ("b", "goodbye")])
    qv = e.embed(["hello"])[0]
    r1 = idx.search(qv, top_k=1, threshold=0.0)
    r2 = idx.search_text("hello", top_k=1, threshold=0.0)
    assert r1[0][0] == r2[0][0]


def test_get_embedder_factory_kinds():
    assert isinstance(get_embedder(None), HashEmbedder)
    assert isinstance(get_embedder({}), HashEmbedder)
    assert isinstance(get_embedder({"kind": "hash"}), HashEmbedder)
    assert isinstance(get_embedder({"kind": "tfidf"}), TfIdfEmbedder)
    # ollama/api construct without network call
    assert get_embedder({"kind": "ollama"}).model == "embeddinggemma:300m"
    assert get_embedder({"kind": "api", "api_base": "https://x/v1"}).api_base == "https://x/v1"
