"""Test the impact of max_tokens on model failure rate.

The deepseek model is known to use more thinking tokens per question. If
max_tokens is too small, the model may run out of output budget mid-thinking
and return empty/malformed JSON, causing a fallback to deterministic mode.

This script runs the extract prompt on a fixed set of sections at several
max_tokens values and reports the failure rate + avg concepts per success.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ai_helpers import complete_json  # noqa: E402

CONCEPT_TYPES = "network_function, procedure, information_element, interface, protocol, qos, architecture, security"

EXTRACT_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the specification text below, identify NEW technical concepts (terms) that are NOT already covered by the existing knowledge base.

The existing knowledge base already contains these terms:
{known}

Text:
{text}

List each NEW concept with its type (choose from: {types}) and a confidence 0-1. Return ONLY a JSON object of the form:
{{"concepts": [{{"canonical": "term", "type": "type", "confidence": 0.9}}]}}"""


def load_sections(parsed: Path) -> list:
    sections = []
    for line in parsed.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sections.append(json.loads(line))
    return sections


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-v4-flash:0731-cloud"
    max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    tokens_list = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [1024, 2048, 4096]
    sections = load_sections(Path("data/parsed/38300-i30.jsonl"))
    # Fixed spread of sections (skip empty ones).
    test_idx = [0, 5, 20, 50, 100, 200, 300, 400]
    test_sections = [s for i, s in enumerate(sections) if i in test_idx and s["text"].strip()]

    print(f"model={model} max_chars={max_chars} sections={len(test_sections)}")
    for mt in tokens_list:
        fails = 0
        total_concepts = 0
        total_time = 0.0
        for s in test_sections:
            text = s["text"][:max_chars]
            prompt = EXTRACT_PROMPT_TEMPLATE.format(
                text=text, types=CONCEPT_TYPES, known="(none)"
            )
            t0 = time.time()
            try:
                result = complete_json(prompt, model, max_tokens=mt, attempts=3)
                concepts = result.get("concepts", [])
                total_concepts += len(concepts)
            except Exception:  # noqa: BLE001
                fails += 1
            total_time += time.time() - t0
        n = len(test_sections)
        print(
            f"  max_tokens={mt:5d}  fail={fails}/{n} "
            f"fail_rate={fails/n:.0%}  avg_concepts={total_concepts/max(n-fails,1):.1f} "
            f"avg_time={total_time/n:.1f}s"
        )


if __name__ == "__main__":
    main()
