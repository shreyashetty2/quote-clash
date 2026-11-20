"""Field-level accuracy of extracted Quotes against expected fixture JSON."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import Quote

TERM_FIELDS = [
    "contract_months",
    "auto_renewal",
    "renewal_notice_days",
    "price_escalator_percent",
    "late_fee_percent",
    "payment_terms_days",
]


@dataclass
class Score:
    correct: int = 0
    total: int = 0
    misses: list[str] = field(default_factory=list)

    def add(self, ok: bool, label: str) -> None:
        self.total += 1
        if ok:
            self.correct += 1
        else:
            self.misses.append(label)

    def merge(self, other: Score) -> None:
        self.correct += other.correct
        self.total += other.total
        self.misses += other.misses

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 1.0


def _eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return abs(float(a) - float(b)) < 1e-6


def _match(expected: list[dict], got: list, key_exp: str, key_got: str) -> list:
    """Pair each expected entry with an unused extracted one that has the same key value."""
    used: set[int] = set()
    pairs = []
    for e in expected:
        hit = None
        for i, g in enumerate(got):
            if i not in used and _eq(e[key_exp], getattr(g, key_got)):
                hit = i
                break
        if hit is not None:
            used.add(hit)
        pairs.append((e, got[hit] if hit is not None else None))
    pairs.append((None, [g for i, g in enumerate(got) if i not in used]))  # spurious
    return pairs


def score_quote(quote: Quote, expected: dict) -> Score:
    """Fields scored: line item price+quantity, fee amount+recurring, tax rate, 6 terms.

    A missing expected item scores all of its fields wrong. An extra item the quote
    does not contain adds one wrong field per item.
    """
    s = Score()
    name = expected["file"]

    *pairs, (_, spurious) = _match(expected["line_items"], quote.line_items, "unit_price", "unit_price")
    for e, g in pairs:
        label = f"{name} item {e['description']!r}"
        s.add(g is not None, f"{label} price")
        s.add(g is not None and _eq(e["quantity"], g.quantity), f"{label} quantity")
    for g in spurious:
        s.add(False, f"{name} spurious item {g.description!r}")

    *pairs, (_, spurious) = _match(expected["fees"], quote.fees, "amount", "amount")
    for e, g in pairs:
        label = f"{name} fee {e['name']!r}"
        s.add(g is not None, f"{label} amount")
        s.add(g is not None and g.recurring is e["recurring"], f"{label} recurring")
    for g in spurious:
        s.add(False, f"{name} spurious fee {g.name!r}")

    s.add(_eq(expected["tax"]["rate_percent"], quote.tax.rate_percent), f"{name} tax rate")
    for key in TERM_FIELDS:
        s.add(_eq(expected["terms"][key]["value"], getattr(quote.terms, key).value), f"{name} {key}")
    return s
