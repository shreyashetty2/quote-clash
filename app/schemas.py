"""Pydantic models. Every extracted value carries the source text it came from.

If a value is not in the quote, `value` is None and `source_snippet` is None
(meaning "not found"). Values are never guessed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: float | None = Field(
        None, description="Units billed as stated in the line (25 users, 156 visits). 1 for a flat rate."
    )
    unit_price: float | None = Field(None, description="Price per billing unit, as a plain number.")
    billing_unit: str | None = Field(None, description="Text of the billing unit, e.g. 'user per month'.")
    source_snippet: str = Field(description="Exact text copied from the quote that states this line item.")


class Fee(BaseModel):
    name: str
    amount: float | None = Field(None, description="Fee amount in dollars, as a plain number.")
    recurring: bool | None = Field(None, description="True if charged repeatedly, False if one time.")
    billing_unit: str | None = Field(None, description="e.g. 'month', 'lunch'. Null if one time.")
    quantity: float | None = Field(
        None,
        description="For a fee charged per occurrence, how many times it is charged over the quote period "
        "if the quote states it (e.g. 48 lunches). Null otherwise.",
    )
    source_snippet: str = Field(description="Exact text copied from the quote that states this fee.")


class Tax(BaseModel):
    rate_percent: float | None = None
    source_snippet: str | None = None


class IntTerm(BaseModel):
    value: int | None = None
    source_snippet: str | None = None


class FloatTerm(BaseModel):
    value: float | None = None
    source_snippet: str | None = None


class BoolTerm(BaseModel):
    value: bool | None = None
    source_snippet: str | None = None


class Terms(BaseModel):
    contract_months: IntTerm = Field(default_factory=IntTerm)
    auto_renewal: BoolTerm = Field(
        default_factory=BoolTerm,
        description="True if it renews automatically, False only if the quote says it does not.",
    )
    renewal_notice_days: IntTerm = Field(default_factory=IntTerm)
    price_escalator_percent: FloatTerm = Field(default_factory=FloatTerm)
    late_fee_percent: FloatTerm = Field(default_factory=FloatTerm)
    payment_terms_days: IntTerm = Field(default_factory=IntTerm)


class QuoteExtraction(BaseModel):
    """The shape the LLM is asked to produce."""

    vendor: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    fees: list[Fee] = Field(default_factory=list)
    tax: Tax = Field(default_factory=Tax)
    terms: Terms = Field(default_factory=Terms)


class Quote(QuoteExtraction):
    """Validated extraction. `warnings` lists anything dropped for lacking grounding."""

    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- normalize

Severity = Literal["high", "medium", "low"]


class NormalizedLine(BaseModel):
    kind: Literal["item", "fee"]
    name: str
    recurring: bool
    annual_cost: float | None = Field(None, description="Cost over 12 months; None if the unit was ambiguous.")
    basis: str = Field(description="How annual_cost was computed, e.g. '25 x $38.00 x 12'.")
    ambiguous: bool = False
    resolved_by: Literal["rule", "llm"] = "rule"
    source_snippet: str


class NormalizedQuote(BaseModel):
    vendor: str
    lines: list[NormalizedLine]
    year1_total: float = Field(description="Sum of all lines with a known annual cost, before tax.")
    recurring_annual: float
    one_time_total: float
    year2_total: float = Field(description="Recurring lines with the stated escalator applied, no one-time fees.")
    tax_rate_percent: float | None = None
    year1_total_with_tax: float | None = Field(None, description="None when no tax rate is stated.")
    contract_months: int | None = None
    complete: bool = Field(description="False if any line was ambiguous, so totals are partial.")
    warnings: list[str] = Field(default_factory=list)


class UnitResolution(BaseModel):
    """LLM answer for an ambiguous billing unit."""

    periods_per_year: float | None = Field(
        None, description="How many times per year quantity x unit_price is charged. Null if truly unclear."
    )


# ------------------------------------------------------------------ compare

class ComparisonRow(BaseModel):
    concept: str
    label: str
    kind: Literal["item", "fee"]
    known_concept: bool = True
    costs: dict[str, float | None] = Field(description="Annual cost per vendor; None if the vendor omits it.")
    snippets: dict[str, str | None]


class MissingItem(BaseModel):
    concept: str
    label: str
    vendor: str
    estimate_low: float
    estimate_high: float
    included_by: list[str]


class VendorSummary(BaseModel):
    vendor: str
    year1_total: float
    year2_total: float
    year1_total_with_tax: float | None = None
    complete: bool
    missing_concepts: list[str]
    like_for_like_low: float
    like_for_like_high: float
    headline_rank: int
    like_for_like_rank: int


class Comparison(BaseModel):
    vendors: list[VendorSummary]
    rows: list[ComparisonRow]
    missing: list[MissingItem]
    cheapest_headline: str
    cheapest_like_for_like: str


# --------------------------------------------------------------- risk_check

class RiskFlag(BaseModel):
    vendor: str
    rule: str
    severity: Severity
    title: str
    explanation: str
    source_snippet: str | None = None
    source: Literal["rule", "llm"] = "rule"


class LLMRiskFlag(BaseModel):
    title: str
    severity: Severity
    explanation: str
    source_snippet: str


class LLMRiskResult(BaseModel):
    flags: list[LLMRiskFlag] = Field(default_factory=list)
