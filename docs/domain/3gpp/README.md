# Domain: 3GPP

The first concrete domain pack. This drives the pipeline for 3GPP
specifications. To adapt to another domain, copy `docs/domain/_template/`.

## config.yaml

```yaml
domain: 3gpp

# Top-level ontology (TBox) — the blueprint / constraint for the ABox.
concept_types:
  - network_function
  - procedure
  - information_element
  - interface
  - protocol
  - qos
  - architecture
  - security

relation_types:
  - is_a
  - part_of
  - uses
  - selects
  - participates_in
  - specified_in
  - related_to

# TBox edges: (source_type, rel, target_type). A relation in the ABox is valid
# only if its (source.type, rel, target.type) appears here.
relation_type_constraints:
  - {source_type: network_function, rel: uses, target_type: network_function}
  - {source_type: network_function, rel: selects, target_type: network_function}
  - {source_type: network_function, rel: participates_in, target_type: procedure}
  - {source_type: network_function, rel: uses, target_type: procedure}
  - {source_type: procedure, rel: uses, target_type: network_function}
  - {source_type: procedure, rel: uses, target_type: information_element}
  - {source_type: procedure, rel: part_of, target_type: procedure}
  - {source_type: information_element, rel: part_of, target_type: information_element}
  - {source_type: interface, rel: connects, target_type: network_function}
  - {source_type: protocol, rel: uses, target_type: interface}
  - {source_type: qos, rel: part_of, target_type: procedure}
  - {source_type: architecture, rel: part_of, target_type: architecture}
  - {source_type: security, rel: uses, target_type: procedure}
  - {source_type: network_function, rel: is_a, target_type: network_function}
  - {source_type: procedure, rel: is_a, target_type: procedure}
  - {source_type: information_element, rel: is_a, target_type: information_element}
  - {source_type: network_function, rel: specified_in, target_type: architecture}
  - {source_type: procedure, rel: specified_in, target_type: architecture}
  - {source_type: network_function, rel: related_to, target_type: network_function}
  - {source_type: procedure, rel: related_to, target_type: procedure}

intents:
  - DEFINITION
  - PURPOSE
  - PROCEDURE
  - MESSAGE_FLOW
  - CONFIGURATION
  - PARAMETER
  - FAILURE
  - ERROR_HANDLING
  - SECURITY
  - COMPARISON
  - DEPENDENCY
  - ARCHITECTURE
  - REQUIREMENT

document_metadata:
  - spec_number
  - release
  - version
  - document_type
  - title

judge_threshold: 0.8

# Multi-model LLM routing (ADR-0012). Each pipeline task resolves to a named
# model; tasks with no entry fall back to `default`. `enabled: false` keeps the
# pipeline deterministic / AI-free.
llm:
  enabled: false
  default:
    provider: openai
    model: gpt-4o-mini
    api_base: null
    api_key: null
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

## Prompts

See the `prompts/` directory for the AI prompt templates.
