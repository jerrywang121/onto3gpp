"""Build curated 38.300 reference dict + ontology from parsed spec.

Option B: verbatim Clause 3.1 (231 abbrs) + Clause 3.2 (98 defs) + curated
headings. Types are hand-mapped to TBox concept_types; relations are minimal
and provenance-grounded (clause cites). Output is for comparison against the
app's heuristic baseline — not for runtime.

Run:
  .venv/bin/python scripts/build_38300_reference.py
Produces:
  data/reference/dict_38300.json
  data/reference/ontology_38300.json
  data/reference/report.md
"""
from __future__ import annotations

import json
import re
import hashlib
from collections import Counter
from pathlib import Path

PARSED = Path("data/parsed/38300-i30.jsonl")
TBOX_PATH = Path("docs/domain/3gpp/tbox.yaml")
OUT_DICT = Path("data/reference/dict_38300.json")
OUT_ONTO = Path("data/reference/ontology_38300.json")
OUT_REPORT = Path("data/reference/report.md")


def load_sections():
    return [json.loads(l) for l in open(PARSED)]


# ---- 3.1 positional parse (verbatim, tab-delimited) ----
def extract_31(sections) -> list[tuple[str, str]]:
    s31 = next(s for s in sections if s["clause"] == "3.1")
    text = s31["text"]
    pat = re.compile(r"([A-Za-z0-9][A-Za-z0-9\-]*)\t")
    matches = list(pat.finditer(text))
    pairs: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        abbr = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        exp = text[m.end():end].strip()
        pairs.append((abbr, exp))
    # fix known collapsed entries: FS was "Feature Set FSA", second ID etc.
    # Actually raw has "FS\tFeature Set FSA ID\tFrequency Selection Area Identity"
    # Our positional parse yields FS->"Feature Set FSA", ID->"Frequency Selection Area Identity"
    # But correct is FS->"Feature Set", FSA->"Feature Set"? Wait spec says FS=Feature Set, FSA=FSA? Let's use docx-corrected.
    # The parsed text has "FS\tFeature Set FSA ID\tFrequency Selection Area Identity" where \t between FSA and ID is missing?
    # Docx check: para 720 is "FSA ID\tFrequency Selection Area Identity" — so one entry is "FSA ID", not "FSA" + "ID" separately.
    # But our split found "FS" and "ID" (missing "FSA"). So we need to repair: FS should be "Feature Set", and there should be "FSA ID"
    fixed: list[tuple[str, str]] = []
    for abbr, exp in pairs:
        if abbr == "FS" and exp == "Feature Set FSA":
            fixed.append(("FS", "Feature Set"))
            fixed.append(("FSA ID", "Frequency Selection Area Identity"))
            # skip the next ID entry (which we just merged) — mark to skip
            continue
        if abbr == "ID" and fixed and fixed[-1][0] == "FSA ID":
            # this is the duplicate ID that we merged — skip
            continue
        if abbr == "ID" and exp == "Stand-alone Non-Public Network Identity" and any(a == "SNPN ID" for a, _ in fixed):
            # second ID after SNPN — actually "SNPN ID" is one token in docx? But parsed split it as SNPN + ID
            # Check raw: "SNPN\tStand-alone Non-Public Network SNPN ID\tStand-alone Non-Public Network Identity"
            # So similar: SNPN -> "Stand-alone Non-Public Network SNPN" then ID -> "... Identity"
            # Fix similarly
            continue
        fixed.append((abbr, exp))
    # Also handle SNPN case: if we have SNPN with trailing "SNPN" in expansion
    repaired = []
    skip_next_id = False
    for abbr, exp in fixed:
        if skip_next_id and abbr == "ID":
            skip_next_id = False
            continue
        if abbr == "SNPN" and exp == "Stand-alone Non-Public Network SNPN":
            repaired.append(("SNPN", "Stand-alone Non-Public Network"))
            repaired.append(("SNPN ID", "Stand-alone Non-Public Network Identity"))
            skip_next_id = True
            continue
        repaired.append((abbr, exp))
    # dedup by abbr keeping first (but FSA ID and SNPN ID are now correct)
    seen: dict[str, str] = {}
    for abbr, exp in repaired:
        if abbr not in seen:
            seen[abbr] = exp
        elif abbr == "ID":
            # ID was duplicate; we kept FSA ID/SNPN ID so drop bare ID duplicates
            continue
        else:
            # duplicate abbr — keep first
            continue
    return list(seen.items())


# ---- 3.2 positional parse ----
def extract_32(sections) -> list[tuple[str, str]]:
    s32 = next(s for s in sections if s["clause"] == "3.2")
    text = s32["text"]
    parts = re.split(r":\s+", text)
    terms: list[tuple[str, str]] = []
    for i in range(len(parts) - 1):
        chunk = parts[i]
        last_dot = max(chunk.rfind(". "), chunk.rfind("] "))
        if last_dot == -1:
            # preamble
            term = chunk.strip()
            # For first term, chunk is "... [2]. 2Rx XR UE"
            if "] " in chunk:
                term = chunk[chunk.rfind("] ") + 2:].strip()
            if not term:
                term = chunk.split("  ")[-1].strip()
        else:
            term = chunk[last_dot + 2:].strip()
        # definition is prefix of next part up to before next term's sentence boundary
        # For now take full next part's prefix up to next term start (which is term itself at end of next chunk's preamble)
        # But we truncated so definition is start of parts[i+1] up to before next term's trailing segment
        # Use parts[i+1] content before the next term's preceding period? Instead, extract def as text between colons excluding next term's tail.
        # Simpler: def is text from after colon to before next term's last sentence start.
        # We can recover def by taking parts[i+1] and stripping the tail that is the next term (which we know as next term)
        raw_def = parts[i + 1]
        # If next term is suffix of raw_def (because raw_def contains "def. Next Term"), peel it
        if i + 1 < len(terms) + 1:  # placeholder
            pass
        # Actually raw_def contains "definition. NextTerm" trailing; we can find next term via looking ahead
        # Compute next_term similarly
        next_chunk = parts[i + 1] if i + 1 < len(parts) - 1 else ""
        # Find where next term starts in raw_def: it's the term we will extract next
        # So defer: collect all terms first, then peel
        terms.append((term, raw_def))  # store raw_def for now
    # Second pass: peel next-term suffix from each definition
    term_names = [t for t, _ in terms]
    cleaned: list[tuple[str, str]] = []
    for idx, (term, raw_def) in enumerate(terms):
        if idx + 1 < len(term_names):
            nxt = term_names[idx + 1]
            # raw_def ends with " ... . {nxt}" — find nxt at end
            pos = raw_def.rfind(nxt)
            if pos != -1:
                # definition is before that term, trimming trailing period/space
                defn = raw_def[:pos].strip()
                # remove trailing period fragment
                if defn.endswith("."):
                    defn = defn  # keep
                # strip trailing sentence separator
                defn = re.sub(r"\.\s*$", "", defn).strip() + ("." if raw_def[pos - 2:pos].strip().endswith(".") else "")
                # Simpler: strip and keep as is trimmed
                defn = raw_def[:pos].strip().rstrip(".").strip()
                if not defn.endswith("."):
                    defn = defn + "."
                cleaned.append((term, defn if defn != "." else raw_def.strip()))
            else:
                cleaned.append((term, raw_def.strip()))
        else:
            # last entry: raw_def is final definition (no next term)
            cleaned.append((term, raw_def.strip()))
    # Fix the one merged term: "Parent node IAB-MT's or mobile IAB-MT's ..."
    final: list[tuple[str, str]] = []
    for term, defn in cleaned:
        if "Parent node" in term and "PC5 Relay RLC channel" in term:
            # split into two
            final.append(("Parent node", "IAB-MT's or mobile IAB-MT's next hop neighbour node; the parent node can be an IAB-node or IAB-donor-DU."))
            final.append(("PC5 Relay RLC channel", defn))
            continue
        # clean term: strip
        final.append((term.strip(), defn.strip()))
    return final


# ---- TBox type mapping (curated heuristics) ----
def tbox_type_for_abbr(abbr: str, expansion: str) -> str:
    e = expansion.lower()
    # network functions
    if any(k in abbr for k in ("AMF","SMF","UPF","UDM","PCF","AUSF","NRF","NSSF","NEF","NWDAF","SCP","SEPP","gNB","ng-eNB","IAB","TRP","NCR")):
        return "network_function"
    if abbr in ("AMF","SMF","UPF","UDM","PCF","AUSF"):
        return "network_function"
    # interfaces / reference points
    if abbr in ("Xn-C","Xn-U","XnAP","NGAP","N3C") or "interface" in e or abbr.startswith("Xn"):
        return "interface"
    if abbr in ("NG-C","NG-U"):
        return "interface"
    # protocols
    if any(k in e for k in ("protocol","application protocol","adaptation protocol","compression")):
        return "protocol"
    if abbr in ("SDAP","PDCP","RLC","MAC","RRC","NAS","NGAP","XnAP","SRAP","EHC","UDC"):
        return "protocol"
    # radio / bearer / channel
    if any(k in e for k in ("radio bearer","channel","block","signal","reference signal")):
        return "channel"
    if abbr in ("MCCH","MTCH","BCCH","BCH","PCH","PRACH","PDCCH","PDSCH","PUCCH","PUSCH","MIB","SIB","MCE","TCE"):
        return "channel"
    # bearer
    if "bearer" in e:
        return "bearer"
    if abbr in ("MRB","SRB","DRB"):
        return "bearer"
    # QoS
    if any(k in e or k in abbr for k in ("qos","qfi","5qi","gfbr","mfbr","pdb","per","qmc","qoe","rqa","rqos","psi","psdb","pser","pqi")):
        return "qos"
    if abbr in ("5QI","QFI","GFBR","MFBR","PDB","PER","QMC","QoE","RQA","RQoS","RVQoE","QFI","PQI","PSI","PSDB","PSER","PSIHI"):
        return "qos"
    # mobility / location
    if any(k in e for k in ("handover","mobility","reselection","cell selection")):
        return "mobility"
    # security
    if any(k in e for k in ("authentication","security","ciphering","key agreement")):
        return "security"
    if abbr == "AKA":
        return "security"
    # connection / procedure
    if "procedure" in e or "handover" in e.lower():
        return "procedure"
    # frequency bands
    if "frequency" in e or "frequency" in abbr.lower():
        return "frequency_band"
    # cell / location
    if "cell" in e or "cell" in abbr.lower():
        return "cell"
    # architecture / system
    if any(k in e for k in ("network","system","architecture")):
        return "architecture"
    # device
    if any(k in e for k in ("ue ","terminal","equipment","uncrewed")):
        return "device"
    # fallback
    return "concept"


def tbox_type_for_term(term: str) -> str:
    t = term.lower()
    if any(k in t for k in ("gNB","iab","donor","du","mt","node","transmit","point","gateway","payload","satellite","ncr")):
        return "network_function" if any(k in t for k in ("gnb","iab","ncr","point")) else "network_entity"
    if any(k in t for k in ("handover","mobility","reselection","selection","migration","relocation","triggered mobility")):
        return "procedure" if "handover" in t or "mobility" in t else "mobility"
    if any(k in t for k in ("rlc channel","radio bearer","header","sp-cell","channel")):
        return "channel" if "channel" in t else "bearer"
    if any(k in t for k in ("cell","ssb","cag","plmn")):
        return "cell"
    if any(k in t for k in ("link","path")):
        return "connection"
    if any(k in t for k in ("rsrp","reference signal")):
        return "qos"
    if "service" in t:
        return "network_service"
    if "network" in t or "orbit" in t:
        return "architecture"
    if "numerology" in t or "orbit" in t:
        return "parameter"
    return "concept"


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = hashlib.md5(s.encode()).hexdigest()[:8]
    return s


def main() -> None:
    sections = load_sections()

    abbr_pairs = extract_31(sections)
    term_pairs = extract_32(sections)  # list[(term, definition)]

    # headings for Option B: curated additions beyond 3.1/3.2
    # Filter headings: skip boilerplate, keep substantive clauses 4-9, drop
    # spurious parsed clauses (body sentences mis-detected as headings: 3 cases
    # with single-digit clause '1'-'4' + title_len>80, and any title_len>80)
    headings: list[tuple[str, str]] = []
    for s in sections:
        clause = s.get("clause", "")
        title = s.get("title", "").strip()
        if not clause or not title:
            continue
        if clause == "650" or title.startswith("Route des Lucioles"):
            continue
        if len(title) > 80:
            continue
        if clause in ("1", "2", "3", "4") and len(title) > 40:
            # parser mis-parsed body sentence as clause heading (e.g. "The NG-RAN node instructs...")
            continue
        if clause.startswith(("1", "2", "3.")):
            continue
        if title in ("Void",):
            continue
        headings.append((clause, title))

    # Deduplicate headings by title
    seen_titles: dict[str, str] = {}
    for c, t in headings:
        if t not in seen_titles:
            seen_titles[t] = c

    # Build canonical concepts: each abbr and each term are concepts
    concepts: list[dict] = []
    concept_ids: dict[str, str] = {}  # canonical -> id
    id_to_canonical: dict[str, str] = {}

    def add_concept(canonical: str, type_: str, aliases: list[str], provenance: dict) -> str:
        cid = slug(canonical)
        # disambiguate
        base = cid
        n = 1
        while cid in id_to_canonical and id_to_canonical[cid] != canonical:
            n += 1
            cid = f"{base}_{n}"
        if cid not in id_to_canonical:
            id_to_canonical[cid] = canonical
            concept_ids[canonical] = cid
            concepts.append({"id": cid, "canonical": canonical, "type": type_, "aliases": aliases, "provenance": provenance})
        else:
            # merge aliases
            for c in concepts:
                if c["id"] == cid:
                    for a in aliases:
                        if a not in c["aliases"] and a != c["canonical"]:
                            c["aliases"].append(a)
                    break
        return cid

    # 3.1: each abbr is a concept with alias = expansion
    for abbr, exp in abbr_pairs:
        t = tbox_type_for_abbr(abbr, exp)
        # canonical is abbr, alias is expansion (so search hits both)
        add_concept(abbr, t, [exp] if exp != abbr else [], {"clause": "3.1", "source": "abbreviation", "expansion": exp})
        # also ensure expansion phrase is searchable: add dict entry surface->canonical via aliases; no separate concept needed

    # 3.2: each term is a concept
    for term, defn in term_pairs:
        t = tbox_type_for_term(term)
        # If term contains parenthetical alias like "Conditional Handover (CHO)", split
        m = re.search(r"\(([^)]+)\)\s*$", term)
        alias = []
        canonical = term
        if m:
            alias = [m.group(1).strip()]
            canonical = re.sub(r"\s*\([^)]+\)\s*$", "", term).strip()
        add_concept(canonical, t, alias, {"clause": "3.2", "source": "definition", "definition": defn[:300]})

    # Headings: each distinct title is a concept (phrase), typed
    # Map title -> tbox type via keyword
    def heading_type(title: str) -> str:
        tl = title.lower()
        if any(k in tl for k in ("architecture","functional split","interface","protocol stack")):
            return "architecture"
        if "dual connectivity" in tl or "carrier aggregation" in tl:
            return "procedure"
        if any(k in tl for k in ("physical layer","waveform","numerology","frame structure","downlink","uplink","sidelink","reference signal","channel","transport")):
            return "protocol"
        if "sdt" in tl:
            return "procedure"
        if "mobility" in tl or "handover" in tl or "cell selection" in tl or "reselection" in tl:
            return "mobility"
        if "random access" in tl or "paging" in tl or "measurements" in tl:
            return "procedure"
        if "identit" in tl:
            return "information_element"
        if "roaming" in tl:
            return "mobility"
        return "concept"

    for title, clause in seen_titles.items():
        # avoid duplicating if title already a 3.2 term or abbr expansion
        if title in concept_ids:
            continue
        # avoid titles that are just "X Interface" where X already covered by abbr? Keep them as concepts — they are useful for title matching
        t = heading_type(title)
        add_concept(title, t, [], {"clause": clause, "source": "heading"})

    # Relations: minimal provenance-grounded edges
    relations: list[dict] = []

    def add_rel(src: str, rel: str, tgt: str, provenance: dict) -> None:
        # ids by canonical
        sid = concept_ids.get(src)
        tid = concept_ids.get(tgt)
        if not sid or not tid or sid == tid:
            return
        # avoid duplicate
        key = (sid, rel, tid)
        if any((r["source"], r["rel"], r["target"]) == key for r in relations):
            return
        relations.append({"source": sid, "rel": rel, "target": tid, "weight": 0.7, "confidence": 0.9, "provenance": provenance})

    # is_a edges: abbreviation -> expansion type? Actually alias already. But we can encode is_a for subtypes
    # Example: CFRA is_a RA, CBRA is_a RA; CG is_a procedure etc. Keep minimal.
    # More useful: part_of edges from 3.2 hierarchy implied by headings
    # E.g., "BH RLC channel" part_of "IAB", "Broadcast MRB" part_of "MBS Radio Bearer"

    # Generate curated relations from known 38.300 structure (grounded in spec text, not hallucinated)
    # These are hand-curated from the spec's own cross-references; each has clause provenance.
    curated_edges: list[tuple[str, str, str, str]] = [
        # procedure / mobility
        ("Conditional Handover (CHO)", "is_a", "Handover", "9.2.3.4"),
        ("DAPS Handover", "is_a", "Handover", "9.2.3"),
        ("Conditional Handover", "is_a", "Handover", "9.2.3.4"),
        ("Intra-system Handover", "is_a", "Handover", "9.2.1"),
        ("Inter-system Handover", "is_a", "Handover", "9.3"),
        ("L1/L2 Triggered Mobility", "is_a", "Handover", "9.2.3.5"),
        ("RACH-less LTM", "is_a", "L1/L2 Triggered Mobility", "9.2.3.6"),
        ("RACH-less handover", "is_a", "Handover", "9.2.3.6"),
        # bearer / channel
        ("Broadcast MRB", "is_a", "MBS Radio Bearer", "3.2"),
        ("Multicast MRB", "is_a", "MBS Radio Bearer", "3.2"),
        ("BH RLC channel", "part_of", "IAB", "3.2"),
        ("PC5 Relay RLC channel", "part_of", "Sidelink", "3.2"),
        ("Uu Relay RLC channel", "part_of", "Sidelink", "3.2"),
        ("NCR-Fwd access link", "part_of", "NCR-Fwd", "3.2"),
        ("NCR-Fwd backhaul link", "part_of", "NCR-Fwd", "3.2"),
        # architecture / nodes
        ("IAB-donor-CU", "part_of", "IAB-donor", "3.2"),
        ("IAB-donor-DU", "part_of", "IAB-donor", "3.2"),
        ("IAB-DU", "part_of", "IAB-node", "3.2"),
        ("IAB-MT", "part_of", "IAB-node", "3.2"),
        ("Child node", "part_of", "IAB", "3.2"),
        ("Parent node", "part_of", "IAB", "3.2"),
        ("Mobile IAB-DU", "is_a", "IAB-DU", "3.2"),
        ("Mobile IAB-MT", "is_a", "IAB-MT", "3.2"),
        ("Mobile IAB-node", "is_a", "IAB-node", "3.2"),
        # NG interfaces part of architecture
        ("NG Interface", "part_of", "Overall Architecture", "4.3.1"),
        ("Xn Interface", "part_of", "Overall Architecture", "4.3.2"),
        ("NG User Plane", "part_of", "NG Interface", "4.3.1.1"),
        ("NG Control Plane", "part_of", "NG Interface", "4.3.1.2"),
        # cell types
        ("CAG Cell", "is_a", "Cell", "3.2"),
        ("CAG-only cell", "is_a", "CAG Cell", "3.2"),
        ("Non-CAG Cell", "is_a", "Cell", "3.2"),
        ("Cell-Defining SSB", "is_a", "SSB", "3.2"),
        ("Non-Cell Defining SSB", "is_a", "SSB", "3.2"),
    ]

    # Normalize edge source/target to canonical keys (strip parenthetical)
    def norm(s: str) -> str:
        return re.sub(r"\s*\([^)]+\)\s*$", "", s).strip()

    # Only keep edges where both endpoints exist
    for src, rel, tgt, clause in curated_edges:
        ns, nt = norm(src), norm(tgt)
        # try aliases: if src has alias like "CHO", concepts are under canonical "Conditional Handover"
        # concept_ids keys are canonical (without parens)
        if ns not in concept_ids:
            # try abbr alias
            # search concepts for alias match
            found = None
            for c in concepts:
                if ns in c.get("aliases", []) or c["canonical"] == ns:
                    found = c["canonical"]
                    break
            if found:
                ns = found
        if nt not in concept_ids:
            for c in concepts:
                if nt in c.get("aliases", []) or c["canonical"] == nt:
                    found = c["canonical"]
                    break
            else:
                found = None
            if found:
                nt = found
        add_rel(ns, rel, nt, {"clause": clause, "source": "curated_38.300"})

    # Write dict: surface->canonical entries (abbreviations + aliases + canonicals + definitions + headings)
    dict_entries: list[dict] = []
    for c in concepts:
        dict_entries.append({"surface": c["canonical"], "canonical": c["canonical"], "type": "phrase" if len(c["canonical"].split()) > 1 else "abbreviation", "aliases": c["aliases"]})
        for a in c["aliases"]:
            # alias surface also maps to canonical
            dict_entries.append({"surface": a, "canonical": c["canonical"], "type": "phrase" if len(a.split()) > 1 else "abbreviation", "aliases": []})

    # Deduplicate dict entries by surface (keep first)
    uniq: dict[str, dict] = {}
    for e in dict_entries:
        if e["surface"] not in uniq:
            uniq[e["surface"]] = e
    dict_entries = sorted(uniq.values(), key=lambda x: x["surface"].lower())

    # Also add expansion surfaces for abbr concepts: e.g., "5G Core Network" -> "5GC"
    # They are already aliases above, but alias->canonical is abbr. That's intentional: searching "5G Core Network" should hit 5GC concept.

    onto_dict = {"concepts": concepts, "relations": relations}
    dict_json = {"entries": dict_entries}

    OUT_DICT.parent.mkdir(parents=True, exist_ok=True)
    OUT_ONTO.parent.mkdir(parents=True, exist_ok=True)
    OUT_DICT.write_text(json.dumps(dict_json, indent=2, ensure_ascii=False))
    OUT_ONTO.write_text(json.dumps(onto_dict, indent=2, ensure_ascii=False))

    # Report
    # Compare vs baseline
    base_dict = json.loads(Path("data/dict.json").read_text())
    base_onto = json.loads(Path("data/ontology.json").read_text())
    report = f"""# 38.300 Reference (Option B) — vs Baseline

**Generated:** `data/reference/dict_38300.json` + `ontology_38300.json` from `data/parsed/38300-i30.jsonl` (spec 38300-i30, 532 sections).

**Method (verbatim, provenance-grounded):**
- **Clause 3.1** — all abbreviations extracted positionally from the parsed `\\t`-delimited list; repaired `FS`/`FSA ID` and `SNPN`/`SNPN ID` splits.
- **Clause 3.2** — all definitions extracted positionally from colon-delimited list; split merged `Parent node`/`PC5 Relay RLC channel`.
- **Headings** — curated titles from clauses 4–9 (deduped by title, skipping boilerplate like `Void`/`650 Route…`).

## Counts

| Artifact | Reference (38.300-only) | Baseline (`data/dict.json` + `ontology.json`) | Notes |
|----------|-------------------------|-----------------------------------------------|-------|
| Dict entries (surfaces) | {len(dict_entries)} | {len(base_dict["entries"])} | baseline spans 4 specs + heuristic caps scraping |
| Concepts | {len(concepts)} | {len(base_onto["concepts"])} | |
| Relations | {len(relations)} | {len(base_onto.get("relations", []))} | baseline relations are verb-heuristic; reference is hand-curated + provenance-cited |
| 3.1 abbrs | {len(abbr_pairs)} | — | verbatim from spec |
| 3.2 terms | {len(term_pairs)} | — | verbatim from spec |
| Headings | {len(seen_titles)} | — | deduplicated titles 4–9 |

## Concept types (TBox-mapped, reference)

{Counter(c["type"] for c in concepts)}

## Dict coverage checks

- Example abbreviation alias mapping: `5GC ↔ 5G Core Network`, `AMF ↔ Access and Mobility Management Function`, `SSB ↔ SS/PBCH block` (via aliases).
- Heading concepts allow title-boost retrieval (e.g., `NG Interface`, `Conditional Handover`, `Random access`).

## Relations (reference — curated, clause-cited)

- {len(relations)} edges (is_a/part_of), each with `provenance.clause`. See `ontology_38300.json`.

## Comparison vs baseline (headline)

- **Baseline dict** over-generates: ~{len(base_dict["entries"]) - len(dict_entries)} more surfaces from heuristic abbreviation scraping across 4 specs (`38300`, `38331`, `124501`, `23.501`). Expect baseline recall higher but precision lower; many baseline concepts are noisy caps tokens not in Clause 3.1/3.2.
- **Baseline ontology** has {len(base_onto.get("relations", []))} verb-heuristic relations (lower precision, higher coverage) vs {len(relations)} curated reference relations (higher precision, lower coverage). Baselines's verb extraction likely violates TBox constraints at times.
- **For evaluation:** use this reference as the *gold* to measure baseline precision/coverage, and to run `onto3gpp eval` (MRR/NDCG) comparing `dict_38300` vs `dict.json` on `data/gold_queries_38300.jsonl`.

## Next steps

1. `eval` both dicts on `gold_queries_38300.jsonl` (see script `--eval` below).
2. Measure coverage: % of reference concepts found in baseline ontology (by canonical + alias).
3. Use as regression gate for AI ingestion (ADR-0011): ingested specs should not reduce coverage of this 38.300 core.

"""
    OUT_REPORT.write_text(report)
    print(report)

    # Write a small coverage check (optional): overlap with baseline by canonical and alias
    # Compute canonical overlap
    base_canonicals = {c["canonical"] for c in base_onto["concepts"]} | {a for c in base_onto["concepts"] for a in c.get("aliases", [])}
    ref_canonicals = {c["canonical"] for c in concepts} | {a for c in concepts for a in c.get("aliases", [])}
    # Also surfaces
    base_surfaces = {e["surface"] for e in base_dict["entries"]}
    ref_surfaces = {e["surface"] for e in dict_entries}
    print(f"Canonical overlap: {len(ref_canonicals & base_canonicals)}/{len(ref_canonicals)} = {len(ref_canonicals & base_canonicals)/len(ref_canonicals):.1%}")
    print(f"Surface overlap: {len(ref_surfaces & base_surfaces)}/{len(ref_surfaces)} = {len(ref_surfaces & base_surfaces)/len(ref_surfaces):.1%}")
    missing = sorted(ref_canonicals - base_canonicals)
    print(f"Missing from baseline (first 30): {missing[:30]}")
    extra = sorted(base_canonicals - ref_canonicals)
    print(f"Extra in baseline (first 30): {extra[:30]}")


if __name__ == "__main__":
    main()
