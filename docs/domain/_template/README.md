# Domain Pack Template

Copy this directory to create a new domain, e.g. `docs/domain/<your-domain>/`.
Fill in the prompts and config. No code changes are needed to adapt the
pipeline to a new domain.

## Structure

```
docs/domain/<domain>/
├── prompts/            # AI prompt templates (parameterized)
│   ├── extract_terms.txt
│   ├── extract_relations.txt
│   ├── judge_candidates.txt
│   └── propose_improvements.txt
├── config.yaml         # domain config (intents, patterns, metadata, llm)
└── tbox.yaml           # top-level ontology (TBox): concept/relation types + constraints
```

## config.yaml

```yaml
# Domain identifier
domain: <domain-name>

# Intent types for query classification
intents:
  - DEFINITION
  - PROCEDURE
  - CONFIGURATION
  - FAILURE

# Deterministic query-intent classification patterns (Stage 3). Each intent
# maps to a list of regexes; a query is classified by counting regex matches
# (ties broken by the latest match position). See src/onto3gpp/runtime/intent.py.
intent_patterns:
  DEFINITION:
    - "\\bwhat is\\b"
    - "\\bdefine\\b"
  PROCEDURE:
    - "\\bhow (does|is|are|do)\\b"
    - "\\bprocedure\\b"
  CONFIGURATION:
    - "\\bconfigure\\b"
    - "\\bsetup\\b"
  FAILURE:
    - "\\b(fail|failure|error|break)\\b"

# Document metadata fields (spec number, release, clause, etc.)
document_metadata:
  - spec_number
  - release
  - clause
  - title

# Judge confidence threshold (0-1)
judge_threshold: 0.8

# External AI model hooks (optional). The pipeline is deterministic and
# AI-free by default; enable an LLM only to use AI-as-judge / AI extraction /
# the improvement loop / AI-assisted ingestion. See ADR-0012.
#
# Multi-model routing: each pipeline task resolves to a named model. A task
# with no entry falls back to `default`. A flat `model:`/`provider:`/
# `api_base:`/`api_key:` block (the old single-model form) is treated as
# `default` for backward compatibility.
llm:
  enabled: false
  default:
    provider: openai
    model: gpt-4o-mini
    api_base: null        # e.g. http://localhost:8000/v1 for a local vLLM
    api_key: null         # set via env (OPENAI_API_KEY) or here
    temperature: 0.0
    max_tokens: 1024
  models:
    extract:       {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
    judge:         {provider: openai, model: gpt-4o,      temperature: 0.0, max_tokens: 1024}
    align:         {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
    merge:         {provider: ollama, model: llama3,     api_base: http://localhost:11434, temperature: 0.0, max_tokens: 1024}
    domain_detect: {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 256}
    improve:       {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
```

## tbox.yaml

The top-level ontology (TBox) lives in its own file, `tbox.yaml`, separate
from `config.yaml`. It is the durable source of truth: the `ingest` command
writes the evolved TBox back to this file.

```yaml
# Top-level ontology (TBox) — the blueprint / constraint for the ABox.
# concept_types are the TBox nodes; relation_type_constraints are the TBox
# edges (which relation types may connect which concept types). Curated here
# by default; AI may evolve it only when evidence demands (ADR-0010, ADR-0011).
# The `ingest` command writes the evolved TBox back to this file.
concept_types:
  - concept
  - procedure
  - entity
  - interface

relation_types:
  - is_a
  - part_of
  - uses
  - related_to

# TBox edges: (source_type, rel, target_type). A relation in the ABox is valid
# only if its (source.type, rel, target.type) appears here. This is the
# top-level ontology graph (TBox) that constrains the low-level knowledge
# graph (ABox). See ADR-0010.
relation_type_constraints:
  - {source_type: concept, rel: is_a, target_type: concept}
  - {source_type: procedure, rel: uses, target_type: entity}
  - {source_type: entity, rel: part_of, target_type: entity}
```

## Prompts

Each prompt template is a text file with `{placeholders}` that the pipeline
fills in. See the `3gpp/` domain for concrete examples.
