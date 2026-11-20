"""Step 1: PDF to text, then LLM to a Quote where every value cites its source text."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path

import pdfplumber

from app import llm
from app.schemas import Quote, QuoteExtraction

LLMFn = Callable[[str, type[QuoteExtraction]], QuoteExtraction]

PROMPT = """You extract structured data from a vendor quote. Rules:
- Copy values only from the quote text. Never invent, estimate or compute numbers.
- Every item, fee and term needs `source_snippet`: the exact text copied from the quote that states it.
- If something is not stated in the quote, leave its value null and its source_snippet null.
- Include every priced line item and every fee, including ones in small print.
- line_items: quantity is the units billed as stated (25 users, 156 visits, 1,920 meals); use 1 for a flat rate.
  unit_price is the price per billing unit as a plain number (no $ or commas).
- fees: extra charges such as setup, onboarding, deep clean, delivery, surcharges. recurring=false for one time.
  Do not repeat line items as fees.
- tax.rate_percent only if a tax rate is stated; "prices exclude tax" is not a rate.
- auto_renewal: true if the quote says it renews automatically, false only if it explicitly says it does not renew,
  otherwise null.
- price_escalator_percent: the stated percent increase of prices over time.
- contract_months: the term length in months.

QUOTE TEXT:
---
{text}
---"""


def pdf_to_text(source: bytes | str | Path) -> str:
    """Extract text from PDF bytes or a path. Kept in memory, nothing written to disk."""
    stream = io.BytesIO(source) if isinstance(source, bytes) else source
    with pdfplumber.open(stream) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _numbers(s: str) -> list[float]:
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))]


def _grounded(snippet: str | None, text_norm: str, number: float | None = None) -> bool:
    """A snippet is grounded if it appears in the quote and, when given, contains the number."""
    if not snippet or _norm(snippet) not in text_norm:
        return False
    if number is not None and not any(abs(n - number) < 1e-9 for n in _numbers(snippet)):
        return False
    return True


def ground(extraction: QuoteExtraction, text: str) -> Quote:
    """Enforce the no-invented-numbers rule: drop anything whose snippet is not in the quote."""
    t = _norm(text)
    warnings: list[str] = []
    quote = Quote(**extraction.model_dump())

    items = []
    for it in quote.line_items:
        if not _grounded(it.source_snippet, t):
            warnings.append(f"dropped line item {it.description!r}: snippet not found in quote")
        elif it.unit_price is not None and not _grounded(it.source_snippet, t, it.unit_price):
            warnings.append(f"dropped line item {it.description!r}: price not in snippet")
        else:
            items.append(it)
    quote.line_items = items

    fees = []
    for f in quote.fees:
        if not _grounded(f.source_snippet, t):
            warnings.append(f"dropped fee {f.name!r}: snippet not found in quote")
        elif f.amount is not None and not _grounded(f.source_snippet, t, f.amount):
            warnings.append(f"dropped fee {f.name!r}: amount not in snippet")
        else:
            fees.append(f)
    quote.fees = fees

    if quote.tax.rate_percent is not None and not _grounded(
        quote.tax.source_snippet, t, quote.tax.rate_percent
    ):
        warnings.append("cleared tax rate: not supported by snippet")
        quote.tax = type(quote.tax)()

    for name in type(quote.terms).model_fields:
        term = getattr(quote.terms, name)
        if term.value is None:
            term.source_snippet = None
            continue
        number = None if isinstance(term.value, bool) else float(term.value)
        if not _grounded(term.source_snippet, t, number):
            warnings.append(f"cleared term {name}: not supported by snippet")
            setattr(quote.terms, name, type(term)())

    quote.warnings = warnings
    return quote


def extract_quote(text: str, llm_fn: LLMFn | None = None) -> Quote:
    """Run the LLM over quote text and return a grounded Quote."""
    llm_fn = llm_fn or llm.generate_structured
    extraction = llm_fn(PROMPT.format(text=text), QuoteExtraction)
    return ground(extraction, text)


def extract_from_pdf(source: bytes | str | Path, llm_fn: LLMFn | None = None) -> Quote:
    return extract_quote(pdf_to_text(source), llm_fn)
