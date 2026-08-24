"""AI-as-judge improvement loop: log analysis → proposals → review.

This is the *optional* AI-driven improvement path. The runtime is always
deterministic; this module only runs when an LLM client is configured and
enabled in the domain pack.

Flow:
1. **Analyze** search logs (queries + clicks) to find gaps.
2. **Propose** improvements (new terms, aliases, relations) via an LLM using
   the ``propose_improvements.txt`` prompt template.
3. **Review** proposals against the ontology (referential integrity) and
   apply only those that are valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from onto3gpp.llm import LLMClient
from onto3gpp.ontology.schema import Ontology, Relation


@dataclass
class ImprovementProposal:
    """A single proposed ontology improvement from the LLM."""

    type: str  # "term" | "alias" | "relation"
    concept: str
    surface: str | None = None
    relation: dict | None = None
    confidence: float = 0.5
    rationale: str = ""


def _load_prompt(name: str, domain_dir: Path) -> str:
    """Load a prompt template from a domain pack's prompts/ directory."""
    path = domain_dir / "prompts" / name
    return path.read_text(encoding="utf-8")


def propose_improvements(
    llm: LLMClient,
    search_logs: list[dict],
    ontology_summary: str,
    domain_dir: Path | None = None,
) -> list[ImprovementProposal]:
    """Ask the LLM to propose ontology improvements from search logs."""
    if domain_dir is not None:
        template = _load_prompt("propose_improvements.txt", domain_dir)
    else:
        template = (
            "You are a knowledge engineer proposing improvements to the {domain} "
            "ontology based on search logs.\n\nSearch logs:\n{search_logs}\n\n"
            "Current ontology (summary):\n{ontology_summary}\n\n"
            "Return JSON with a 'proposals' list."
        )
    prompt = template.format(
        domain="3gpp",
        search_logs=json.dumps(search_logs, indent=2),
        ontology_summary=ontology_summary,
    )
    data = llm.complete_json(prompt)
    proposals: list[ImprovementProposal] = []
    for p in data.get("proposals", []):
        proposals.append(
            ImprovementProposal(
                type=p.get("type", "term"),
                concept=p.get("concept", ""),
                surface=p.get("surface"),
                relation=p.get("relation"),
                confidence=float(p.get("confidence", 0.5)),
                rationale=p.get("rationale", ""),
            )
        )
    return proposals


def apply_proposals(onto: Ontology, proposals: list[ImprovementProposal]) -> int:
    """Apply valid proposals to the ontology, returning the count applied.

    Review rules:
    - **term/alias**: add the surface form as an alias to the concept (if the
      concept exists and the alias is not already present).
    - **relation**: add the relation only if both endpoints are concepts.
    """
    applied = 0
    concept_by_id = {c.id: c for c in onto.concepts}

    for p in proposals:
        if p.type in ("term", "alias"):
            concept = concept_by_id.get(p.concept)
            if concept is None or not p.surface:
                continue
            if p.surface not in concept.aliases:
                concept.aliases.append(p.surface)
                applied += 1
        elif p.type == "relation" and p.relation:
            rel = p.relation
            if rel.get("source") in concept_by_id and rel.get("target") in concept_by_id:
                onto.relations.append(
                    Relation(
                        source=rel["source"],
                        rel=rel.get("rel", "related_to"),
                        target=rel["target"],
                        weight=float(rel.get("weight", 0.7)),
                        confidence=p.confidence,
                        provenance={"rationale": p.rationale},
                    )
                )
                applied += 1
    return applied
