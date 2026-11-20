import json
from collections.abc import Iterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.agent.orchestrator import QuoteInput, run_pipeline
from app.analytics import ALLOWED, log_event

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 60_000

app = FastAPI(title="Quote Clash")


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


@app.post("/api/events", status_code=204)
def track(name: str = Form(...), value: str = Form(default="")) -> None:
    """Frontend analytics: only allow-listed event names and a short value, never quote content."""
    if name not in ALLOWED:
        raise HTTPException(400, "Unknown event.")
    log_event(name, value=value[:40] or None)
