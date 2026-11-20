import pytest

from app.agent.normalize import is_occurrence, normalize, time_periods
from app.schemas import Fee, LineItem, Quote, UnitResolution
from tests.helpers import PDFS, load_expected, load_quote


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.name)
def test_year1_total_matches_fixture(pdf):
    exp = load_expected(pdf)
    n = normalize(load_quote(pdf.stem))
    assert n.complete, n.warnings
    assert n.year1_total == pytest.approx(exp["expected_first_year_pretax_total"])
    assert n.vendor == exp["vendor"]


def test_unit_helpers():
    assert time_periods("user per month") == 12
    assert time_periods("user per year") == 1
    assert time_periods("per week") == 52
    assert time_periods("visit") is None
    assert is_occurrence("person per lunch")
    assert not is_occurrence("hour")


def test_monthly_annual_and_visit_units_line_up():
    q = Quote(
        line_items=[
            LineItem(description="a", quantity=25, unit_price=38, billing_unit="user per month", source_snippet="x"),
            LineItem(description="b", quantity=1, unit_price=3600, billing_unit="year", source_snippet="x"),
            LineItem(description="c", quantity=156, unit_price=185, billing_unit="visit", source_snippet="x"),
        ]
    )
    costs = [ln.annual_cost for ln in normalize(q, "V").lines]
    assert costs == [11400, 3600, 28860]


def test_recurring_and_one_time_fees():
    q = Quote(
        fees=[
            Fee(name="setup", amount=1500, recurring=False, source_snippet="x"),
            Fee(name="monthly", amount=95, recurring=True, billing_unit="month", source_snippet="x"),
            Fee(name="delivery", amount=75, recurring=True, billing_unit="lunch", quantity=48, source_snippet="x"),
        ]
    )
    n = normalize(q, "V")
    assert n.one_time_total == 1500
    assert n.recurring_annual == 95 * 12 + 75 * 48
    assert n.year1_total == 1500 + 1140 + 3600


def test_escalator_applies_to_year2_but_not_one_time_fees():
    n = normalize(load_quote("it_corestack"))
    assert n.year1_total == 15000
    assert n.year2_total == pytest.approx(15900)
    n = normalize(load_quote("it_netsure"))
    assert n.year2_total == n.recurring_annual == 19860


def test_tax_only_when_stated():
    bright = normalize(load_quote("it_brightpath"))
    assert bright.tax_rate_percent == 8.875
    assert bright.year1_total_with_tax == pytest.approx(17600 * 1.08875)
    assert normalize(load_quote("it_netsure")).year1_total_with_tax is None


def test_ambiguous_unit_is_excluded_not_guessed():
    q = Quote(
        line_items=[
            LineItem(description="ok", quantity=1, unit_price=100, billing_unit="month", source_snippet="x"),
            LineItem(description="odd", quantity=10, unit_price=50, billing_unit="hour", source_snippet="x"),
        ],
        fees=[Fee(name="mystery", amount=40, recurring=True, billing_unit="call", source_snippet="x")],
    )
    n = normalize(q, "V")
    assert not n.complete
    assert n.year1_total == 1200
    assert len(n.warnings) == 2
    assert [ln.annual_cost for ln in n.lines if ln.ambiguous] == [None, None]


def test_llm_resolves_ambiguous_unit_and_is_marked():
    q = Quote(line_items=[
        LineItem(description="odd", quantity=10, unit_price=50, billing_unit="hour", source_snippet="10 hours a month")
    ])
    n = normalize(q, "V", resolve_fn=lambda p, s: UnitResolution(periods_per_year=12))
    assert n.complete
    assert n.year1_total == 6000
    assert n.lines[0].resolved_by == "llm"


def test_llm_that_cannot_resolve_leaves_line_ambiguous():
    q = Quote(line_items=[
        LineItem(description="odd", quantity=10, unit_price=50, billing_unit="hour", source_snippet="x")
    ])
    n = normalize(q, "V", resolve_fn=lambda p, s: UnitResolution(periods_per_year=None))
    assert not n.complete


def test_missing_price_is_not_found_not_zero():
    q = Quote(line_items=[LineItem(description="x", quantity=1, unit_price=None, billing_unit="month", source_snippet="x")])
    n = normalize(q, "V")
    assert n.lines[0].annual_cost is None and not n.complete
