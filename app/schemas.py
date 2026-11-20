"""Pydantic models. Every extracted value carries the source text it came from.

If a value is not in the quote, `value` is None and `source_snippet` is None
(meaning "not found"). Values are never guessed.
"""

from __future__ import annotations

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
    billing_unit: str | None = Field(None, description="e.g. 'per month', 'per lunch'. Null if one time.")
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
