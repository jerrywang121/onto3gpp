"""ABox merge / conflict resolution (Stage 9).

Deterministic similarity first: merge new concepts/relations into an existing
ABox, deduplicating by canonical (case-insensitive) and keeping the higher
confidence relation. Type conflicts are recorded and resolved first-wins.
An AI judge can be added later for ambiguous cases (ADR-0011).

Embedding+judge path: `merge_abox_with_judge` uses embedding retrieval +
LLM judge (optional, deterministic fallback) to recover hyphen/case/order
variants that plain casefold misses (e.g. NGAP/NG-AP). See ADR-0014.
"""

from __future__ import annotations

from dataclasses import dataclass

from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation


@dataclass
class MergeResult:
    """Outcome of merging an incoming ABox into an existing one."""

    abox: ABox
    added_concepts: int = 0
    merged_concepts: int = 0
    added_relations: int = 0
    duplicate_relations: int = 0
    conflicts: int = 0


def _canonical_key(canonical: str) -> str:
    return canonical.strip().lower()


def merge_abox(existing: ABox, incoming: ABox) -> MergeResult:
    """Merge ``incoming`` into ``existing``, deduplicating and resolving
    conflicts. Returns a new ABox (the input ABoxes are not mutated)."""
    concepts: dict[str, ABoxConcept] = {}
    for c in existing.concepts:
        concepts[_canonical_key(c.canonical)] = c

    relations: dict[tuple[str, str, str], ABoxRelation] = {}
    for r in existing.relations:
        relations[(r.source, r.rel, r.target)] = r

    added_concepts = 0
    merged_concepts = 0
    added_relations = 0
    duplicate_relations = 0
    conflicts = 0

    for c in incoming.concepts:
        key = _canonical_key(c.canonical)
        if key in concepts:
            merged_concepts += 1
            existing_c = concepts[key]
            if existing_c.type != c.type:
                conflicts += 1
            # first-wins: keep the existing concept, but merge aliases
            for alias in c.aliases:
                if alias not in existing_c.aliases:
                    existing_c.aliases.append(alias)
        else:
            concepts[key] = c
            added_concepts += 1

    for r in incoming.relations:
        key = (r.source, r.rel, r.target)
        if key in relations:
            duplicate_relations += 1
            if r.confidence > relations[key].confidence:
                relations[key] = r
        else:
            relations[key] = r
            added_relations += 1

    return MergeResult(
        abox=ABox(concepts=list(concepts.values()), relations=list(relations.values())),
        added_concepts=added_concepts,
        merged_concepts=merged_concepts,
        added_relations=added_relations,
        duplicate_relations=duplicate_relations,
        conflicts=conflicts,
    )


def merge_abox_with_judge(
    existing: ABox,
    incoming: ABox,
    *,
    index=None,
    judge=None,
    threshold: float = 0.25,
    top_k: int = 5,
) -> MergeResult:
    """Embedding-guided merge: embed→top-k→judge per incoming concept.

    `index` is an EmbeddingIndex over existing concepts (id→canonical);
    `judge` is a MergeJudge (LLM optional, deterministic fallback). When
    either is None, falls back to `merge_abox` (case-insensitive exact).
    """
    if index is None or judge is None:
        return merge_abox(existing, incoming)

    # Build lookup for judge display
    id_to_canonical = {c.id: c.canonical for c in existing.concepts}
    id_to_type = {c.id: c.type for c in existing.concepts}

    # id→concept for direct mutation + canonical-key dedupe as fallback
    by_id: dict[str, ABoxConcept] = {c.id: c for c in existing.concepts}
    by_key: dict[str, ABoxConcept] = {_canonical_key(c.canonical): c for c in existing.concepts}

    relations: dict[tuple[str, str, str], ABoxRelation] = {}
    for r in existing.relations:
        relations[(r.source, r.rel, r.target)] = r

    added_concepts = 0
    merged_concepts = 0
    conflicts = 0
    added_relations = 0
    duplicate_relations = 0

    # Local import to avoid circular deps
    from onto3gpp.ingest.merge_judge import decide as _decide

    for c in incoming.concepts:
        key = _canonical_key(c.canonical)
        # Fast path: exact case-insensitive key — deterministic merge without LLM/embedding
        if key in by_key:
            merged_concepts += 1
            existing_c = by_key[key]
            if existing_c.type != c.type:
                conflicts += 1
            for alias in c.aliases:
                if alias not in existing_c.aliases:
                    existing_c.aliases.append(alias)
            continue

        # Embedding → judge
        dec = _decide(
            c.canonical,
            c.type,
            index,
            judge,
            top_k=top_k,
            threshold=threshold,
            id_to_canonical=id_to_canonical,
            id_to_type=id_to_type,
        )
        if dec.decision == "MERGE" and dec.target and dec.target in by_id:
            merged_concepts += 1
            target_c = by_id[dec.target]
            if target_c.type != c.type:
                conflicts += 1
            # merge incoming canonical as alias of target
            if c.canonical not in target_c.aliases and c.canonical != target_c.canonical:
                target_c.aliases.append(c.canonical)
            for alias in c.aliases:
                if alias not in target_c.aliases:
                    target_c.aliases.append(alias)
        else:
            # ADD
            by_id[c.id] = c
            by_key[key] = c
            id_to_canonical[c.id] = c.canonical
            id_to_type[c.id] = c.type
            # keep index in sync for subsequent incoming concepts in same batch
            try:
                index.add(c.id, c.canonical)
            except Exception:
                pass
            added_concepts += 1

    for r in incoming.relations:
        key_r = (r.source, r.rel, r.target)
        if key_r in relations:
            duplicate_relations += 1
            if r.confidence > relations[key_r].confidence:
                relations[key_r] = r
        else:
            relations[key_r] = r
            added_relations += 1

    return MergeResult(
        abox=ABox(concepts=list(by_id.values()), relations=list(relations.values())),
        added_concepts=added_concepts,
        merged_concepts=merged_concepts,
        added_relations=added_relations,
        duplicate_relations=duplicate_relations,
        conflicts=conflicts,
    )
