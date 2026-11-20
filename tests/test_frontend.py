from fastapi.testclient import TestClient

from app import llm
from app.main import SAMPLE_SETS, SAMPLES_DIR, app
from tests.helpers import PDFS, router_llm
from tests.test_orchestrator import parse_sse

client = TestClient(app)


def test_index_page_has_privacy_notice_and_sample_demo():
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert "do not upload confidential quotes" in html.lower()
    assert "Gemini" in html
    assert html.count("data-sample=") == 3
    assert "/static/app.js" in html


def test_static_js_served():
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "EventSource" not in r.text  # POST streaming via fetch, not EventSource
    assert "/api/analyze-sample" in r.text


def test_no_em_dashes_in_frontend():
    for name in ("index.html", "app.js"):
        assert "—" not in client.get("/" if name == "index.html" else f"/static/{name}").text


def test_every_sample_set_has_its_pdfs():
    for stems in SAMPLE_SETS.values():
        for s in stems:
            assert (SAMPLES_DIR / f"{s}.pdf").exists()


def test_analyze_sample_streams_a_result(monkeypatch):
    monkeypatch.setattr(llm, "generate_structured", router_llm([p.stem for p in PDFS]))
    for category in SAMPLE_SETS:
        r = client.post("/api/analyze-sample", data={"category": category})
        events = parse_sse(r.text)
        assert events[-1][0] == "result", category


def test_analyze_sample_rejects_unknown_category():
    assert client.post("/api/analyze-sample", data={"category": "nope"}).status_code == 400
