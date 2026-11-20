"""Run the extract step on every fixture PDF with the real LLM and report field-level accuracy.

Usage: python scripts/eval_extraction.py
Needs GEMINI_API_KEY (or a .env file). Quotes are sent to the Gemini API.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import llm  # noqa: E402
from app.agent.extract import extract_from_pdf  # noqa: E402
from app.evaluation import Score, score_quote  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main() -> None:
    if not llm.is_configured():
        raise SystemExit("GEMINI_API_KEY is not set")
    overall = Score()
    for pdf in sorted(FIXTURES.glob("*.pdf")):
        expected = json.loads(pdf.with_suffix(".expected.json").read_text())
        quote = extract_from_pdf(pdf)
        s = score_quote(quote, expected)
        overall.merge(s)
        print(f"{pdf.name:34} {s.correct:>2}/{s.total:<2} {s.accuracy:6.1%}")
        for m in s.misses:
            print(f"    miss: {m}")
        for w in quote.warnings:
            print(f"    warning: {w}")
    print(f"\nOVERALL field-level accuracy: {overall.correct}/{overall.total} = {overall.accuracy:.1%}")


if __name__ == "__main__":
    main()
