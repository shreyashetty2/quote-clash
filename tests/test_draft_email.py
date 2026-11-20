import re

from app.agent.compare import compare
from app.agent.draft_email import build_asks, draft_email
from app.agent.normalize import normalize
from app.agent.recommend import recommend
from app.agent.risk_check import risk_check
from app.schemas import EmailDraft
from tests.helpers import load_quote


def setup(stems):
    quotes = [load_quote(s) for s in stems]
    norms = [normalize(q) for q in quotes]
    comp = compare(norms)
    flags = risk_check(quotes, norms, comp)
    return recommend(comp, flags), comp, quotes, norms, flags


CATERING = ["catering_tableandfork", "catering_harvestkitchen", "catering_urbanplate"]
CLEANING = ["cleaning_sparkleworks", "cleaning_cleanslate", "cleaning_evergreen"]


def test_template_email_is_specific_and_uses_competing_quotes():
    rec, comp, quotes, norms, flags = setup(CATERING)
    email = draft_email(rec, comp, quotes, norms, flags, context="weekly lunch for 40 people")
    assert email.source == "template"
    body = email.body
    assert "Harvest Kitchen" in body
    assert "$35,460" in body
    assert "$41,520" in body  # cheapest competing quote at equivalent scope (Urban Plate mid)
    assert "equipment and setup charge of $900" not in body.lower()  # phrasing is ours
    assert "Waive the equipment and setup of $900" in body
    assert "3% price increase" in body
    assert "automatic renewal" in body
    assert "weekly lunch for 40 people" in body
    assert "Urban Plate" not in body and "Table & Fork" not in body  # competitors are not named
    assert "\u2014" not in body


def test_asks_follow_the_quote():
    rec, comp, quotes, norms, flags = setup(CLEANING)  # Evergreen: escalator + surcharge
    i = next(i for i, n in enumerate(norms) if n.vendor == rec.vendor)
    asks = build_asks(rec.vendor, quotes[i], norms[i], comp, flags)
    assert any("5% price increase" in a for a in asks)
    assert any("fuel and equipment surcharge of $95" in a for a in asks)


def test_llm_email_used_when_numbers_are_grounded():
    rec, comp, quotes, norms, flags = setup(CATERING)
    good = EmailDraft(subject="Quote", body="Hi, your total is $35,460 and another quote is about $41,520. Can you waive $900?")
    email = draft_email(rec, comp, quotes, norms, flags, llm_fn=lambda p, s: good)
    assert email.source == "llm"
    assert email.body == good.body


def test_llm_email_with_invented_number_falls_back_to_template():
    rec, comp, quotes, norms, flags = setup(CATERING)
    bad = EmailDraft(subject="Quote", body="Another vendor offered us $29,999 so please match it.")
    email = draft_email(rec, comp, quotes, norms, flags, llm_fn=lambda p, s: bad)
    assert email.source == "template"
    assert "29,999" not in email.body


def test_llm_error_falls_back_to_template():
    rec, comp, quotes, norms, flags = setup(CATERING)

    def boom(p, s):
        raise RuntimeError("api down")

    assert draft_email(rec, comp, quotes, norms, flags, llm_fn=boom).source == "template"


def test_prompt_contains_only_structured_facts_not_raw_quote_text():
    rec, comp, quotes, norms, flags = setup(CATERING)
    seen = []

    def spy(p, s):
        seen.append(p)
        return EmailDraft(subject="s", body="b")

    draft_email(rec, comp, quotes, norms, flags, llm_fn=spy)
    assert "Harvest Kitchen" in seen[0]
    assert "This quotation is valid" not in seen[0]
    assert not re.search(r"Urban Plate|Table & Fork", seen[0])
