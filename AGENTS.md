# AGENTS.md — Development Process Rules

This file defines **how** we develop `onto3gpp`. It is binding on all agents
(and humans) working in this repo. Read it before starting any task.

> **Project one-liner:** A domain-general pipeline that builds an ontology-guided
> RAG system. AI works **offline** as a knowledge engineer and **judge**; the
> runtime is deterministic and cheap (optionally AI-free). No human-in-the-loop
> in the build/improve cycle — AI judges its own output against ground truth.

---

## 0. Core Principles

1. **AI offline, deterministic runtime.** LLMs only run in the offline
   build/improve/evaluate stages. The runtime query path must be explainable,
   CPU-only, and runnable with zero AI cost.
2. **No human-in-the-loop.** The bootstrap and iterative improvement loops are
   gated by **AI-as-judge** against a ground-truth evaluation set, not by human
   review. Humans set policy and thresholds; AI executes the loop.
3. **Domain-general.** 3GPP is the first domain, but every AI prompt, schema,
   and pipeline stage must be driven by a **domain pack** (templates + config),
   never hard-coded to 3GPP.
4. **Evidence before assertions.** Never claim something works without running
   the verification command and showing its output.
5. **Small, reversible steps.** Every change is staged, measured, and
   roll-back-able. Prefer many small commits over one big one.

---

## 1. Development Workflow (Staged / Evaluated / Roll-back-able)

We use a **stage-gated, evidence-driven** workflow. Each stage is a vertical
slice that ends with a measurable evaluation.

### 1.1 The Stage Loop

```
1. PROPOSE   — write/update the stage plan in docs/roadmap.md
2. PROTOTYPE — for open architecture questions, build throwaway prototypes
               (skip TDD) to compare options quickly
3. DECIDE    — record the decision in an ADR (docs/adr/)
4. IMPLEMENT — feature work follows TDD/SDD (see §2)
5. EVALUATE  — run the eval harness, record metrics in docs/status.md
6. REVIEW    — re-evaluate architecture; if a better option exists, roll back
               and try it (see §3)
7. PROMOTE   — merge to main only when the stage gate passes
```

### 1.2 Stage Gate

A stage is **done** only when:

- [ ] All planned features implemented (TDD green).
- [ ] Eval harness runs and metrics recorded in `docs/status.md`.
- [ ] Metrics meet the stage's acceptance threshold (or a documented, justified
      exception).
- [ ] ADRs updated for any decisions made.
- [ ] No regressions on previously-promoted stages.

### 1.3 Prototyping (quick evaluation, no TDD)

For **open architecture questions**, create a throwaway prototype to compare
options. Rules:

- Put prototypes under `prototypes/<name>/` (or a dedicated branch).
- **Skip TDD** — the goal is fast signal, not production code.
- Write a short `README.md` in the prototype stating the question, the options
  compared, and the measured result.
- Record the outcome in an ADR. Delete or archive the prototype after the
  decision (keep it in git history / a branch).

---

## 2. Feature Implementation (TDD / SDD)

For **feature work** (not prototyping), follow strict TDD/SDD:

1. **Write the test first** (red) — a failing test that captures the desired
   behavior.
2. **Write the minimal implementation** (green) — make the test pass.
3. **Refactor** — clean up while keeping tests green.
4. **Commit** — one logical change per commit, with a clear message.

Use the `test-driven-development` and `subagent-driven-development` skills.

---

## 3. Architecture Re-evaluation & Roll-back

After **every stage**, re-evaluate the architecture:

- Did the stage meet its metrics? If not, why?
- Is there a simpler/better alternative we should trial?
- Did any assumption in an ADR turn out wrong?

If an alternative looks better:

1. Create a **trial branch** (see §4) for the alternative.
2. Prototype/implement it there.
3. Compare metrics against the current approach.
4. **Roll back** (revert the merge / switch branch) if the alternative wins,
   or keep the current approach if it doesn't.
5. Record the outcome in an ADR.

Rolling back is a **normal, expected** part of the process — not a failure.

---

## 4. Git Branching Model

We use a **trunk-based + trial-branch** model.

```
main  ────────────────────────────────────────────────►  (always green, promoted)
        \                    \                    \
         stage/0-baseline     stage/1-terms        trial/vector-search
         └──► merge           └──► merge           └──► (compare, then merge or discard)
```

- **`main`** — always deployable. Only promoted, evaluated stages land here.
- **`stage/<n>-<name>`** — one branch per roadmap stage. Merged to `main` when
  the stage gate passes.
- **`trial/<name>`** — throwaway branches for architecture alternatives.
  Merged to `main` only if they win; otherwise deleted.
- **`prototype/<name>`** — throwaway branches for quick prototypes.
- **`docs/`** — documentation changes can go straight to `main` (or a
  `docs/` branch if large).

### Branch naming

```
stage/0-baseline
stage/1-terminology
trial/vector-search
prototype/aho-corasick-vs-trie
```

### Commit message convention

```
<type>(<scope>): <summary>

type: feat | fix | docs | refactor | test | chore | trial | revert
scope: e.g. runtime, extract, eval, adr, roadmap
```

---

## 5. Project Structure (persistent memory / planning / tracking)

```
onto3gpp/
├── AGENTS.md                 # this file
├── README.md                 # project overview + quickstart
├── docs/
│   ├── architecture.md       # high-level architecture (living doc)
│   ├── roadmap.md            # staged feature plan + stage gates
│   ├── status.md             # live status tracker (metrics per stage)
│   ├── adr/                  # Architecture Decision Records
│   │   ├── 0001-*.md
│   │   └── ...
│   ├── domain/               # domain packs (templates + config)
│   │   ├── 3gpp/
│   │   │   ├── prompts/      # AI prompt templates (domain-general)
│   │   │   └── config.yaml   # domain config
│   │   └── _template/        # template for new domains
│   └── brainstorm/           # original thinking (keep as reference)
├── prototypes/               # throwaway prototypes (quick eval)
├── src/onto3gpp/             # main package
│   ├── cli.py
│   ├── config.py
│   ├── domain/               # domain-pack loading
│   ├── parser/               # doc parsing (docx/pdf/text)
│   ├── extract/              # candidate term/relation extraction
│   ├── ontology/             # schema, merge, validate, version
│   ├── compile/              # knowledge pack compiler
│   ├── runtime/              # deterministic NER + reasoner
│   ├── search/               # BM25 + rerankers
│   ├── evaluate/             # eval harness (gold set, metrics)
│   └── improve/              # AI-as-judge improvement loop
├── tests/                    # TDD tests
├── data/                     # gold sets, logs, review queue (gitignored)
└── pyproject.toml
```

---

## 6. AI-as-Judge (no human-in-the-loop)

The build/improve loop uses **AI as judge**, not humans:

- **Bootstrap:** AI extracts candidate terms/relations, then **judges its own
  output** against the ground-truth gold set + provenance checks. Only
  candidates passing the judge's confidence threshold enter the ontology.
- **Iterative improvement:** AI analyzes search logs, proposes changes, judges
  them against a hold-out eval set, and promotes only if metrics improve.
- **Humans set policy** (thresholds, gold set, domain pack) but do **not**
  review every candidate.

The judge must be **calibrated and audited** — see `docs/architecture.md` §"AI
as Judge" and the eval harness.

---

## 7. Context Window Discipline

- Keep agent context windows **< 120k tokens**.
- Use **subagents** to isolate independent tasks (see
  `subagent-driven-development` skill).
- Use **codegraph** / targeted reads instead of dumping whole files.
- Keep `docs/status.md` and `docs/roadmap.md` concise — they are the
  persistent memory of where we are and where we're going.

---

## 8. Definition of Done (DoD)

A task is done when:

- [ ] Code follows the project structure and conventions.
- [ ] Tests written (TDD) and passing (feature work).
- [ ] Eval metrics recorded in `docs/status.md` (if applicable).
- [ ] ADRs updated for any decisions.
- [ ] `docs/roadmap.md` and `docs/status.md` reflect reality.
- [ ] Committed on the correct branch with a clear message.
- [ ] Verification command run and output shown (evidence, not assertion).
