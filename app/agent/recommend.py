"""Step 5: pick a vendor and explain why, using only numbers computed from the quotes."""

from __future__ import annotations

from app.schemas import Alternative, Comparison, Recommendation, RiskFlag

NEAR_TIE = 0.03  # within 3% of the best like-for-like cost counts as a tie


def money(x: float) -> str:
    return f"${x:,.0f}" if abs(x - round(x)) < 0.005 else f"${x:,.2f}"


def _mid(v) -> float:
    return (v.like_for_like_low + v.like_for_like_high) / 2


def recommend(comparison: Comparison, flags: list[RiskFlag]) -> Recommendation:
    vendors = comparison.vendors
    high = {v.vendor: [f.title for f in flags if f.vendor == v.vendor and f.severity == "high"] for v in vendors}

    caveats: list[str] = []
    pool = [v for v in vendors if v.complete]
    if len(pool) < len(vendors):
        names = ", ".join(v.vendor for v in vendors if not v.complete)
        caveats.append(f"Some prices for {names} could not be annualized, so their totals are understated.")
        if not pool:
            pool = list(vendors)

    best_mid = min(_mid(v) for v in pool)
    contenders = [v for v in pool if _mid(v) <= best_mid * (1 + NEAR_TIE)]
    pick = min(contenders, key=lambda v: (len(high[v.vendor]), _mid(v)))
    others = sorted((v for v in vendors if v is not pick), key=_mid)

    labels = {m.concept: m.label.lower() for m in comparison.missing}

    def names(v) -> str:
        return ", ".join(labels.get(c, c) for c in v.missing_concepts)

    reasoning = []
    lo, hi = pick.like_for_like_low, pick.like_for_like_high
    span = money(lo) if lo == hi else f"{money(lo)} to {money(hi)}"
    rivals = [v.vendor for v in contenders if v is not pick]
    if not rivals:
        reasoning.append(f"{pick.vendor} has the lowest first-year cost for the same scope: {span}.")
    else:
        fewer = len(high[pick.vendor]) < min(len(high[v.vendor]) for v in contenders if v is not pick)
        win = "fewer high-severity risks" if fewer else "the lowest cost of the group"
        reasoning.append(
            f"{pick.vendor} ({span} for the same scope) costs about the same as {', '.join(rivals)} "
            f"(within {NEAR_TIE:.0%}) and wins on {win}."
        )
    if pick.missing_concepts:
        reasoning.append(f"Its quote leaves out {names(pick)}; the range above adds that back.")

    if comparison.cheapest_headline != pick.vendor:
        cheap = next(v for v in vendors if v.vendor == comparison.cheapest_headline)
        why = f"it omits {names(cheap)}" if cheap.missing_concepts else "of its terms and risk flags"
        reasoning.append(
            f"{cheap.vendor} has the lowest headline price ({money(cheap.year1_total)}) but "
            f"{why}, so it is not the best value."
        )

    if high[pick.vendor]:
        reasoning.append(f"Negotiate before signing: {'; '.join(high[pick.vendor])}.")
    else:
        reasoning.append("It has no high-severity risk flags.")

    caveats.append("Totals are before tax and cover the first 12 months.")

    priciest = max(vendors, key=_mid)
    savings = max(0.0, _mid(priciest) - _mid(pick))
    pct = savings / _mid(priciest) * 100 if _mid(priciest) else 0.0

    return Recommendation(
        vendor=pick.vendor,
        runner_up=others[0].vendor if others else None,
        year1_total=pick.year1_total,
        like_for_like_low=lo,
        like_for_like_high=hi,
        reasoning=reasoning,
        caveats=caveats,
        high_severity_flags=high[pick.vendor],
        most_expensive_vendor=priciest.vendor,
        savings_vs_most_expensive=round(savings, 2),
        savings_percent=round(pct, 1),
        alternatives=[
            Alternative(vendor=v.vendor, like_for_like_mid=round(_mid(v), 2),
                        more_than_recommended=round(_mid(v) - _mid(pick), 2))
            for v in others
        ],
    )
