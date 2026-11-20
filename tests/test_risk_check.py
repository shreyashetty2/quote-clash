import pytest

from app.agent.compare import compare
from app.agent.extract import pdf_to_text
from app.agent.normalize import normalize
from app.agent.risk_check import risk_check, rule_flags
from app.schemas import LLMRiskFlag, LLMRiskResult
from tests.helpers import load_quote, pdf_for

# rule -> severity expected from the rule-based pass, per fixture
EXPECTED = {
    "it_netsure": {"one_time_fee": "medium", "renewal_unclear": "low"},
    "it_brightpath": {"auto_renewal": "high", "lock_in": "high"},
    "it_corestack": {"price_escalator": "high", "late_fee": "low", "renewal_unclear": "low"},
    "cleaning_sparkleworks": {"one_time_fee": "low"},
    "cleaning_cleanslate": {"auto_renewal": "high", "lock_in": "medium", "late_fee": "medium"},
    "cleaning_evergreen": {"price_escalator": "high", "recurring_fee": "medium", "renewal_unclear": "low"},
    "catering_tableandfork": {"recurring_fee": "medium", "renewal_unclear": "low"},
    "catering_harvestkitchen": {
        "one_time_fee": "low", "auto_renewal": "medium", "price_escalator": "medium", "late_fee": "low",
    },
    "catering_urbanplate": {"auto_renewal": "high"},
}


@pytest.mark.parametrize("stem", EXPECTED)
def test_rule_flags_per_fixture(stem):
    q = load_quote(stem)
    flags = rule_flags(q, normalize(q))
    assert {f.rule: f.severity for f in flags} == EXPECTED[stem]


@pytest.mark.parametrize("stem", EXPECTED)
def test_rule_flags_cite_source_text(stem):
    text = " ".join(pdf_to_text(pdf_for(stem)).split())
    q = load_quote(stem)
    for f in rule_flags(q, normalize(q)):
        if f.rule == "renewal_unclear":
            assert f.source_snippet is None  # nothing in the quote to cite
        else:
            assert f.source_snippet and " ".join(f.source_snippet.split()) in text


def test_explicit_no_renewal_is_not_flagged():
    q = load_quote("cleaning_sparkleworks")
    assert q.terms.auto_renewal.value is False
    assert not any("renew" in f.rule for f in rule_flags(q, normalize(q)))


def test_missing_item_flags_from_comparison():
    stems = ["cleaning_sparkleworks", "cleaning_cleanslate", "cleaning_evergreen"]
    quotes = [load_quote(s) for s in stems]
    norms = [normalize(q) for q in quotes]
    flags = risk_check(quotes, norms, compare(norms))
    missing = [f for f in flags if f.rule == "missing_item"]
    assert [(f.vendor, f.severity) for f in missing] == [("CleanSlate Facilities", "medium")]
    assert "1,600.00" in missing[0].explanation and "1,680.00" in missing[0].explanation


def test_flags_sorted_high_first():
    stems = ["it_netsure", "it_brightpath", "it_corestack"]
    quotes = [load_quote(s) for s in stems]
    norms = [normalize(q) for q in quotes]
    sevs = [f.severity for f in risk_check(quotes, norms, compare(norms))]
    order = {"high": 0, "medium": 1, "low": 2}
    assert sevs == sorted(sevs, key=order.get)
    assert sevs[0] == "high"


def test_llm_pass_keeps_grounded_flags_and_drops_invented_ones():
    stem = "it_corestack"
    text = pdf_to_text(pdf_for(stem))
    q = load_quote(stem)

    def fake(prompt, schema):
        assert "Price escalator" in prompt  # rule findings are passed so the LLM does not repeat them
        return LLMRiskResult(flags=[
            LLMRiskFlag(title="Short validity", severity="low", explanation="Quote expires in 30 days.",
                        source_snippet="This quotation is valid for 30 days from the date above."),
            LLMRiskFlag(title="Invented", severity="high", explanation="Not in quote.",
                        source_snippet="Customer waives all liability."),
        ])

    flags = risk_check([q], [normalize(q)], texts=[text], llm_fn=fake)
    llm = [f for f in flags if f.source == "llm"]
    assert [f.title for f in llm] == ["Short validity"]
    assert any(f.source == "rule" for f in flags)


def test_llm_pass_skipped_without_texts():
    q = load_quote("it_corestack")
    called = []
    risk_check([q], [normalize(q)], llm_fn=lambda p, s: called.append(1))
    assert not called
