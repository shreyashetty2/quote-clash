"""Step 2: convert every price to an annual cost.

Plain Python handles the common billing units. Only units it cannot read are sent
to the LLM (if an `llm_fn` is given); otherwise they are left out of the totals and
the quote is marked incomplete. Numbers are never guessed.
"""

from __future__ import annotations

from collections.abc import Callable

from app import llm
from app.schemas import (
    Fee,
    LineItem,
    NormalizedLine,
    NormalizedQuote,
    Quote,
    UnitResolution,
)

ResolveFn = Callable[[str, type[UnitResolution]], UnitResolution]

# Time units: (keyword, charges per year). Checked in order.
TIME_UNITS = [("month", 12), ("week", 52), ("quarter", 4), ("year", 1), ("annual", 1)]
# Per-occurrence units: the stated quantity is already the number of occurrences.
OCCURRENCE_WORDS = ("visit", "lunch", "meal", "event", "delivery", "serving", "session")


def time_periods(unit: str | None) -> int | None:
    u = (unit or "").casefold()
    for word, n in TIME_UNITS:
        if word in u:
            return n
    return None


def is_occurrence(unit: str | None) -> bool:
    u = (unit or "").casefold()
    return any(w in u for w in OCCURRENCE_WORDS)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _ask_llm(resolve_fn: ResolveFn, name: str, unit: str | None, snippet: str) -> float | None:
    prompt = (
        "A vendor quote line is billed in a unit that is hard to annualize. Using only the quote text, "
        "say how many times per year quantity x unit price is charged over a 12 month period. "
        "Answer null if the text does not say.\n"
        f"Line: {name}\nBilling unit: {unit}\nQuote text: {snippet}"
    )
    try:
        return resolve_fn(prompt, UnitResolution).periods_per_year
    except Exception:
        return None  # leave the line ambiguous rather than failing the whole run


def _item_line(it: LineItem, resolve_fn: ResolveFn | None) -> NormalizedLine:
    base = dict(kind="item", name=it.description, recurring=True, source_snippet=it.source_snippet)
    if it.unit_price is None or it.quantity is None:
        return NormalizedLine(**base, annual_cost=None, basis="price or quantity not found", ambiguous=True)
    periods = time_periods(it.billing_unit)
    if periods is None and is_occurrence(it.billing_unit):
        periods = 1
    resolved_by = "rule"
    if periods is None and resolve_fn:
        periods = _ask_llm(resolve_fn, it.description, it.billing_unit, it.source_snippet)
        resolved_by = "llm"
    if periods is None:
        return NormalizedLine(
            **base, annual_cost=None, ambiguous=True,
            basis=f"unit {it.billing_unit!r} could not be annualized",
        )
    cost = it.quantity * it.unit_price * periods
    basis = f"{it.quantity:g} x {_money(it.unit_price)} x {periods:g}"
    return NormalizedLine(**base, annual_cost=round(cost, 2), basis=basis, resolved_by=resolved_by)


def _fee_line(f: Fee, resolve_fn: ResolveFn | None) -> NormalizedLine:
    recurring = bool(f.recurring)
    base = dict(kind="fee", name=f.name, recurring=recurring, source_snippet=f.source_snippet)
    if f.amount is None or f.recurring is None:
        return NormalizedLine(**base, annual_cost=None, basis="amount or frequency not found", ambiguous=True)
    if not f.recurring:
        return NormalizedLine(**base, annual_cost=f.amount, basis=f"{_money(f.amount)} one time")
    periods = time_periods(f.billing_unit)
    if periods is None and is_occurrence(f.billing_unit) and f.quantity:
        periods = f.quantity
    resolved_by = "rule"
    if periods is None and resolve_fn:
        periods = _ask_llm(resolve_fn, f.name, f.billing_unit, f.source_snippet)
        resolved_by = "llm"
    if periods is None:
        return NormalizedLine(
            **base, annual_cost=None, ambiguous=True,
            basis=f"recurring fee with unit {f.billing_unit!r} and no stated count",
        )
    return NormalizedLine(
        **base, annual_cost=round(f.amount * periods, 2),
        basis=f"{_money(f.amount)} x {periods:g}", resolved_by=resolved_by,
    )


def normalize(quote: Quote, vendor: str | None = None, resolve_fn: ResolveFn | None = None) -> NormalizedQuote:
    """Annualize a quote. Pass `resolve_fn` (e.g. app.llm.generate_structured) to resolve odd units."""
    lines = [_item_line(i, resolve_fn) for i in quote.line_items]
    lines += [_fee_line(f, resolve_fn) for f in quote.fees]

    known = [ln for ln in lines if ln.annual_cost is not None]
    recurring = round(sum(ln.annual_cost for ln in known if ln.recurring), 2)
    one_time = round(sum(ln.annual_cost for ln in known if not ln.recurring), 2)
    year1 = round(recurring + one_time, 2)

    esc = quote.terms.price_escalator_percent.value
    year2 = round(recurring * (1 + esc / 100), 2) if esc else recurring

    rate = quote.tax.rate_percent
    with_tax = round(year1 * (1 + rate / 100), 2) if rate is not None else None

    warnings = [f"could not annualize {ln.name!r}: {ln.basis}" for ln in lines if ln.ambiguous]
    return NormalizedQuote(
        vendor=vendor or quote.vendor or "Unknown vendor",
        lines=lines,
        year1_total=year1,
        recurring_annual=recurring,
        one_time_total=one_time,
        year2_total=year2,
        tax_rate_percent=rate,
        year1_total_with_tax=with_tax,
        contract_months=quote.terms.contract_months.value,
        complete=not warnings,
        warnings=warnings,
    )


def default_resolver() -> ResolveFn:
    return llm.generate_structured
