import pytest

from app.agent.compare import compare, concept_for
from app.agent.normalize import normalize
from tests.helpers import load_quote

IT = ["it_netsure", "it_brightpath", "it_corestack"]
CLEANING = ["cleaning_sparkleworks", "cleaning_cleanslate", "cleaning_evergreen"]
CATERING = ["catering_tableandfork", "catering_harvestkitchen", "catering_urbanplate"]


def run(stems):
    return compare([normalize(load_quote(s)) for s in stems])


@pytest.mark.parametrize(
    "name,concept",
    [
        ("Managed helpdesk support", "helpdesk"),
        ("Helpdesk and device support", "helpdesk"),
        ("Server and network monitoring", "monitoring"),
        ("Cloud backup and recovery", "backup"),
        ("Backup and disaster recovery", "backup"),
        ("Window cleaning (quarterly)", "window_cleaning"),
        ("Nightly office cleaning (3 visits per week, 52 weeks)", "core_cleaning"),
        ("Annual janitorial service (3 visits per week)", "core_cleaning"),
        ("Coffee and beverage service", "beverages"),
        ("Monthly lunch package (4 lunches for up to 40 people)", "meals"),
    ],
)
def test_concepts(name, concept):
    assert concept_for(name) == (concept, True)


def test_unknown_item_is_not_a_known_concept():
    assert concept_for("Parking validation")[1] is False


def test_it_missing_backup():
    c = run(IT)
    assert [(m.vendor, m.concept) for m in c.missing] == [("CoreStack Solutions", "backup")]
    m = c.missing[0]
    assert (m.estimate_low, m.estimate_high) == (2000, 2160)
    assert sorted(m.included_by) == ["BrightPath Technologies", "NetSure IT Services"]
    assert c.cheapest_headline == "CoreStack Solutions"


def test_cleaning_ranking_flips_once_missing_windows_are_added():
    c = run(CLEANING)
    assert c.cheapest_headline == "CleanSlate Facilities"
    assert c.cheapest_like_for_like == "Evergreen Janitorial"
    slate = next(v for v in c.vendors if v.vendor == "CleanSlate Facilities")
    assert slate.missing_concepts == ["window_cleaning"]
    assert (slate.like_for_like_low, slate.like_for_like_high) == (27400, 27480)
    assert (slate.headline_rank, slate.like_for_like_rank) == (1, 2)


def test_catering_missing_beverages():
    c = run(CATERING)
    assert [(m.vendor, m.concept) for m in c.missing] == [("Urban Plate Co.", "beverages")]
    assert c.cheapest_headline == c.cheapest_like_for_like == "Harvest Kitchen"


def test_rows_hold_costs_and_none_for_omitted():
    c = run(IT)
    backup = next(r for r in c.rows if r.concept == "backup")
    assert backup.costs == {"NetSure IT Services": 2160, "BrightPath Technologies": 2000, "CoreStack Solutions": None}
    assert backup.snippets["CoreStack Solutions"] is None
    assert backup.snippets["NetSure IT Services"]


def test_fees_get_rows_but_are_never_reported_missing():
    c = run(CLEANING)
    fee_rows = [r for r in c.rows if r.kind == "fee"]
    assert {r.label for r in fee_rows} == {"Initial deep clean", "Fuel and equipment surcharge"}
    assert all(m.concept not in {r.concept for r in fee_rows} for m in c.missing)


def test_no_missing_when_all_include_everything():
    c = run(["it_netsure", "it_brightpath"])
    assert c.missing == []


def test_needs_two_quotes_and_unique_names():
    n = normalize(load_quote("it_netsure"))
    with pytest.raises(ValueError):
        compare([n])
    with pytest.raises(ValueError):
        compare([n, n])
