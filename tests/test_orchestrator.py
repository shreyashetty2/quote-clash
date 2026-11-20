import json

from fastapi.testclient import TestClient

from app import llm
from app.agent.orchestrator import STEPS, QuoteInput, run_pipeline
from app.main import app
from app.schemas import EmailDraft, QuoteExtraction
from tests.helpers import load_expected, pdf_for, router_llm

CLEANING = ["cleaning_sparkleworks", "cleaning_cleanslate", "cleaning_evergreen"]
CATERING = ["catering_tableandfork", "catering_harvestkitchen", "catering_urbanplate"]


def inputs(stems, as_text=False):
    from app.agent.extract import pdf_to_text

    return [QuoteInput(text=pdf_to_text(pdf_for(s))) if as_text else QuoteInput(pdf=pdf_for(s).read_bytes())
            for s in stems]


def test_events_run_in_order_and_end_with_result():
    events = list(run_pipeline(inputs(CLEANING), llm_fn=router_llm(CLEANING)))
    steps = [(e["step"], e["status"]) for e in events if e["event"] == "step"]
    expected = []
    for name, _ in STEPS:
        expected += [(name, "running"), (name, "done")]
    assert steps == expected
    assert events[-1]["event"] == "result"
    assert sum(e["event"] == "result" for e in events) == 1


def test_result_contents():
    data = list(run_pipeline(inputs(CLEANING), llm_fn=router_llm(CLEANING)))[-1]["data"]
    assert data["recommendation"]["vendor"] == "Evergreen Janitorial"
    assert data["comparison"]["cheapest_headline"] == "CleanSlate Facilities"
    assert len(data["quotes"]) == len(data["normalized"]) == 3
    assert data["email"]["source"] == "llm"  # the fake model's draft has no stray numbers
    assert {f["severity"] for f in data["flags"]} >= {"high", "medium", "low"}
    assert data["time_to_results_ms"] >= 0
    json.dumps(data)  # serializable


def test_pasted_text_works_like_pdf():
    a = list(run_pipeline(inputs(CATERING), llm_fn=router_llm(CATERING)))[-1]["data"]
    b = list(run_pipeline(inputs(CATERING, as_text=True), llm_fn=router_llm(CATERING)))[-1]["data"]
    assert a["recommendation"] == b["recommendation"]


def test_context_reaches_the_email_but_is_truncated():
    seen = []

    def spy(prompt, schema):
        if schema is EmailDraft:
            seen.append(prompt)
        return router_llm(CATERING)(prompt, schema)

    list(run_pipeline(inputs(CATERING), context="x" * 5000 + "TAIL", llm_fn=spy))
    assert "TAIL" not in seen[0]


def test_wrong_number_of_quotes_is_an_error_event():
    events = list(run_pipeline(inputs(CATERING[:1]), llm_fn=router_llm(CATERING)))
    assert events[-1]["event"] == "error"
    assert "2 or 3" in events[-1]["message"]


def test_unreadable_text_is_a_friendly_error():
    bad = [QuoteInput(text="hi"), QuoteInput(pdf=pdf_for(CATERING[0]).read_bytes())]
    events = list(run_pipeline(bad, llm_fn=router_llm(CATERING)))
    assert events[-1]["event"] == "error"
    assert "no readable text" in events[-1]["message"]
    assert events[-2]["status"] == "error" and events[-2]["step"] == "extract"


def test_quote_with_no_prices_is_an_error():
    def empty(prompt, schema):
        return QuoteExtraction() if schema is QuoteExtraction else router_llm(CATERING)(prompt, schema)

    events = list(run_pipeline(inputs(CATERING), llm_fn=empty))
    assert events[-1]["event"] == "error" and "any prices" in events[-1]["message"]


def test_llm_failure_does_not_leak_details():
    def boom(prompt, schema):
        raise RuntimeError("secret internal detail: key=abc123")

    events = list(run_pipeline(inputs(CATERING), llm_fn=boom))
    assert events[-1]["event"] == "error"
    assert "abc123" not in json.dumps(events)


def test_optional_llm_passes_failing_does_not_break_the_run():
    base = router_llm(CATERING)

    def flaky(prompt, schema):
        if schema is EmailDraft or schema.__name__ == "LLMRiskResult":
            raise RuntimeError("down")
        return base(prompt, schema)

    last = list(run_pipeline(inputs(CATERING), llm_fn=flaky))[-1]
    assert last["event"] == "result"
    assert last["data"]["email"]["source"] == "template"


def test_analytics_logged_without_quote_content(capsys):
    list(run_pipeline(inputs(CATERING), llm_fn=router_llm(CATERING)))
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    names = [e["event"] for e in events]
    assert names == ["upload_started", "results_shown", "time_to_results_ms"]
    assert "Harvest" not in out and "$" not in out


# ------------------------------------------------------------------- API

client = TestClient(app)


def parse_sse(body: str):
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_analyze_streams_sse(monkeypatch):
    monkeypatch.setattr(llm, "generate_structured", router_llm(CATERING))
    files = [("files", (f"{s}.pdf", pdf_for(s).read_bytes(), "application/pdf")) for s in CATERING]
    r = client.post("/api/analyze", files=files, data={"context": "lunch for 40"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [e for e, _ in events].count("step") == 12
    assert events[-1][0] == "result"
    assert events[-1][1]["data"]["recommendation"]["vendor"] == "Harvest Kitchen"


def test_analyze_accepts_pasted_text(monkeypatch):
    from app.agent.extract import pdf_to_text

    monkeypatch.setattr(llm, "generate_structured", router_llm(CATERING))
    r = client.post("/api/analyze", data={"texts": [pdf_to_text(pdf_for(s)) for s in CATERING]})
    assert parse_sse(r.text)[-1][0] == "result"


def test_analyze_rejects_bad_input():
    pdf = pdf_for(CATERING[0]).read_bytes()
    assert client.post("/api/analyze", files=[("files", ("a.pdf", pdf, "application/pdf"))]).status_code == 400
    two = [("files", ("a.pdf", pdf, "application/pdf")), ("files", ("b.txt", b"not a pdf", "text/plain"))]
    r = client.post("/api/analyze", files=two)
    assert r.status_code == 400 and "PDF" in r.json()["detail"]


def test_events_endpoint_allowlist(capsys):
    assert client.post("/api/events", data={"name": "email_copied"}).status_code == 204
    assert client.post("/api/events", data={"name": "drop table"}).status_code == 400
    assert '"email_copied"' in capsys.readouterr().out
