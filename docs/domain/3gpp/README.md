# Domain: 3GPP

The first concrete domain pack. This drives the pipeline for 3GPP
specifications. To adapt to another domain, copy `docs/domain/_template/`.

## config.yaml

```yaml
domain: 3gpp

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
```

## Prompts

See the `prompts/` directory for the AI prompt templates.
