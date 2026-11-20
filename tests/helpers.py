"""Shared test helpers: fixture loading and a fake LLM that answers from the expected JSON."""

import json
from pathlib import Path

from app.agent.extract import extract_quote, pdf_to_text
from app.schemas import Quote

FIXTURES = Path(__file__).parent / "fixtures"
PDFS = sorted(FIXTURES.glob("*.pdf"))


def pdf_for(stem: str) -> Path:
    return FIXTURES / f"{stem}.pdf"


def load_expected(pdf: Path) -> dict:
    return json.loads(pdf.with_suffix(".expected.json").read_text())


def oracle_llm(expected: dict):
    """A fake LLM that answers exactly what the fixture says."""

    def fn(prompt, schema):
        terms = {
            k: {"value": v["value"], "source_snippet": v["source_snippet"]}
            for k, v in expected["terms"].items()
        }
        return schema.model_validate(
            {
                "vendor": expected["vendor"],
                "line_items": expected["line_items"],
                "fees": expected["fees"],
                "tax": {
                    "rate_percent": expected["tax"]["rate_percent"],
                    "source_snippet": expected["tax"]["source_snippet"],
                },
                "terms": terms,
            }
        )

    return fn


def load_quote(stem: str) -> Quote:
    pdf = pdf_for(stem)
    return extract_quote(pdf_to_text(pdf), oracle_llm(load_expected(pdf)))
