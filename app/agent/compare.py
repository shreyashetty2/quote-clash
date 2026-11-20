"""Step 3: line quotes up side by side and find what one vendor includes and others leave out."""

from __future__ import annotations

from collections import defaultdict

from app.schemas import (
    Comparison,
    ComparisonRow,
    MissingItem,
    NormalizedLine,
    NormalizedQuote,
    VendorSummary,
)

# (concept, label, keywords). First match wins, so order matters.
CONCEPTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("window_cleaning", "Window cleaning", ("window",)),
    ("beverages", "Beverage service", ("beverage", "coffee")),
    ("meals", "Meals", ("lunch", "meal", "catering")),
    ("helpdesk", "Helpdesk support", ("helpdesk", "help desk", "device support")),
    ("monitoring", "Monitoring", ("monitoring",)),
    ("backup", "Backup and recovery", ("backup", "recovery")),
    ("core_cleaning", "Core cleaning service", ("clean", "janitorial")),
]
LABELS = {c: label for c, label, _ in CONCEPTS}


def concept_for(name: str) -> tuple[str, bool]:
    """Return (concept, known). Unknown names become their own row and are never reported missing."""
    n = name.casefold()
    for concept, _, words in CONCEPTS:
        if any(w in n for w in words):
            return concept, True
    return n.strip(), False


def _fee_concept(name: str) -> str:
    return name.casefold().strip()


def compare(quotes: list[NormalizedQuote]) -> Comparison:
    if len(quotes) < 2:
        raise ValueError("compare needs at least 2 quotes")
    names = [q.vendor for q in quotes]
    if len(set(names)) != len(names):
        raise ValueError("vendor names must be unique")

    # concept -> vendor -> (cost, snippet), summed if a vendor has several lines for one concept
    cells: dict[tuple[str, str], dict[str, tuple[float | None, str | None]]] = defaultdict(dict)
    meta: dict[tuple[str, str], tuple[str, bool]] = {}

    def add(q: NormalizedQuote, ln: NormalizedLine) -> None:
        if ln.kind == "item":
            concept, known = concept_for(ln.name)
            label = LABELS.get(concept, ln.name)
        else:
            concept, known, label = _fee_concept(ln.name), False, ln.name
        key = (ln.kind, concept)
        meta[key] = (label, known)
        prev = cells[key].get(q.vendor)
        if prev and prev[0] is not None and ln.annual_cost is not None:
            cells[key][q.vendor] = (prev[0] + ln.annual_cost, prev[1])
        else:
            cells[key][q.vendor] = (ln.annual_cost, ln.source_snippet)

    for q in quotes:
        for ln in q.lines:
            add(q, ln)

    rows = []
    for (kind, concept), per_vendor in cells.items():
        label, known = meta[(kind, concept)]
        rows.append(
            ComparisonRow(
                concept=concept, label=label, kind=kind, known_concept=known,
                costs={v: per_vendor[v][0] if v in per_vendor else None for v in names},
                snippets={v: per_vendor[v][1] if v in per_vendor else None for v in names},
            )
        )
    rows.sort(key=lambda r: (r.kind != "item", r.label))

    missing: list[MissingItem] = []
    for r in rows:
        if r.kind != "item" or not r.known_concept:
            continue
        have = {v: c for v, c in r.costs.items() if c is not None}
        if not have:
            continue
        for v in names:
            if r.costs[v] is None:
                missing.append(
                    MissingItem(
                        concept=r.concept, label=r.label, vendor=v,
                        estimate_low=min(have.values()), estimate_high=max(have.values()),
                        included_by=sorted(have),
                    )
                )

    summaries = []
    for q in quotes:
        mine = [m for m in missing if m.vendor == q.vendor]
        summaries.append(
            dict(
                vendor=q.vendor, year1_total=q.year1_total, year2_total=q.year2_total,
                year1_total_with_tax=q.year1_total_with_tax, complete=q.complete,
                missing_concepts=[m.concept for m in mine],
                like_for_like_low=round(q.year1_total + sum(m.estimate_low for m in mine), 2),
                like_for_like_high=round(q.year1_total + sum(m.estimate_high for m in mine), 2),
            )
        )
    by_headline = sorted(summaries, key=lambda s: s["year1_total"])
    by_lfl = sorted(summaries, key=lambda s: (s["like_for_like_low"] + s["like_for_like_high"]) / 2)
    for s in summaries:
        s["headline_rank"] = by_headline.index(s) + 1
        s["like_for_like_rank"] = by_lfl.index(s) + 1

    return Comparison(
        vendors=[VendorSummary(**s) for s in summaries],
        rows=rows,
        missing=missing,
        cheapest_headline=by_headline[0]["vendor"],
        cheapest_like_for_like=by_lfl[0]["vendor"],
    )
