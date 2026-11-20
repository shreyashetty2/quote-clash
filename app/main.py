import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent.orchestrator import QuoteInput, run_pipeline
from app.analytics import ALLOWED, log_event

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 60_000

STATIC = Path(__file__).parent / "static"
SAMPLES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
SAMPLE_SETS = {
    "cleaning": ["cleaning_sparkleworks", "cleaning_cleanslate", "cleaning_evergreen"],
    "it": ["it_netsure", "it_brightpath", "it_corestack"],
    "catering": ["catering_tableandfork", "catering_harvestkitchen", "catering_urbanplate"],
}

app = FastAPI(title="Quote Clash")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def sse(events: Iterator[dict]) -> Iterator[str]:
    for e in events:
        yield f"event: {e['event']}\ndata: {json.dumps(e)}\n\n"


@app.post("/api/analyze")
async def analyze(
    files: list[UploadFile] = File(default=[]),
    texts: list[str] = Form(default=[]),
    context: str = Form(default=""),
) -> StreamingResponse:
    """Upload 2 to 3 quotes (PDF files and/or pasted text). Streams progress as Server-Sent Events."""
    inputs: list[QuoteInput] = []
    for f in files:
        data = await f.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "Each file must be under 10 MB.")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "Only PDF files are supported. You can paste text instead.")
        inputs.append(QuoteInput(pdf=data))
    for t in texts:
        if t.strip():
            inputs.append(QuoteInput(text=t[:MAX_TEXT_CHARS]))
    if not 2 <= len(inputs) <= 3:
        raise HTTPException(400, "Provide 2 or 3 quotes.")
    return StreamingResponse(
        sse(run_pipeline(inputs, context=context)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/analyze-sample")
def analyze_sample(category: str = Form(...)) -> StreamingResponse:
    """One-click demo with fake sample quotes, so nobody has to upload real pricing."""
    stems = SAMPLE_SETS.get(category)
    if not stems:
        raise HTTPException(400, "Unknown sample set.")
    inputs = [QuoteInput(pdf=(SAMPLES_DIR / f"{s}.pdf").read_bytes()) for s in stems]
    return StreamingResponse(
        sse(run_pipeline(inputs, context=None)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/events", status_code=204)
def track(name: str = Form(...), value: str = Form(default="")) -> None:
    """Frontend analytics: only allow-listed event names and a short value, never quote content."""
    if name not in ALLOWED:
        raise HTTPException(400, "Unknown event.")
    log_event(name, value=value[:40] or None)
