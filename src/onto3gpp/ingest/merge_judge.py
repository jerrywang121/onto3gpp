"""Embedding retrieval + AI judge — add vs merge decision.

Offline ingest-only: embed(new term) → cosine top-k over existing index → LLM
judge (merge vs add) with deterministic fallback when LLM is disabled.
See prototypes/ai-merge/merge.py for the prototype origin and
docs/adr/0014-ai-merge-embedding-judge.md for the decision record.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from onto3gpp.embed import EmbeddingIndex

try:
    from onto3gpp.llm import LLMClient  # type: ignore
except Exception:  # pragma: no cover
    LLMClient = None  # type: ignore


_DENYLIST_NORMALIZE: set[frozenset[str]] = {
    frozenset(["1", "dci", "0"]),
    frozenset(["dci", "0", "1"]),
}
_DENYLIST_PAIRS: set[frozenset[str]] = {
    frozenset(["dci-1-0", "dci-0-1"]),
    frozenset(["dci_1_0", "dci_0_1"]),
}


def _compact(s: str) -> str:
    """Lower + strip hyphens/underscores/spaces — for hyphen variants (NGAP/NG-AP)."""
    return s.casefold().replace("-", "").replace("_", "").replace(" ", "").strip()


def _normalize(s: str) -> str:
    """Casefold + hyphens→spaces + collapse whitespace + sort tokens."""
    s = s.casefold()
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    return " ".join(sorted(tokens))


def _denied(a: str, b: str) -> bool:
    if frozenset([a.lower(), b.lower()]) in _DENYLIST_PAIRS:
        return True
    if frozenset(_normalize(a).split()) in _DENYLIST_NORMALIZE and frozenset(
        _normalize(b).split()
    ) in _DENYLIST_NORMALIZE:
        return True
    return False


@dataclass
class MergeDecision:
    decision: str  # "MERGE" | "ADD"
    target: str | None
    reason: str
    neighbours: list[tuple[str, float]]
    used_llm: bool = False


class MergeJudge:
    """LLM-backed judge with deterministic fallback.

    When llm_client is None or disabled, MERGE iff normalized canonicals equal
    one of the neighbours and the pair is not denylisted.
    """

    def __init__(self, llm_client=None, model_name: str = "default") -> None:
        self.llm_client = llm_client
        self.model_name = model_name
        self._llm_available = False
        if llm_client is not None:
            try:
                cfg = getattr(llm_client, "config", None)
                if cfg is not None:
                    self._llm_available = bool(getattr(cfg, "enabled", False))
                else:
                    self._llm_available = bool(getattr(llm_client, "enabled", False))
            except Exception:
                self._llm_available = False

    def judge(
        self,
        new_canonical: str,
        new_type: str,
        neighbours: list[dict],
    ) -> dict:
        """Return {"decision": "MERGE"|"ADD", "target": id|None, "reason": str}."""
        if not neighbours:
            return {"decision": "ADD", "target": None, "reason": "no neighbours"}

        norm_new = _normalize(new_canonical)
        compact_new = _compact(new_canonical)
        lid_new = new_canonical.lower().replace(" ", "_").replace("-", "_")

        if not self._llm_available or LLMClient is None:
            for nb in neighbours:
                can = nb["canonical"]
                if _denied(new_canonical, can):
                    continue
                # Hybrid exact: normalized, compact (NGAP/NG-AP, E-UTRAN/EUTRAN),
                # or id-folded lower — all catch hyphen/space/case variants
                # without false merges on DCI/timers (denylist-gated).
                if _normalize(can) == norm_new:
                    return {
                        "decision": "MERGE",
                        "target": nb["id"],
                        "reason": f"normalized match: {can!r}",
                    }
                if _compact(can) == compact_new:
                    return {
                        "decision": "MERGE",
                        "target": nb["id"],
                        "reason": f"compact match: {can!r}",
                    }
                if can.lower().replace(" ", "_").replace("-", "_") == lid_new:
                    return {
                        "decision": "MERGE",
                        "target": nb["id"],
                        "reason": f"id match: {can!r}",
                    }
            return {"decision": "ADD", "target": None, "reason": "no normalized/compact match"}

        nb_lines = "\n".join(
            f'- id={nb["id"]!r} canonical={nb["canonical"]!r} type={nb["type"]!r} cosine={nb["cosine"]:.3f}'
            for nb in neighbours
        )
        prompt = (
            "You are a 3GPP ontology merge judge. Decide if a newly extracted term "
            "is the SAME concept as one of the existing neighbours (MERGE) or a "
            "distinct concept (ADD). Be conservative: timers, DCI formats, and "
            "identifiers that differ by a single character (e.g. T3444 vs T3445, "
            "C1-174182 vs C1-174183, ACTIVE vs INACTIVE, DCI-1-0 vs DCI-0-1) are "
            "DISTINCT. Hyphen/space/case variants (NGAP vs NG-AP, E-UTRAN vs EUTRAN) "
            "ARE the same.\n\n"
            f"New term: canonical={new_canonical!r} type={new_type!r}\n"
            f"Neighbours:\n{nb_lines}\n\n"
            'Reply with JSON only: {"decision": "MERGE"|"ADD", "target": "<id or null>", "reason": "..."}'
        )
        try:
            client = self.llm_client
            text = None
            if hasattr(client, "complete"):
                try:
                    text = client.complete(prompt)
                except TypeError:
                    text = client.complete(prompt, model=self.model_name)  # type: ignore
            elif hasattr(client, "chat"):
                try:
                    text = client.chat(prompt)
                except TypeError:
                    text = client.chat(prompt, model=self.model_name)  # type: ignore
            elif hasattr(client, "_call"):
                text = client._call(prompt)
            elif callable(client):
                text = client(prompt)
            else:
                raise RuntimeError("LLM client has no known call method")

            m = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
            dec = (data.get("decision") or "ADD").upper()
            if dec not in ("MERGE", "ADD"):
                dec = "ADD"
            tgt = data.get("target")
            if dec == "MERGE" and tgt not in {nb["id"] for nb in neighbours}:
                dec, tgt = "ADD", None
            return {"decision": dec, "target": tgt, "reason": data.get("reason", "")}
        except Exception as e:
            comp_new = _compact(new_canonical)
            lid_new = new_canonical.lower().replace(" ", "_").replace("-", "_")
            for nb in neighbours:
                can = nb["canonical"]
                if _denied(new_canonical, can):
                    continue
                if _normalize(can) == norm_new or _compact(can) == comp_new or can.lower().replace(" ", "_").replace("-", "_") == lid_new:
                    return {
                        "decision": "MERGE",
                        "target": nb["id"],
                        "reason": f"LLM error fallback, hybrid match: {e}",
                    }
            return {"decision": "ADD", "target": None, "reason": f"LLM error fallback: {e}"}


def decide(
    new_canonical: str,
    new_type: str,
    index: EmbeddingIndex,
    judge: MergeJudge,
    top_k: int = 5,
    threshold: float = 0.3,
    id_to_canonical: dict[str, str] | None = None,
    id_to_type: dict[str, str] | None = None,
) -> MergeDecision:
    """Full pipeline: embed+search → judge → MergeDecision.

    Hybrid retrieval: dict exact (normalized + compact + id-folded, cosine 1.0)
    UNION embedding top-k. This matches step 2 of the per-chunk loop.
    """
    neighbours_scored = index.search_text(new_canonical, top_k=top_k, threshold=threshold)
    neighbours: list[dict] = []
    for cid, cos in neighbours_scored:
        neighbours.append(
            {
                "id": cid,
                "canonical": (id_to_canonical or {}).get(cid, cid),
                "type": (id_to_type or {}).get(cid, "concept"),
                "cosine": cos,
            }
        )
    # Hybrid dict exact: inject normalized/compact/id matches with cosine 1.0
    # so the judge (deterministic or LLM) sees hyphen/space/case variants
    # even when hash embedding cosine is < threshold — but respect the
    # threshold gate (if threshold > 1.0 nothing passes).
    if id_to_canonical and 1.0 >= threshold:
        norm_new = _normalize(new_canonical)
        compact_new = _compact(new_canonical)
        lid_new = new_canonical.lower().replace(" ", "_").replace("-", "_")
        seen_ids = {nb["id"] for nb in neighbours}
        for cid, can in id_to_canonical.items():
            if cid in seen_ids:
                continue
            if _denied(new_canonical, can):
                continue
            if _normalize(can) == norm_new or _compact(can) == compact_new or can.lower().replace(" ", "_").replace("-", "_") == lid_new:
                neighbours.insert(0, {"id": cid, "canonical": can, "type": (id_to_type or {}).get(cid, "concept"), "cosine": 1.0})
                neighbours_scored = [(cid, 1.0)] + neighbours_scored
                seen_ids.add(cid)
    res = judge.judge(new_canonical, new_type, neighbours)
    return MergeDecision(
        decision=res["decision"],
        target=res.get("target"),
        reason=res.get("reason", ""),
        neighbours=neighbours_scored,
        used_llm=judge._llm_available,
    )
