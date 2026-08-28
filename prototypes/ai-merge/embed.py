"""Pluggable embedding layer — CPU-only local + swappable API.

Two local impls (stdlib only) and one API impl share the same Embedder
protocol. Production path: src/onto3gpp/embed/.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# HashEmbedder — default local, lexical, zero deps
# ---------------------------------------------------------------------------
class HashEmbedder:
    """Char 3-5-gram hashing → L2-normalized vector (deterministic, CPU-only).

    Captures hyphen/space/case variants (NGAP/NG-AP, E-UTRAN/EUTRAN) without a
    model download. 384-d by default, swappable via `dim`.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            t = (text or "").lower().strip()
            if not t:
                out.append(vec)
                continue
            # normalize hyphens/_ to spaces so NG-AP/NGAP, SL-DRX/SL DRX match lexically
            t_norm = t.replace("-", " ").replace("_", " ")
            padded = f" {t_norm} "
            # char 3..5-grams over padded string
            ngrams: list[str] = []
            for n in (3, 4, 5):
                for i in range(len(padded) - n + 1):
                    ngrams.append(padded[i : i + n])
            # word tokens (helps alias/full-form overlap)
            for tok in t_norm.split():
                ngrams.append(f"w:{tok}")
            toks = t_norm.split()
            for i in range(len(toks) - 1):
                ngrams.append(f"bw:{toks[i]} {toks[i+1]}")

            for ng in ngrams:
                h = int(hashlib.md5(ng.encode()).hexdigest(), 16)
                idx = h % self.dim
                vec[idx] += 1.0
                # signed second hash for mild decorrelation
                h2 = int(hashlib.md5((ng + "#2").encode()).hexdigest(), 16)
                vec[h2 % self.dim] += 0.3 if (h2 & 1) else -0.3

            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            out.append(vec)
        return out


# ---------------------------------------------------------------------------
# TfIdfEmbedder — optional corpus-weighted variant
# ---------------------------------------------------------------------------
class TfIdfEmbedder:
    """TF-IDF-weighted hash embedding (still hash-bucketed, CPU-only).

    Fit on a corpus to learn IDF per hash bucket, then scale counts by IDF
    at embed time. Keeps the same fixed dim as HashEmbedder so index/search
    stays identical. If no corpus is given, behaves like HashEmbedder.
    """

    def __init__(self, dim: int = 384, corpus: list[str] | None = None) -> None:
        self.dim = dim
        self._idf: list[float] | None = None
        self._base = HashEmbedder(dim=dim)
        if corpus:
            self.fit(corpus)

    def fit(self, corpus: list[str]) -> None:
        n = len(corpus) or 1
        df = [0] * self.dim
        for text in corpus:
            seen: set[int] = set()
            t = (text or "").lower().strip()
            padded = f" {t} "
            for ng_len in (3, 4, 5):
                for i in range(len(padded) - ng_len + 1):
                    ng = padded[i : i + ng_len]
                    h = int(hashlib.md5(ng.encode()).hexdigest(), 16) % self.dim
                    seen.add(h)
            for s in seen:
                df[s] += 1
        # smoothed idf
        self._idf = [math.log((n + 1) / (d + 1)) + 1.0 for d in df]

    def embed(self, texts: list[str]) -> list[list[float]]:
        base_vecs = self._base.embed(texts)
        if self._idf is None:
            return base_vecs
        out: list[list[float]] = []
        for vec in base_vecs:
            w = [v * self._idf[i] for i, v in enumerate(vec)]
            norm = math.sqrt(sum(x * x for x in w))
            if norm > 0:
                w = [x / norm for x in w]
            out.append(w)
        return out


# ---------------------------------------------------------------------------
# ApiEmbedder — customer-defined endpoint (OpenAI-compatible)
# ---------------------------------------------------------------------------
class OllamaEmbedder:
    """POST to Ollama's /api/embed endpoint (local CPU, e.g. embeddinggemma:300m).

    Mirrors ApiEmbedder but speaks Ollama's native format:
      POST {api_base}/api/embed  {"model": "...", "input": "..."|["..."]}
    Also accepts the OpenAI-compatible {api_base}/v1/embeddings shim when
    available. Dim is inferred (embeddinggemma:300m → 768).
    """

    def __init__(
        self,
        api_base: str = "http://localhost:11434",
        model: str = "embeddinggemma:300m",
        dim: int = 768,
        timeout: float = 15.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.dim = dim
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Try native Ollama /api/embed first (batched: input is list)
        url = f"{self.api_base}/api/embed"
        body = json.dumps({"model": self.model, "input": texts}).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            vecs = data.get("embeddings", [])
        except urllib.error.HTTPError:
            # Fallback: OpenAI-compatible shim
            url2 = f"{self.api_base}/v1/embeddings"
            body2 = json.dumps({"model": self.model, "input": texts}).encode()
            req2 = urllib.request.Request(url2, data=body2, headers=headers, method="POST")
            with urllib.request.urlopen(req2, timeout=self.timeout) as resp2:
                data2 = json.loads(resp2.read().decode())
            vecs = [d["embedding"] for d in data2.get("data", [])]

        if vecs and len(vecs[0]) != self.dim:
            self.dim = len(vecs[0])
        out: list[list[float]] = []
        for v in vecs:
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v] if norm > 0 else list(v))
        return out


class ApiEmbedder:
    """POST to an OpenAI-compatible /v1/embeddings endpoint.

    Config: api_base (e.g. https://api.openai.com/v1), model, api_key, dim.
    Swapping local→API is a one-line config change; the vector dim is
    inferred from the first response if not given.
    """

    def __init__(
        self,
        api_base: str,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dim: int = 1536,
        timeout: float = 15.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dim = dim
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.api_base}/embeddings"
        body = json.dumps({"model": self.model, "input": texts}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ApiEmbedder HTTP {e.code}: {e.read().decode()[:500]}") from e
        vecs = [d["embedding"] for d in data.get("data", [])]
        if vecs and len(vecs[0]) != self.dim:
            self.dim = len(vecs[0])
        # L2-normalize for cosine parity with local embedders
        out: list[list[float]] = []
        for v in vecs:
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v] if norm > 0 else v)
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_embedder(cfg: dict | None) -> HashEmbedder | TfIdfEmbedder | OllamaEmbedder | ApiEmbedder:
    """Return an Embedder from a dict config.

    cfg examples:
      {"kind": "hash", "dim": 384}
      {"kind": "tfidf", "dim": 384, "corpus": [...]}
      {"kind": "ollama", "api_base": "http://localhost:11434",
       "model": "embeddinggemma:300m", "dim": 768}
      {"kind": "api", "api_base": "https://api.openai.com/v1",
       "model": "text-embedding-3-small", "api_key": "...", "dim": 1536}
    Defaults to HashEmbedder(384).
    """
    if not cfg:
        return HashEmbedder(dim=384)
    kind = (cfg.get("kind") or "hash").lower()
    dim = int(cfg.get("dim", 384))
    if kind == "ollama":
        return OllamaEmbedder(
            api_base=cfg.get("api_base", "http://localhost:11434"),
            model=cfg.get("model", "embeddinggemma:300m"),
            dim=int(cfg.get("dim", 768)),
        )
    if kind == "api":
        return ApiEmbedder(
            api_base=cfg["api_base"],
            model=cfg.get("model", "text-embedding-3-small"),
            api_key=cfg.get("api_key"),
            dim=dim,
        )
    if kind == "tfidf":
        return TfIdfEmbedder(dim=dim, corpus=cfg.get("corpus"))
    return HashEmbedder(dim=dim)


# ---------------------------------------------------------------------------
# Brute-force cosine index (replaceable with FAISS/Chroma later)
# ---------------------------------------------------------------------------
@dataclass
class EmbeddingIndex:
    """In-memory cosine index over concept embeddings (dim inferred from embedder).

    Stores id→vector and id→text. Search is brute-force dot product
    (vectors are L2-normalized, so dot==cosine). Good for ≤100k concepts;
    swap the backend to FAISS for larger graphs.
    """

    dim: int
    embedder: HashEmbedder | TfIdfEmbedder | ApiEmbedder
    ids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    _id_to_idx: dict[str, int] = field(default_factory=dict)

    def add(self, cid: str, text: str, vector: list[float] | None = None) -> None:
        if cid in self._id_to_idx:
            return
        vec = vector if vector is not None else self.embedder.embed([text])[0]
        self._id_to_idx[cid] = len(self.ids)
        self.ids.append(cid)
        self.texts.append(text)
        self.vectors.append(vec)

    def add_many(self, items: list[tuple[str, str]]) -> None:
        """Batch-add (id, text) pairs — embeds in one call when possible."""
        pending = [(cid, txt) for cid, txt in items if cid not in self._id_to_idx]
        if not pending:
            return
        texts = [t for _, t in pending]
        vecs = self.embedder.embed(texts)
        for (cid, txt), vec in zip(pending, vecs):
            self._id_to_idx[cid] = len(self.ids)
            self.ids.append(cid)
            self.texts.append(txt)
            self.vectors.append(vec)

    def search(
        self, query_vec: list[float], top_k: int = 5, threshold: float = 0.0
    ) -> list[tuple[str, float]]:
        """Return [(id, cosine)] sorted by cosine desc, filtered by threshold."""
        scored: list[tuple[str, float]] = []
        for cid, vec in zip(self.ids, self.vectors):
            # dot product (both L2-normalized)
            s = sum(a * b for a, b in zip(query_vec, vec))
            if s >= threshold:
                scored.append((cid, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def search_text(
        self, text: str, top_k: int = 5, threshold: float = 0.0
    ) -> list[tuple[str, float]]:
        qv = self.embedder.embed([text])[0]
        return self.search(qv, top_k=top_k, threshold=threshold)
