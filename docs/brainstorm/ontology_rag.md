## Question

i need to improve keywords search in 3gpp document. 
i am think use high level ontology to guid ai for both keywords extractin (or NER), and reasoning on query.
while the runtime keywords extraction / NER shall be AI free, i.e run local with small model on cpu, or simply dictionary lookup.

make a design / archecture / plan how may i do it



## Suggestion

Yes. I think this is a **very good architecture**, especially for 3GPP documents, because 3GPP terminology is highly structured and repetitive, while user queries are often vague, abbreviated, or expressed at the wrong level of abstraction.

The key idea I would recommend is:

> **Use AI offline to build and maintain a 3GPP ontology + terminology knowledge base. Use deterministic/local methods at runtime to turn the user's query into ontology concepts and search terms.**

That gives you much of the benefit of AI reasoning without requiring an LLM during every search.

---

# 1. Overall architecture

I would structure the system into **four layers**:

```text
                         OFFLINE / DEVELOPMENT
 ┌───────────────────────────────────────────────────────────────┐
 │                    3GPP Knowledge Builder                    │
 │                                                               │
 │  3GPP specs ──► terminology extraction ──► ontology          │
 │                         │                    │                │
 │                         │                    ├─ concepts      │
 │                         │                    ├─ relations     │
 │                         │                    ├─ abbreviations │
 │                         │                    ├─ synonyms      │
 │                         │                    └─ hierarchy     │
 │                         │                                     │
 │                         └──────────────► search lexicon       │
 └───────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    Versioned Knowledge Pack
                              │
                              │
                         RUNTIME / CPU
                              ▼
 ┌───────────────────────────────────────────────────────────────┐
 │                         Query Engine                          │
 │                                                               │
 │ User query                                                   │
 │    │                                                          │
 │    ▼                                                          │
 │ Query normalization                                           │
 │    │                                                          │
 │    ▼                                                          │
 │ Deterministic NER / terminology matching                      │
 │    │                                                          │
 │    ▼                                                          │
 │ Ontology mapping                                              │
 │    │                                                          │
 │    ▼                                                          │
 │ Query expansion / reasoning                                   │
 │    │                                                          │
 │    ▼                                                          │
 │ Search plan                                                   │
 │    │                                                          │
 │    ├── exact terms                                            │
 │    ├── synonyms                                                │
 │    ├── abbreviations                                           │
 │    ├── related concepts                                        │
 │    ├── document/section constraints                            │
 │    └── semantic relationships                                  │
 │                                                               │
 │    ▼                                                          │
 │ 3GPP Search Index                                              │
 │    │                                                          │
 │    ▼                                                          │
 │ Ranked results                                                 │
 └───────────────────────────────────────────────────────────────┘
```

The important architectural separation is:

**AI creates knowledge → runtime consumes knowledge.**

---

# 2. Don't make the ontology just a taxonomy

This is probably the most important design decision.

A simple ontology like:

```text
5G
 ├── RAN
 ├── Core
 ├── IMS
 └── Security
```

isn't sufficient for search.

You want a **knowledge graph / ontology with several types of relationships**.

For example:

```text
PDU Session
    │
    ├── belongs_to ───────► 5G Core
    │
    ├── uses ─────────────► SMF
    │
    ├── uses ─────────────► UPF
    │
    ├── has ──────────────► QoS Flow
    │
    ├── related_to ───────► DNN
    │
    ├── related_to ───────► S-NSSAI
    │
    ├── specified_in ─────► TS 23.501
    │
    └── abbreviated_as ───► PDU
                              Session
```

And separately:

```text
SMF
 │
 ├── Session Management Function
 ├── network function
 ├── 5GC
 ├── TS 23.501
 ├── TS 23.502
 └── N11
```

This lets you reason about a query.

---

# 3. Represent concepts separately from terms

I would strongly recommend **not** making the dictionary itself the ontology.

Instead:

```text
Concept
   │
   ├── canonical name
   ├── aliases
   ├── abbreviations
   ├── definitions
   ├── parent concepts
   ├── child concepts
   ├── related concepts
   ├── procedures
   ├── messages
   ├── information elements
   ├── interfaces
   ├── specifications
   └── search terms
```

For example:

```json
{
  "concept_id": "concept.pdu_session",
  "canonical_name": "PDU Session",

  "aliases": [
    "PDU session",
    "PDU sessions"
  ],

  "abbreviations": [
    "PDU"
  ],

  "parents": [
    "concept.session_management",
    "concept.5gc"
  ],

  "related": [
    "concept.smf",
    "concept.upf",
    "concept.qos_flow",
    "concept.dnn",
    "concept.s_nssai"
  ],

  "specifications": [
    "23.501",
    "23.502"
  ]
}
```

But importantly:

> **"PDU" should not automatically equal "PDU Session".**

You need context and confidence.

---

# 4. Build a 3GPP ontology hierarchy

I would initially create something approximately like this:

```text
3GPP
│
├── Generation
│   ├── 2G
│   ├── 3G
│   ├── 4G
│   ├── 5G
│   └── 6G
│
├── Network
│   ├── RAN
│   │   ├── NR
│   │   ├── LTE
│   │   ├── gNB
│   │   ├── CU
│   │   ├── DU
│   │   └── ...
│   │
│   ├── Core
│   │   ├── EPC
│   │   └── 5GC
│   │       ├── AMF
│   │       ├── SMF
│   │       ├── UPF
│   │       ├── PCF
│   │       ├── UDM
│   │       └── AUSF
│   │
│   ├── IMS
│   └── Network Management
│
├── Procedure
│   ├── Registration
│   ├── PDU Session Establishment
│   ├── Handover
│   ├── Paging
│   ├── Authentication
│   └── ...
│
├── Protocol
│   ├── NAS
│   ├── RRC
│   ├── NGAP
│   ├── PFCP
│   ├── HTTP/2
│   └── ...
│
├── Information
│   ├── Information Element
│   ├── Cause
│   ├── Timer
│   ├── Parameter
│   └── Message
│
├── QoS
│   ├── QoS Flow
│   ├── 5QI
│   ├── QFI
│   ├── ARP
│   └── ...
│
├── Architecture
│   ├── Interface
│   ├── Reference Point
│   ├── Network Function
│   └── Deployment
│
└── Security
    ├── Authentication
    ├── Authorization
    ├── Integrity
    └── Encryption
```

But don't try to build the perfect ontology at the beginning.

Start with perhaps **500–2,000 important concepts** and expand.

---

# 5. Add "search relationships"

This is where your idea becomes much more powerful than ordinary NER.

Suppose the user searches:

> "How does AMF handle registration when UE moves to another cell?"

A normal keyword extractor might produce:

```text
AMF
registration
UE
cell
move
```

Your ontology can turn that into:

```text
AMF
    │
    └── network function

Registration
    │
    └── procedure

UE
    │
    └── user equipment

Move
    │
    ├── mobility
    ├── handover
    ├── registration update
    └── tracking area update
```

Then the search engine generates something like:

```text
EXACT:
    "AMF"
    "Registration"

ALIAS:
    "Access and Mobility Management Function"
    "registration procedure"

RELATED:
    "Registration Request"
    "Registration Accept"
    "Registration Update"
    "mobility registration update"

PROCEDURE:
    "5GS registration procedure"

POSSIBLE:
    "handover"
    "mobility"
```

But **"handover" shouldn't have the same weight as "registration."**

That leads naturally to a weighted query model.

---

# 6. Give every expansion a relationship weight

For example:

```text
Exact term                 1.00
Canonical alias             0.95
Abbreviation                0.90
Morphological variant       0.85
Parent concept              0.60
Child concept               0.70
Strongly related            0.50
Procedure relationship      0.65
Interface relationship      0.55
Weak semantic relationship  0.25
```

Then:

```text
User:
    "PDU session establishment"

Extracted concepts:
    PDU_SESSION
    SESSION_ESTABLISHMENT
```

Expansion:

```text
PDU Session                    1.00
PDU Session Establishment     1.00
SMF                            0.55
UPF                            0.55
AMF                            0.40
N11                            0.40
PDU Session Establishment Req 0.85
PDU Session Establishment Acc 0.85
```

Now the search engine can use these weights.

---

# 7. Separate NER from query reasoning

I would make this an explicit architectural boundary.

## Stage A — NER / terminology extraction

This should be extremely cheap:

```text
Input:
"During PDU session establishment, how does SMF select UPF?"

                 │
                 ▼

        deterministic matcher

                 │
                 ▼

[
  {
    span: "PDU session establishment",
    concept: "PDU_SESSION_ESTABLISHMENT",
    confidence: 1.0
  },
  {
    span: "SMF",
    concept: "SMF",
    confidence: 1.0
  },
  {
    span: "UPF",
    concept: "UPF",
    confidence: 1.0
  }
]
```

No LLM required.

---

# 8. Runtime NER can be much better than a simple dictionary

I would use a **layered matcher**.

### Layer 1 — exact dictionary

```text
AMF
SMF
UPF
PDU Session
QoS Flow
Registration Request
```

### Layer 2 — case-insensitive matching

```text
amf
AMF
Amf
```

### Layer 3 — normalization

Handle:

```text
PDU-session
PDU session
pdu_session
PDU Session
PDU sessions
```

### Layer 4 — abbreviation expansion

```text
Access and Mobility Management Function
                 ↓
                AMF
```

### Layer 5 — phrase matching

This is important.

Instead of:

```text
PDU → concept A
session → concept B
establishment → concept C
```

recognize:

```text
"PDU Session Establishment"
        ↓
one concept
```

Use a trie/Aho-Corasick/FST-style matcher.

For a large 3GPP vocabulary, **Aho-Corasick or a trie** is particularly attractive.

Runtime can therefore be:

```text
O(text length + matches)
```

and easily run on CPU.

---

# 9. Handle ambiguity explicitly

This is another major benefit of the ontology.

Consider:

> "security context"

Could mean several things.

Instead of:

```text
security context → one concept
```

store:

```text
SECURITY_CONTEXT
    │
    ├── NAS security context
    ├── AS security context
    ├── 5G security context
    └── EPS security context
```

Then the NER output can be:

```json
{
  "surface": "security context",
  "candidate_concepts": [
    ["security_context", 0.8],
    ["nas_security_context", 0.6],
    ["as_security_context", 0.5]
  ]
}
```

Context can resolve this later.

---

# 10. Query reasoning should be deterministic too

This is where I would slightly modify your original proposal.

You said:

> runtime keywords extraction / NER shall be AI free

I agree.

But I would also try to make **most query reasoning AI-free**.

For example, define explicit reasoning rules:

```text
IF concept = AMF
THEN add:
    Access and Mobility Management Function

IF concept = PDU_SESSION_ESTABLISHMENT
THEN add:
    PDU Session Establishment Request
    PDU Session Establishment Accept
    SMF
    AMF
    UPF

IF concept = HANDOVER
THEN add:
    source cell
    target cell
    source gNB
    target gNB
    mobility
```

This becomes a small **3GPP search inference engine**.

---

# 11. Think of the query processor as a compiler

I think this is the cleanest mental model.

User query:

```text
"How does SMF select UPF during PDU session establishment?"
```

gets compiled into an intermediate representation:

```text
Query IR
─────────────────────────────────────

Intent:
    PROCEDURE / BEHAVIOR

Concepts:
    SMF
    UPF
    PDU_SESSION_ESTABLISHMENT

Relationships:
    SMF ──selects──► UPF

Context:
    Session Management

Likely specs:
    23.501
    23.502

Search terms:
    "SMF"
    "UPF"
    "PDU Session Establishment"
    "UPF selection"
    "User Plane Function selection"

Required proximity:
    SMF ↔ UPF
    PDU Session Establishment

Ranking:
    exact concepts > related concepts
```

Then the actual search engine doesn't need to understand the natural-language question.

It receives a structured search plan.

---

# 12. Your ontology should include "intent"

This is a useful extension.

Queries aren't just about entities.

For example:

> "What is the purpose of the N2 interface?"

Entities:

```text
N2
```

Intent:

```text
DEFINITION / PURPOSE
```

Another:

> "What happens when PDU session establishment fails?"

Entities:

```text
PDU Session Establishment
```

Intent:

```text
FAILURE / ERROR HANDLING
```

Another:

> "Which message carries the QoS rules?"

Entities:

```text
QoS Rules
```

Intent:

```text
MESSAGE / INFORMATION ELEMENT
```

You can have a small finite set:

```text
DEFINITION
PURPOSE
PROCEDURE
MESSAGE_FLOW
CONFIGURATION
PARAMETER
FAILURE
ERROR_HANDLING
SECURITY
COMPARISON
DEPENDENCY
ARCHITECTURE
REQUIREMENT
```

Intent classification could also be deterministic initially, using lexical patterns.

---

# 13. Use 3GPP document structure as another ontology

This is **very important for 3GPP search**.

Don't treat a specification as just a giant bag of text.

Your index should know:

```text
TS 23.501
   │
   ├── clause 4
   │
   ├── clause 5
   │
   ├── clause 5.15
   │
   └── clause 5.15.6
```

and:

```text
document
   ↓
chapter
   ↓
clause
   ↓
subclause
   ↓
paragraph
   ↓
sentence
```

Each chunk should carry metadata:

```json
{
  "spec": "23.501",
  "release": "Rel-18",
  "clause": "5.15.6",
  "title": "Network Slice Selection",
  "text": "...",

  "concepts": [
    "S-NSSAI",
    "NSSF",
    "AMF",
    "network_slice"
  ]
}
```

This gives you **structural search**, which can be extremely valuable.

---

# 14. Add "specification knowledge"

The ontology can also know:

```text
Concept                Primary specification
------------------------------------------------
5GC                    23.501
5GS procedures         23.502
NAS                    24.501
RRC                     38.331
NGAP                    38.413
PDCP                    38.323
SDAP                    37.324
```

Then:

> "PDU session establishment procedure"

can automatically boost relevant documents.

For example:

```text
23.502       +1.0
23.501       +0.8
24.501       +0.6
38.xxx       +0.2
```

You can still return other documents, but ranking becomes much better.

---

# 15. Build the ontology offline using AI

This is where I would use an LLM aggressively.

Pipeline:

```text
3GPP documents
       │
       ▼
document parser
       │
       ▼
candidate terminology extraction
       │
       ▼
LLM
       │
       ├── identify concepts
       ├── identify aliases
       ├── identify abbreviations
       ├── identify relationships
       ├── identify procedures
       ├── identify interfaces
       └── identify definitions
       │
       ▼
ontology candidate database
       │
       ▼
validation
       │
       ▼
human review
       │
       ▼
versioned ontology
```

The LLM should **not** directly generate the production dictionary.

Instead:

```text
LLM
 ↓
candidate
 ↓
validation
 ↓
approved knowledge
 ↓
production
```

That prevents hallucinations from contaminating search.

---

# 16. Use the 3GPP specifications themselves as ground truth

For every ontology relationship, ideally maintain provenance:

```json
{
  "subject": "SMF",
  "relation": "selects",
  "object": "UPF",

  "source": {
    "spec": "23.501",
    "release": "Rel-18",
    "clause": "6.2.2"
  }
}
```

This is extremely valuable.

You can then answer:

> Why does the search engine associate SMF with UPF?

with:

```text
SMF ──selects──► UPF
Source: TS 23.501, clause 6.2.2
```

It also makes ontology maintenance much easier.

---

# 17. I would maintain three knowledge stores

You don't necessarily need three physical databases.

But logically, keep them separate.

### A. Terminology store

```text
surface form
    ↓
concept
```

Example:

```text
"Access and Mobility Management Function"
"AMF"
"amf"
        ↓
AMF
```

### B. Ontology / graph

```text
AMF ──is_a──► Network Function
AMF ──part_of──► 5GC
AMF ──uses──► N2
AMF ──participates_in──► Registration
```

### C. Document index

```text
document
clause
paragraph
text
concept IDs
terms
metadata
```

This separation makes the architecture much cleaner.

---

# 18. Search engine architecture

I'd use something like:

```text
                  Query
                    │
                    ▼
             Query Normalizer
                    │
                    ▼
              Terminology NER
                    │
                    ▼
              Concept Resolver
                    │
                    ▼
             Intent Detector
                    │
                    ▼
             Query Reasoner
                    │
                    ▼
             Query IR / Plan
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
     Lexical search       Semantic search
       BM25/etc.          optional vectors
          │                   │
          └─────────┬─────────┘
                    ▼
                 Fusion
                    │
                    ▼
                 Rerank
                    │
                    ▼
               3GPP results
```

The semantic/vector component is **optional**.

I'd actually start without it.

---

# 19. Don't throw away conventional search

A common mistake would be:

> "Let's use ontology instead of BM25/vector search."

I wouldn't.

Use the ontology to **improve the query and ranking**, not replace the search engine.

For example:

```text
                   Query
                     │
             ontology expansion
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
       exact       aliases     related
         │           │           │
         └───────────┼───────────┘
                     ▼
                   BM25
                     │
                     ▼
                   Rank
```

This gives you predictable behavior.

---

# 20. Add phrase and proximity scoring

For technical specifications this can be extremely effective.

Suppose:

```text
Query:
PDU session establishment SMF UPF
```

Document A:

```text
PDU Session Establishment procedure
...
SMF selects a UPF...
```

Document B:

```text
The UE establishes a PDU session...
...
The UPF...
```

Document A should score much higher.

So scoring might be:

```text
score =
    0.30 exact_term
  + 0.25 phrase_match
  + 0.15 concept_match
  + 0.10 ontology_relationship
  + 0.10 proximity
  + 0.05 section relevance
  + 0.05 specification relevance
```

You can tune these weights from actual search logs.

---

# 21. Add a "query graph"

This is something I think could become a very strong differentiator.

For:

> "How does SMF select UPF during PDU session establishment?"

build:

```text
              PDU Session
                   │
                   │ establishment
                   ▼
                  SMF
                   │
                   │ selects
                   ▼
                  UPF
```

Now search for documents containing not merely:

```text
SMF AND UPF
```

but preferably:

```text
SMF
    near
UPF
    in context of
PDU Session Establishment
```

This is much closer to what the user actually means.

---

# 22. Use relationship-aware search

Your index can even store relationship evidence.

For example:

```text
Chunk #12345

Concepts:
    SMF
    UPF
    PDU_SESSION_ESTABLISHMENT

Relations:
    SMF --selects--> UPF

Spec:
    23.502

Clause:
    4.3.2
```

That chunk gets a very high score for:

> "How does SMF select UPF?"

even if the exact phrase isn't present.

---

# 23. Small local model: where I would use it

You mentioned a small model on CPU.

I'd keep it as an **optional fallback**, not the core architecture.

Possible runtime stack:

```text
Level 0
Dictionary / trie
       ↓
Level 1
Rules / regex / normalization
       ↓
Level 2
Small local NER model
       ↓
Level 3
Ontology resolver
       ↓
Level 4
Deterministic reasoning
```

For example, if:

```text
"AMF"
```

appears, don't waste model inference.

If:

```text
"access and mobility function"
```

appears, dictionary matching handles it.

Only ambiguous natural-language phrases need the small model.

That makes CPU cost very low.

---

# 24. A particularly useful trick: generate the dictionary from the ontology

Don't manually maintain:

```text
AMF
AMF function
Access Mobility Function
Access and Mobility Management Function
...
```

Instead, have the ontology compiler generate it:

```text
Ontology
   │
   ▼
Terminology compiler
   │
   ├── exact dictionary
   ├── aliases
   ├── abbreviations
   ├── plural forms
   ├── hyphen variants
   ├── normalized forms
   ├── phrase trie
   └── concept IDs
```

Then runtime gets a compact binary package:

```text
3gpp-ontology-rel18.bin
3gpp-terms-rel18.bin
3gpp-search-rules-rel18.bin
```

That is very deployable.

---

# 25. Version the ontology by 3GPP Release

This is essential.

You don't want:

```text
AMF
```

to mean exactly the same thing across every release.

Have:

```text
Ontology
 ├── Rel-15
 ├── Rel-16
 ├── Rel-17
 ├── Rel-18
 ├── Rel-19
 └── ...
```

with:

```text
Concept
   │
   ├── introduced_in
   ├── modified_in
   ├── deprecated_in
   └── valid_until
```

Then the user can search:

> "PDU session establishment in Rel-17"

and the terminology and ranking are release-aware.

---

# 26. I would also model "document type"

3GPP document numbers are highly informative.

For example, distinguish:

```text
Architecture
Procedure
Protocol
Requirements
Test specification
Stage 1
Stage 2
Stage 3
```

Then:

> "What is the procedure for X?"

should favor procedure-oriented specifications.

While:

> "What is the protocol message?"

should favor Stage 3 / protocol specifications.

This is another deterministic signal.

---

# 27. Proposed data model

A practical first version could look like:

```text
Concept
-------
id
canonical_name
type
description

Term
----
surface_form
normalized_form
concept_id
term_type
language
priority

Relation
--------
source_concept
relation_type
target_concept
weight
source_spec
source_clause

Document
--------
spec_number
release
version
document_type
title

Section
-------
document_id
clause
title
parent_clause
text

SectionConcept
--------------
section_id
concept_id
confidence

SearchRule
----------
trigger_concept
rule_type
target_concept
weight
conditions
```

This is enough to build a first prototype.

---

# 28. Example end-to-end

User:

> **"How does the network decide which UPF to use when establishing a PDU session?"**

### Step 1 — deterministic NER

```text
network              → NETWORK
UPF                   → UPF
establishing          → ESTABLISHMENT
PDU session           → PDU_SESSION
```

### Step 2 — ontology resolution

```text
PDU_SESSION
     │
     └── related procedure
             ↓
    PDU_SESSION_ESTABLISHMENT

UPF
     │
     └── network function
```

### Step 3 — intent

```text
HOW / PROCEDURE
```

### Step 4 — ontology reasoning

```text
PDU_SESSION_ESTABLISHMENT
        │
        ├── SMF
        ├── UPF selection
        ├── PDU Session Anchor
        ├── N4
        └── user plane
```

### Step 5 — search query

```text
PRIMARY:
    PDU Session Establishment
    UPF selection
    SMF
    UPF

SECONDARY:
    PDU Session Anchor
    N4
    User Plane Function

FILTER:
    procedure-oriented sections

BOOST:
    TS 23.502
    TS 23.501
```

### Step 6 — ranking

The result containing:

```text
SMF selects a UPF during PDU Session Establishment...
```

gets very high score.

---

# 29. The really interesting part: learning from search logs

Once deployed, you can improve the ontology using actual queries.

Collect:

```text
query
→ extracted concepts
→ expanded concepts
→ clicked result
→ selected result
→ user reformulation
```

Suppose users repeatedly search:

```text
"UPF choose"
"UPF selection"
"how is UPF selected"
"select UPF"
```

You can discover:

```text
UPF_SELECTION
```

as an important latent concept.

Then your offline AI process can propose:

```text
UPF selection
    aliases:
        UPF selection
        UPF selection procedure
        UPF selection criteria
        selecting UPF
        UPF selection mechanism
```

Human validates it.

Then it becomes part of the next ontology release.

So the system becomes:

```text
                     Search logs
                         │
                         ▼
                 Offline AI analysis
                         │
                         ▼
                  Ontology proposals
                         │
                    human review
                         │
                         ▼
                 New ontology release
                         │
                         ▼
                  Runtime search
                         │
                         ▼
                    Search logs
                         │
                         └─────────────►
```

This is a very nice **closed-loop architecture**.

---

# 30. Recommended implementation roadmap

I wouldn't attempt the whole ontology immediately.

## Phase 1 — baseline

Build:

```text
3GPP documents
     ↓
parser/chunker
     ↓
BM25 search
```

Establish a benchmark of perhaps **100–500 real queries**.

Measure:

```text
Recall@5
Recall@10
MRR
NDCG
```

This gives you the baseline.

---

## Phase 2 — terminology knowledge

Build:

```text
3GPP terminology dictionary
        ↓
exact / fuzzy / phrase matcher
        ↓
query expansion
        ↓
BM25
```

Measure improvement.

This phase may already produce a surprisingly large gain.

---

## Phase 3 — ontology

Add:

```text
Concept
Parent/child
Alias
Abbreviation
Related concept
Specification
Procedure
Interface
Message
```

Then:

```text
query
 ↓
NER
 ↓
concept mapping
 ↓
ontology expansion
 ↓
search
```

---

## Phase 4 — relationship-aware search

Add:

```text
SMF ──selects──► UPF
AMF ──controls──► registration
UE ──establishes──► PDU session
```

Now you can support more semantic queries.

---

## Phase 5 — intent

Add:

```text
definition
procedure
failure
configuration
message
parameter
architecture
security
```

This will improve ranking significantly.

---

## Phase 6 — small local NER model

Only after dictionary/rules are strong.

Use the model for:

```text
unknown terminology
ambiguous phrases
complex noun phrases
```

rather than everything.

---

## Phase 7 — learning loop

Use search logs to discover:

```text
missing terms
missing aliases
bad expansions
bad ranking
missing relationships
```

Then AI assists ontology maintenance offline.

---

# 31. My recommended final architecture

If I were designing this system, I'd aim for:

```text
                         OFFLINE
┌────────────────────────────────────────────────────┐
│                                                    │
│  3GPP specifications                               │
│        │                                           │
│        ├───────────────┐                           │
│        ▼               ▼                           │
│  terminology       document structure              │
│  extraction            extraction                  │
│        │               │                           │
│        ▼               │                           │
│       LLM              │                           │
│        │               │                           │
│        ▼               ▼                           │
│  ┌───────────────────────────────┐                │
│  │       3GPP Ontology           │                │
│  │                               │                │
│  │ Concepts                       │                │
│  │ Terms                          │                │
│  │ Abbreviations                  │                │
│  │ Relationships                  │                │
│  │ Procedures                     │                │
│  │ Interfaces                     │                │
│  │ Messages                       │                │
│  │ Specifications                 │                │
│  │ Provenance                     │                │
│  └───────────────┬───────────────┘                │
│                  │                                │
│                  ▼                                │
│         Ontology Compiler                         │
│                  │                                │
│        ┌─────────┼──────────┐                     │
│        ▼         ▼          ▼                     │
│     Dictionary  Trie     Rules                    │
│                                                    │
└────────────────────┬───────────────────────────────┘
                     │
               VERSIONED PACK
                     │
                     ▼
                       RUNTIME
┌────────────────────────────────────────────────────┐
│                                                    │
│ User Query                                         │
│      │                                             │
│      ▼                                             │
│ Normalization                                      │
│      │                                             │
│      ▼                                             │
│ Deterministic NER                                  │
│      │                                             │
│      ├──── dictionary                              │
│      ├──── phrase trie                             │
│      ├──── regex                                    │
│      └──── optional small CPU model                │
│      │                                             │
│      ▼                                             │
│ Concept Resolver                                   │
│      │                                             │
│      ▼                                             │
│ Intent Detector                                    │
│      │                                             │
│      ▼                                             │
│ Ontology Reasoner                                  │
│      │                                             │
│      ▼                                             │
│ Query IR                                           │
│      │                                             │
│      ├──────────────┐                              │
│      ▼              ▼                              │
│   BM25/search    optional vector                  │
│      │              │                              │
│      └──────┬───────┘                              │
│             ▼                                      │
│       Relationship-aware                           │
│          reranking                                 │
│             │                                      │
│             ▼                                      │
│       3GPP results                                 │
│                                                    │
└────────────────────────────────────────────────────┘
```

## The central design principle

I would summarize the whole system as:

> **LLM as an offline knowledge engineer; ontology as the persistent reasoning layer; deterministic NLP as the runtime interface; conventional search as the retrieval engine.**

That is much more controllable than putting an LLM in the runtime search path.

And importantly, it gives you **explainability**:

```text
Why did this result rank highly?

✓ exact match: UPF
✓ exact match: PDU Session Establishment
✓ ontology relation: SMF → selects → UPF
✓ procedure match
✓ TS 23.502
✓ clause-level proximity
```

rather than:

> "The AI thought this document was relevant."

---

### One thing I would do before implementing anything

Create a **small prototype with ~100 real 3GPP queries** and compare four systems:

```text
A. BM25 only

B. BM25 + dictionary expansion

C. BM25 + ontology expansion

D. BM25 + ontology + relationship-aware ranking
```

This will tell you **where the actual gain comes from** before you invest in a large ontology.

If you want, I can next design the **actual ontology schema + JSON examples + runtime query algorithm/pseudocode**, including how I would implement the deterministic NER/phrase matcher and query compiler on a CPU.
