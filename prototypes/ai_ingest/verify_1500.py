"""Verify the model still produces good output at max_chars=1500.

The fallback (try/except -> result={}) masks silent failures: a run can show
fail=0 even if the model returns empty every time. This script directly tests
the extract prompt at 1500 chars on a few sections and reports whether the
model actually returns non-empty concepts.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ai_helpers import complete_json  # noqa: E402

CONCEPT_TYPES = "network_function, procedure, information_element, interface, protocol, qos, architecture, security"


def load_sections(parsed: Path) -> list:
    sections = []
    for line in parsed.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sections.append(json.loads(line))
    return sections

EXTRACT_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the specification text below, identify NEW technical concepts (terms) that are NOT already covered by the existing knowledge base.

The existing knowledge base already contains these terms:
{known}

Text:
{text}

List each NEW concept with its type (choose from: {types}) and a confidence 0-1. Return ONLY a JSON object of the form:
{{"concepts": [{{"canonical": "term", "type": "type", "confidence": 0.9}}]}}"""


def main() -> None:
    model = "minimax-m3:cloud"
    max_chars = 1500
    sections = load_sections(Path("data/parsed/38300-i30.jsonl"))
    # Test a spread of sections (small, medium, large).
    test_idx = [0, 5, 20, 50, 100, 200]
    for idx in test_idx:
        s = sections[idx]
        text = s["text"][:max_chars]
        prompt = EXTRACT_PROMPT_TEMPLATE.format(
            text=text, types=CONCEPT_TYPES, known="(none)"
        )
        try:
            result = complete_json(prompt, model, max_tokens=2048, attempts=5)
            concepts = result.get("concepts", [])
            n = len(concepts)
            sample = concepts[0]["canonical"] if n else "(none)"
            print(
                f"[{idx}] clause={s['clause']} chars={len(text)} "
                f"concepts={n} first={sample!r}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[{idx}] clause={s['clause']} chars={len(text)} FAILED: {e}")


if __name__ == "__main__":
    main()
