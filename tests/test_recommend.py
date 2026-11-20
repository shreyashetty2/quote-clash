import pytest

from app.agent.compare import compare
from app.agent.normalize import normalize
from app.agent.recommend import recommend
from app.agent.risk_check import risk_check
from app.schemas import Comparison, VendorSummary
from tests.helpers import load_quote

SETS = {
    "it": ["it_netsure", "it_brightpath", "it_corestack"],
    "cleaning": ["cleaning_sparkleworks", "cleaning_cleanslate", "cleaning_evergreen"],
    "catering": ["catering_tableandfork", "catering_harvestkitchen", "catering_urbanplate"],
}


def run(stems):
    quotes = [load_quote(s) for s in stems]
    norms = [normalize(q) for q in quotes]
    comp = compare(norms)
    flags = risk_check(quotes, norms, comp)
    return recommend(comp, flags), comp


def test_it_recommends_corestack_with_savings():
    rec, _ = run(SETS["it"])
    assert rec.vendor == "CoreStack Solutions"
    assert rec.most_expensive_vendor == "NetSure IT Services"
    assert rec.savings_vs_most_expensive == pytest.approx(21360 - 17080)
    assert rec.savings_percent == pytest.approx(20.0, abs=0.1)
    assert rec.high_severity_flags == ["Price escalator of 6%"]
    assert any("Negotiate" in r for r in rec.reasoning)


def test_cleaning_does_not_recommend_cheapest_headline():
    rec, comp = run(SETS["cleaning"])
    assert comp.cheapest_headline == "CleanSlate Facilities"
    assert rec.vendor == "Evergreen Janitorial"
    assert any("CleanSlate" in r and "window cleaning" in r for r in rec.reasoning)


def test_near_tie_wording_names_the_rival_and_the_reason():
    rec, _ = run(SETS["cleaning"])
    first = rec.reasoning[0]
    assert "CleanSlate Facilities" in first and "within 3%" in first and "lowest cost of the group" in first


def test_catering_harvest_wins():
    rec, _ = run(SETS["catering"])
    assert rec.vendor == "Harvest Kitchen"
    assert rec.savings_vs_most_expensive == pytest.approx(43920 - 35460)
    assert [a.vendor for a in rec.alternatives] == ["Urban Plate Co.", "Table & Fork Catering"]
    assert all(a.more_than_recommended > 0 for a in rec.alternatives)


def _summary(name, low, high, rank, complete=True):
    return VendorSummary(vendor=name, year1_total=low, year2_total=low, complete=complete, missing_concepts=[],
                         like_for_like_low=low, like_for_like_high=high, headline_rank=rank, like_for_like_rank=rank)


def test_near_tie_prefers_fewer_high_risks():
    from app.schemas import RiskFlag

    comp = Comparison(vendors=[_summary("A", 1000, 1000, 1), _summary("B", 1020, 1020, 2)], rows=[], missing=[],
                      cheapest_headline="A", cheapest_like_for_like="A")
    flag = RiskFlag(vendor="A", rule="auto_renewal", severity="high", title="Auto-renewal", explanation="x")
    assert recommend(comp, [flag]).vendor == "B"
    assert recommend(comp, []).vendor == "A"


def test_clear_price_gap_beats_risk():
    from app.schemas import RiskFlag

    comp = Comparison(vendors=[_summary("A", 1000, 1000, 1), _summary("B", 1500, 1500, 2)], rows=[], missing=[],
                      cheapest_headline="A", cheapest_like_for_like="A")
    flag = RiskFlag(vendor="A", rule="auto_renewal", severity="high", title="Auto-renewal", explanation="x")
    assert recommend(comp, [flag]).vendor == "A"


def test_incomplete_quote_not_recommended_and_caveat_added():
    comp = Comparison(vendors=[_summary("A", 500, 500, 1, complete=False), _summary("B", 1500, 1500, 2)],
                      rows=[], missing=[], cheapest_headline="A", cheapest_like_for_like="A")
    rec = recommend(comp, [])
    assert rec.vendor == "B"
    assert any("could not be annualized" in c for c in rec.caveats)
