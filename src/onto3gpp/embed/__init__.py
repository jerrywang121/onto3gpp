"""Pluggable embedding layer — CPU-only local + swappable API."""

from onto3gpp.embed.embed import (
    ApiEmbedder,
    EmbeddingIndex,
    HashEmbedder,
    OllamaEmbedder,
    TfIdfEmbedder,
    get_embedder,
)

__all__ = [
    "HashEmbedder",
    "TfIdfEmbedder",
    "OllamaEmbedder",
    "ApiEmbedder",
    "EmbeddingIndex",
    "get_embedder",
]
