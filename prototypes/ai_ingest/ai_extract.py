"""AI-assisted concept extraction from parsed 3GPP sections (prototype).

Uses the reliable "extract concepts from text" prompt (the only format the
local ollama models answer consistently) to produce TYPED concepts
(network_function, procedure, information_element, interface, protocol, qos,
architecture, security) per section. Deterministic candidates are typed only
"abbreviation"/"phrase"; the AI types feed the reasoner/reranker.

Checkpointed + resumable: results are appended to an output JSONL as each
section completes, so a partial run can be resumed without redoing work.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ai_helpers import complete_json  # noqa: E402

CONCEPT_TYPES = (
    "network_function, procedure, information_element, interface, protocol, "
    "qos, architecture, security"
)

PROMPT_TEMPLATE = """Extract the key technical concepts (terms) from this 3GPP specification text. List each concept with its type (choose from: {types}) and a confidence 0-1.

Text:
{text}

Return ONLY a JSON object of the form:
{{"concepts": [{{"canonical": "term", "type": "type", "confidence": 0.9}}]}}"""


def extract_section(text: str, model: str, max_chars: int = 800) -> list[dict]:
    """Extract typed concepts from a section's text (with retry)."""
    prompt = PROMPT_TEMPLATE.format(types=CONCEPT_TYPES, text=text[:max_chars])
    data = complete_json(prompt, model, max_tokens=1024, attempts=10)
    return data.get("concepts", [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", required=True, help="Path to a parsed JSONL file")
    ap.add_argument("--out", required=True, help="Output JSONL (checkpoint)")
    ap.add_argument("--model", default="deepseek-v4-flash:0731-cloud")
    ap.add_argument("--max-chars", type=int, default=800)
    ap.add_argument("--limit", type=int, default=0, help="0 = all sections")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between sections")
    args = ap.parse_args()

    parsed = Path(args.parsed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [l for l in parsed.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        lines = lines[: args.limit]

    # Load already-done clauses (resume support).
    done: set[str] = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["clause"])

    total = len(lines)
    done_count = len(done)
    ok = 0
    fail = 0
    concepts_total = 0
    t_start = time.time()

    with out.open("a", encoding="utf-8") as f:
        for i, line in enumerate(lines):
            d = json.loads(line)
            clause = d["clause"]
            if clause in done:
                continue
            text = d["text"]
            try:
                concepts = extract_section(text, args.model, args.max_chars)
                record = {
                    "spec": d["spec"],
                    "clause": clause,
                    "title": d["title"],
                    "concepts": concepts,
                }
                f.write(json.dumps(record) + "\n")
                f.flush()
                ok += 1
                concepts_total += len(concepts)
            except Exception as e:  # noqa: BLE001
                fail += 1
                # record a failure marker so we don't retry forever on resume
                f.write(
                    json.dumps(
                        {"spec": d["spec"], "clause": clause, "title": d["title"],
                         "concepts": [], "error": str(e)}
                    )
                    + "\n"
                )
                f.flush()
            if (i + 1) % 10 == 0 or i == total - 1:
                el = time.time() - t_start
                rate = (ok + fail) / el if el else 0
                print(
                    f"[{i+1}/{total}] ok={ok} fail={fail} concepts={concepts_total} "
                    f"rate={rate:.2f}/s elapsed={el:.0f}s",
                    flush=True,
                )
            if args.sleep:
                time.sleep(args.sleep)

    print(
        f"DONE: processed={ok+fail} ok={ok} fail={fail} concepts={concepts_total} "
        f"total_time={time.time()-t_start:.0f}s"
    )


if __name__ == "__main__":
    main()
