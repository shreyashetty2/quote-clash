"""Step 4: flag risky terms. Rule-based checks first, then an optional LLM pass for anything unusual.

Every flag has a severity, an explanation and the source snippet it came from.
LLM flags whose snippet is not in the quote text are discarded.
"""

from __future__ import annotations

from collections.abc import Callable

from app.agent.extract import _norm
from app.schemas import Comparison, LLMRiskResult, NormalizedQuote, Quote, RiskFlag

LLMFn = Callable[[str, type[LLMRiskResult]], LLMRiskResult]

LLM_PROMPT = """You review a vendor quote for risks to the buyer. These were already flagged by rules, so do not repeat
them: {known}
Flag only other unusual or unfavorable terms (for example uncapped charges, unilateral price changes, broad
liability waivers, minimum purchase commitments, hard-to-meet cancellation conditions). For each flag give a
title, severity (high, medium, low), a plain explanation, and source_snippet copied exactly from the quote.
Return an empty list if nothing else stands out.

QUOTE TEXT:
---
{text}
---"""


def rule_flags(quote: Quote, norm: NormalizedQuote) -> list[RiskFlag]:
    v = norm.vendor
    t = quote.terms
    flags: list[RiskFlag] = []

    def add(rule, severity, title, explanation, snippet=None):
        flags.append(RiskFlag(vendor=v, rule=rule, severity=severity, title=title,
                              explanation=explanation, source_snippet=snippet))

    # auto-renewal
    if t.auto_renewal.value is True:
        days = t.renewal_notice_days.value
        sev = "high" if days is not None and days >= 60 else "medium"
        notice = f" You must give {days} days notice to stop it." if days is not None else ""
        add("auto_renewal", sev, "Auto-renewal",
            "The agreement renews on its own at the end of the term." + notice,
            t.auto_renewal.source_snippet)
    elif t.auto_renewal.value is None:
        add("renewal_unclear", "low", "Renewal terms not stated",
            "The quote does not say whether it renews automatically. Ask before signing.")

    # price escalator
    esc = t.price_escalator_percent.value
    if esc:
        add("price_escalator", "high" if esc >= 5 else "medium", f"Price escalator of {esc:g}%",
            f"Prices rise {esc:g}% over time, so year 2 costs about ${norm.year2_total - norm.recurring_annual:,.2f} "
            f"more than year 1 recurring charges.",
            t.price_escalator_percent.source_snippet)

    # lock-in
    months = t.contract_months.value
    if months is not None and months > 12:
        add("lock_in", "high" if months > 24 else "medium", f"{months} month lock-in",
            f"You are committed for {months} months, longer than the 12 months most buyers can plan for.",
            t.contract_months.source_snippet)

    # fees
    by_name = {ln.name: ln for ln in norm.lines if ln.kind == "fee"}
    for f in quote.fees:
        ln = by_name.get(f.name)
        cost = ln.annual_cost if ln else None
        share = cost / norm.year1_total if cost and norm.year1_total else 0
        if f.recurring is False:
            add("one_time_fee", "medium" if share >= 0.05 else "low",
                f"One-time fee: {f.name}",
                f"A one-time charge of ${f.amount:,.2f} is on top of the listed prices"
                + (f" ({share:.1%} of the first-year total)." if share else "."),
                f.source_snippet)
        elif f.recurring:
            add("recurring_fee", "medium" if share >= 0.03 else "low",
                f"Extra recurring fee: {f.name}",
                f"A recurring charge adds ${cost:,.2f} a year ({share:.1%} of the first-year total)."
                if cost else "A recurring charge is added on top of the listed prices.",
                f.source_snippet)

    # late fee
    late = t.late_fee_percent.value
    if late:
        add("late_fee", "medium" if late >= 2 else "low", f"Late fee of {late:g}% per period",
            f"Overdue balances are charged {late:g}%. Check the period, which is often monthly.",
            t.late_fee_percent.source_snippet)

    return flags


def missing_item_flags(comparison: Comparison) -> list[RiskFlag]:
    flags = []
    for m in comparison.missing:
        flags.append(RiskFlag(
            vendor=m.vendor, rule="missing_item", severity="medium",
            title=f"Missing: {m.label}",
            explanation=(
                f"{', '.join(m.included_by)} include this and {m.vendor} does not. Adding it could cost about "
                f"${m.estimate_low:,.2f} to ${m.estimate_high:,.2f} a year based on those quotes."
            ),
            source_snippet=None,
        ))
    return flags


def llm_flags(vendor: str, text: str, known: list[RiskFlag], llm_fn: LLMFn) -> list[RiskFlag]:
    known_txt = "; ".join(f.title for f in known) or "none"
    result = llm_fn(LLM_PROMPT.format(known=known_txt, text=text), LLMRiskResult)
    t = _norm(text)
    return [
        RiskFlag(vendor=vendor, rule="llm_review", severity=f.severity, title=f.title,
                 explanation=f.explanation, source_snippet=f.source_snippet, source="llm")
        for f in result.flags
        if f.source_snippet and _norm(f.source_snippet) in t
    ]


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def risk_check(
    quotes: list[Quote],
    normalized: list[NormalizedQuote],
    comparison: Comparison | None = None,
    texts: list[str] | None = None,
    llm_fn: LLMFn | None = None,
) -> list[RiskFlag]:
    """Run rules for each quote, add missing-item flags, then the optional LLM pass (needs `texts`)."""
    flags: list[RiskFlag] = []
    for i, (q, n) in enumerate(zip(quotes, normalized, strict=True)):
        mine = rule_flags(q, n)
        if llm_fn and texts:
            mine += llm_flags(n.vendor, texts[i], mine, llm_fn)
        flags += mine
    if comparison:
        flags += missing_item_flags(comparison)
    return sorted(flags, key=lambda f: (SEVERITY_ORDER[f.severity], f.vendor))
