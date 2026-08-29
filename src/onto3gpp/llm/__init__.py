"""llm package — LLM client + queued execution."""

from onto3gpp.llm._core import LLMClient, LLMConfig, LLMDisabledError, _resolve_api_key, _extract_json

try:
    from onto3gpp.llm.queue import ModelQueue
except Exception:  # pragma: no cover
    ModelQueue = None  # type: ignore

__all__ = ["LLMClient", "LLMConfig", "LLMDisabledError", "ModelQueue", "_resolve_api_key", "_extract_json"]
