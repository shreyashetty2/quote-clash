"""Tests for the extract step against the fixtures.

Most tests use a fake LLM so they run offline. The live test calls the real model
and reports field-level accuracy; it is skipped unless GEMINI_API_KEY works.
"""

import json
import os
from pathlib import Path

import pytest

from app import llm
from app.agent.extract import extract_quote, pdf_to_text
from app.evaluation import Score, score_quote
from app.schemas import LineItem, QuoteExtraction

FIXTURES = Path(__file__).parent / "fixtures"
PDFS = sorted(FIXTURES.glob("*.pdf"))


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


def test_nine_fixtures_present():
    assert len(PDFS) == 9


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_pdf_text_contains_every_expected_snippet(pdf):
    text = " ".join(pdf_to_text(pdf).split())
    exp = load_expected(pdf)
    snippets = [i["source_snippet"] for i in exp["line_items"]]
    snippets += [f["source_snippet"] for f in exp["fees"]]
    snippets += [t["source_snippet"] for t in exp["terms"].values() if t["source_snippet"]]
    for s in snippets:
        assert " ".join(s.split()) in text


def test_pdf_to_text_accepts_bytes():
    pdf = PDFS[0]
    assert pdf_to_text(pdf.read_bytes()) == pdf_to_text(pdf)


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_pipeline_with_perfect_llm_scores_100(pdf):
    exp = load_expected(pdf)
    quote = extract_quote(pdf_to_text(pdf), oracle_llm(exp))
    score = score_quote(quote, exp)
    assert score.accuracy == 1.0, score.misses
    assert quote.warnings == []


def test_invented_line_item_is_dropped():
    pdf = next(p for p in PDFS if p.name == "it_corestack.pdf")
    exp = load_expected(pdf)
    good = oracle_llm(exp)

    def lying(prompt, schema):
        out = good(prompt, schema)
        out.line_items.append(
            LineItem(
                description="Premium onsite support",
                quantity=1,
                unit_price=999.0,
                billing_unit="month",
                source_snippet="Premium onsite support - $999.00 per month",
            )
        )
        return out

    quote = extract_quote(pdf_to_text(pdf), lying)
    assert all(i.unit_price != 999.0 for i in quote.line_items)
    assert any("Premium onsite support" in w for w in quote.warnings)


def test_price_not_in_snippet_is_dropped():
    pdf = next(p for p in PDFS if p.name == "it_corestack.pdf")
    exp = load_expected(pdf)
    good = oracle_llm(exp)

    def wrong_number(prompt, schema):
        out = good(prompt, schema)
        out.line_items[0].unit_price = 41.0  # snippet says $38.00
        return out

    quote = extract_quote(pdf_to_text(pdf), wrong_number)
    assert len(quote.line_items) == len(exp["line_items"]) - 1
    assert any("price not in snippet" in w for w in quote.warnings)


def test_invented_term_is_cleared_to_not_found():
    pdf = next(p for p in PDFS if p.name == "it_netsure.pdf")
    exp = load_expected(pdf)
    good = oracle_llm(exp)

    def lying(prompt, schema):
        out = good(prompt, schema)
        out.terms.price_escalator_percent.value = 7.0
        out.terms.price_escalator_percent.source_snippet = "Prices rise 7% every year."
        return out

    quote = extract_quote(pdf_to_text(pdf), lying)
    assert quote.terms.price_escalator_percent.value is None
    assert quote.terms.price_escalator_percent.source_snippet is None
    assert score_quote(quote, exp).accuracy == 1.0


def test_value_without_snippet_is_cleared():
    pdf = next(p for p in PDFS if p.name == "it_netsure.pdf")
    exp = load_expected(pdf)
    good = oracle_llm(exp)

    def sloppy(prompt, schema):
        out = good(prompt, schema)
        out.terms.late_fee_percent.value = 2.0  # no snippet at all
        return out

    quote = extract_quote(pdf_to_text(pdf), sloppy)
    assert quote.terms.late_fee_percent.value is None


def test_whitespace_differences_in_snippet_are_tolerated():
    pdf = next(p for p in PDFS if p.name == "it_corestack.pdf")
    exp = load_expected(pdf)
    exp["line_items"][0]["source_snippet"] = exp["line_items"][0]["source_snippet"].replace(" ", "  ")
    quote = extract_quote(pdf_to_text(pdf), oracle_llm(exp))
    assert len(quote.line_items) == len(exp["line_items"])


def test_empty_extraction_scores_below_100():
    pdf = PDFS[0]
    exp = load_expected(pdf)
    quote = extract_quote(pdf_to_text(pdf), lambda p, s: QuoteExtraction())
    score = score_quote(quote, exp)
    assert score.accuracy < 1.0
    assert score.misses


def test_spurious_item_penalised():
    pdf = next(p for p in PDFS if p.name == "it_corestack.pdf")
    exp = load_expected(pdf)
    base = score_quote(extract_quote(pdf_to_text(pdf), oracle_llm(exp)), exp)
    exp2 = {**exp, "line_items": exp["line_items"][:1]}
    penalised = score_quote(extract_quote(pdf_to_text(pdf), oracle_llm(exp)), exp2)
    assert base.accuracy == 1.0 and penalised.accuracy < 1.0


# ---------------------------------------------------------------- live model

def _live_available() -> bool:
    if not llm.is_configured():
        return False
    try:
        llm.generate_structured("Return an empty extraction.", QuoteExtraction)
        return True
    except Exception:
        return False


@pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call the real model")
def test_live_field_level_accuracy_meets_prd_target(capsys):
    if not _live_available():
        pytest.skip("LLM not configured or API key rejected")
    overall = Score()
    for pdf in PDFS:
        exp = load_expected(pdf)
        quote = extract_quote(pdf_to_text(pdf))
        s = score_quote(quote, exp)
        overall.merge(s)
        print(f"{pdf.name:34} {s.correct}/{s.total} {s.accuracy:.1%}")
        for m in s.misses:
            print("   miss:", m)
    print(f"OVERALL {overall.correct}/{overall.total} = {overall.accuracy:.1%}")
    assert overall.accuracy >= 0.90
