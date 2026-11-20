"""Step 6: draft a polite, specific negotiation email to the recommended vendor.

The email uses competing quotes as leverage without naming the competitors. The LLM only
gets a fixed list of facts, and any number in its draft that is not in those facts makes us
fall back to a deterministic template.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from app.agent.recommend import money
from app.schemas import (
    Comparison,
    EmailDraft,
    NormalizedQuote,
    Quote,
    Recommendation,
    RiskFlag,
)

LLMFn = Callable[[str, type[EmailDraft]], EmailDraft]

PROMPT = """Write a negotiation email from a small business buyer to {vendor}, whose quote they prefer.
Be polite, specific and concise (under 220 words). Use the competing quotes as leverage but do not name the
competitors. Make each request in FACTS.asks. Use ONLY numbers that appear in FACTS; do not invent prices,
percentages or dates. Do not promise to sign. Sign off as "[Your name]". Return subject and body.

FACTS:
{facts}"""


def _numbers(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}


def build_asks(
    vendor: str,
    quote: Quote,
    norm: NormalizedQuote,
    comparison: Comparison,
    flags: list[RiskFlag],
) -> list[str]:
    t = quote.terms
    asks: list[str] = []
    mine = {f.rule: f for f in flags if f.vendor == vendor}

    if "auto_renewal" in mine:
        days = t.renewal_notice_days.value
        asks.append("Remove the automatic renewal clause, or at least shorten the non-renewal notice window"
                    + (f" from {days} days." if days else "."))
    elif "renewal_unclear" in mine:
        asks.append("Confirm in writing whether the agreement renews automatically.")
    if "lock_in" in mine:
        asks.append(f"Offer a 12 month term, or let us exit after 12 months, instead of {t.contract_months.value} months.")
    if "price_escalator" in mine:
        asks.append(f"Remove or cap the {t.price_escalator_percent.value:g}% price increase.")
    for f in quote.fees:
        if f.recurring is False and f.amount:
            asks.append(f"Waive the {f.name.lower()} of {money(f.amount)}.")
        elif f.recurring and f.amount:
            asks.append(f"Include the {f.name.lower()} of {money(f.amount)} in the base price.")
    if "late_fee" in mine and mine["late_fee"].severity != "low":
        asks.append(f"Reduce the late fee of {t.late_fee_percent.value:g}%.")
    for m in comparison.missing:
        if m.vendor == vendor:
            asks.append(f"Confirm whether {m.label.lower()} is included, and if not, the price to add it.")
    return asks


def build_facts(
    rec: Recommendation, norm: NormalizedQuote, asks: list[str], context: str | None
) -> dict:
    return {
        "vendor": rec.vendor,
        "our_quote_first_year_total": money(norm.year1_total),
        "competing_quotes_equivalent_scope": [money(a.like_for_like_mid) for a in rec.alternatives],
        "cheapest_competing_quote": money(min(a.like_for_like_mid for a in rec.alternatives))
        if rec.alternatives else None,
        "asks": asks,
        "buyer_context": context,
    }


def template_email(rec: Recommendation, norm: NormalizedQuote, asks: list[str], context: str | None) -> EmailDraft:
    lines = [f"Hello {rec.vendor} team,", ""]
    intro = "Thank you for your quote."
    if context:
        intro += f" We are looking for the following: {context.strip()}"
    lines.append(intro + f" We are comparing a few vendors and yours is our preferred option, with a first-year "
                         f"total of {money(norm.year1_total)}.")
    if rec.alternatives:
        cheapest = min(a.like_for_like_mid for a in rec.alternatives)
        if cheapest < norm.year1_total:
            lines.append(f"Another quote we received for equivalent scope comes to about {money(cheapest)} "
                         f"for the first year, so we would like to see if you can get closer to that.")
        else:
            lines.append(f"Other quotes we received for equivalent scope start at about {money(cheapest)} "
                         f"for the first year, so the terms matter a lot to our decision.")
    if asks:
        lines += ["", "To move forward we would like to ask:"]
        lines += [f"- {a}" for a in asks]
    lines += ["", "If you can address these points we are ready to make a decision quickly. "
              "Thank you for your time.", "", "Best regards,", "[Your name]"]
    return EmailDraft(subject="Your quote: questions before we decide", body="\n".join(lines), source="template")


def draft_email(
    rec: Recommendation,
    comparison: Comparison,
    quotes: list[Quote],
    normalized: list[NormalizedQuote],
    flags: list[RiskFlag],
    context: str | None = None,
    llm_fn: LLMFn | None = None,
) -> EmailDraft:
    idx = next(i for i, n in enumerate(normalized) if n.vendor == rec.vendor)
    asks = build_asks(rec.vendor, quotes[idx], normalized[idx], comparison, flags)
    facts = build_facts(rec, normalized[idx], asks, context)
    fallback = template_email(rec, normalized[idx], asks, context)
    if llm_fn is None:
        return fallback

    facts_json = json.dumps(facts, indent=2)
    try:
        draft = llm_fn(PROMPT.format(vendor=rec.vendor, facts=facts_json), EmailDraft)
    except Exception:
        return fallback
    allowed = _numbers(facts_json)
    stray = {n for n in _numbers(draft.subject + " " + draft.body) if n > 3 and n not in allowed}
    if stray or not draft.body.strip():
        return fallback
    return EmailDraft(subject=draft.subject, body=draft.body, source="llm")
