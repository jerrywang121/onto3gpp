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
└── config.yaml         # domain config
```

## config.yaml

```yaml
# Domain identifier
domain: <domain-name>

# Concept types allowed in this domain
concept_types:
  - concept
  - procedure
  - entity
  - interface

# Relation types allowed in this domain
relation_types:
  - is_a
  - part_of
  - uses
  - related_to

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
```

## Prompts

Each prompt template is a text file with `{placeholders}` that the pipeline
fills in. See the `3gpp/` domain for concrete examples.
