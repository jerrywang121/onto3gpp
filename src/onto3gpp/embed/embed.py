"""Pluggable embedding layer — CPU-only local + swappable API.

Two local impls (stdlib only) and two API impls share the same Embedder
protocol. See prototypes/ai-merge/embed.py for the prototype origin.
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
            t_norm = t.replace("-", " ").replace("_", " ")
            padded = f" {t_norm} "
            ngrams: list[str] = []
            for n in (3, 4, 5):
                for i in range(len(padded) - n + 1):
                    ngrams.append(padded[i : i + n])
            for tok in t_norm.split():
                ngrams.append(f"w:{tok}")
            toks = t_norm.split()
            for i in range(len(toks) - 1):
                ngrams.append(f"bw:{toks[i]} {toks[i+1]}")

            for ng in ngrams:
                h = int(hashlib.md5(ng.encode()).hexdigest(), 16)
                idx = h % self.dim
                vec[idx] += 1.0
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
# GgufEmbedder — direct HF GGUF (unsloth/embeddinggemma-300m-GGUF BF16)
# ---------------------------------------------------------------------------
class GgufEmbedder:
    """Load a GGUF embedding model directly via llama-cpp-python.

    Default: ``unsloth/embeddinggemma-300m-GGUF`` / ``embeddinggemma-300M-BF16.gguf``
    (768-d, ~612 MB). Downloads from Hugging Face on first use and caches in
    ``~/.cache/huggingface/hub``. CPU-only, no Ollama daemon needed.

    Config keys:
      repo_id  — HF repo (default ``unsloth/embeddinggemma-300m-GGUF``)
      filename — GGUF file in repo (default ``embeddinggemma-300M-BF16.gguf``)
      model_path — direct local path override (skip HF download)
      dim      — expected dim (inferred from model if mismatch)
      n_ctx / n_batch / n_threads — llama.cpp tuning
    """

    # Process-wide singleton so repeated get_embedder() calls don't reload 600 MB.
    _llama_singleton: dict[str, object] = {}
    _lock_singleton: object = None

    def __init__(
        self,
        repo_id: str = "unsloth/embeddinggemma-300m-GGUF",
        filename: str = "embeddinggemma-300M-BF16.gguf",
        model_path: str | None = None,
        dim: int = 768,
        n_ctx: int = 512,
        n_batch: int = 512,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,
        verbose: bool = False,
    ) -> None:
        self.repo_id = repo_id
        self.filename = filename
        self.model_path = model_path
        self.dim = dim
        self.n_ctx = n_ctx
        self.n_batch = n_batch
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._llama = None  # lazy
        # lazy import guard — defer heavy import until first embed

    def _ensure_model(self):  # type: ignore[no-untyped-def]
        if self._llama is not None:
            return self._llama
        # Resolve file path
        if self.model_path:
            from pathlib import Path as _Path

            path = str(_Path(self.model_path).expanduser().resolve())
        else:
            try:
                from huggingface_hub import hf_hub_download as _dl
            except ImportError as e:
                raise RuntimeError(
                    "GgufEmbedder needs huggingface-hub: pip install huggingface-hub"
                ) from e
            path = _dl(repo_id=self.repo_id, filename=self.filename)
        # Singleton keyed by path
        key = path
        # Use class-level cache
        import threading as _threading

        if GgufEmbedder._lock_singleton is None:
            GgufEmbedder._lock_singleton = _threading.Lock()
        with GgufEmbedder._lock_singleton:  # type: ignore[union-attr]
            if key in GgufEmbedder._llama_singleton:
                self._llama = GgufEmbedder._llama_singleton[key]
                # infer dim
                try:
                    self.dim = int(self._llama.n_embd())  # type: ignore[union-attr]
                except Exception:
                    pass
                return self._llama
            try:
                from llama_cpp import Llama as _Llama
            except ImportError as e:
                raise RuntimeError(
                    "GgufEmbedder needs llama-cpp-python: pip install llama-cpp-python"
                ) from e
            llm = _Llama(
                model_path=path,
                embedding=True,
                n_ctx=self.n_ctx,
                n_batch=self.n_batch,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers,
                verbose=self.verbose,
            )
            try:
                inferred = int(llm.n_embd())
                if inferred != self.dim:
                    self.dim = inferred
            except Exception:
                pass
            GgufEmbedder._llama_singleton[key] = llm
            self._llama = llm
            return llm

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        llm = self._ensure_model()
        # llama_cpp Llama.embed handles batching internally; returns list[list[float]]
        try:
            vecs = llm.embed(texts)  # type: ignore[union-attr]
        except TypeError:
            # older API: embed(input, normalize=False)
            vecs = llm.embed(texts, normalize=False)  # type: ignore[union-attr]
        # llama returns list for single string vs list — normalize
        if vecs and isinstance(vecs[0], float):
            vecs = [vecs]  # type: ignore[list-item]
        if vecs and len(vecs[0]) != self.dim:
            self.dim = len(vecs[0])
        out: list[list[float]] = []
        for v in vecs:  # type: ignore[union-attr]
            norm = math.sqrt(sum(float(x) * float(x) for x in v))
            if norm > 0:
                out.append([float(x) / norm for x in v])
            else:
                out.append([float(x) for x in v])
        return out


# ---------------------------------------------------------------------------
# OllamaEmbedder — local HTTP (embeddinggemma:300m etc.)
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
        url = f"{self.api_base}/api/embed"
        body = json.dumps({"model": self.model, "input": texts}).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            vecs = data.get("embeddings", [])
        except urllib.error.HTTPError:
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


# ---------------------------------------------------------------------------
# ApiEmbedder — customer-defined endpoint (OpenAI-compatible)
# ---------------------------------------------------------------------------
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
        api_key_env: str | None = None,
        dim: int = 1536,
        timeout: float = 15.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.api_key_env = api_key_env
        # Resolve declarative wiring: api_key_env → env var
        if not self.api_key and self.api_key_env:
            import os as _os

            self.api_key = _os.getenv(self.api_key_env) or None
        self.dim = dim
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.api_base}/embeddings"
        body = json.dumps({"model": self.model, "input": texts}).encode()
        # Re-resolve at call time in case env was set after construction
        key = self.api_key
        if not key and getattr(self, "api_key_env", None):
            import os as _os2

            key = _os2.getenv(self.api_key_env) or None
        if not key:
            import os as _os3

            key = _os3.getenv("COMMAND_CODE_API_KEY") or _os3.getenv("OPENAI_API_KEY")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ApiEmbedder HTTP {e.code}: {e.read().decode()[:500]}") from e
        vecs = [d["embedding"] for d in data.get("data", [])]
        if vecs and len(vecs[0]) != self.dim:
            self.dim = len(vecs[0])
        out: list[list[float]] = []
        for v in vecs:
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v] if norm > 0 else v)
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_embedder(cfg: dict | None) -> HashEmbedder | TfIdfEmbedder | OllamaEmbedder | ApiEmbedder | GgufEmbedder:
    """Return an Embedder from a dict config.

    cfg examples:
      {"kind": "hash", "dim": 384}
      {"kind": "tfidf", "dim": 384, "corpus": [...]}
      {"kind": "gguf", "repo_id": "unsloth/embeddinggemma-300m-GGUF",
       "filename": "embeddinggemma-300M-BF16.gguf", "dim": 768}
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
    if kind == "gguf":
        return GgufEmbedder(
            repo_id=cfg.get("repo_id", "unsloth/embeddinggemma-300m-GGUF"),
            filename=cfg.get("filename", "embeddinggemma-300M-BF16.gguf"),
            model_path=cfg.get("model_path"),
            dim=int(cfg.get("dim", 768)),
            n_ctx=int(cfg.get("n_ctx", 512)) if cfg.get("n_ctx") is not None else 512,
            n_batch=int(cfg.get("n_batch", 512)) if cfg.get("n_batch") is not None else 512,
            n_gpu_layers=int(cfg.get("n_gpu_layers", 0)) if cfg.get("n_gpu_layers") is not None else 0,
            verbose=bool(cfg.get("verbose", False)),
        )
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
            api_key_env=cfg.get("api_key_env"),
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
    """In-memory cosine index over concept embeddings.

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

    def search_texts(
        self, texts: list[str], top_k: int = 5, threshold: float = 0.0
    ) -> list[list[tuple[str, float]]]:
        """Batch variant of search_text — one embed call for all queries.

        Critical for GGUF/CPU models where per-text overhead dominates.
        Returns list aligned with texts.
        """
        if not texts:
            return []
        qvecs = self.embedder.embed(texts)
        return [self.search(qv, top_k=top_k, threshold=threshold) for qv in qvecs]
