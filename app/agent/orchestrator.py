"""Runs the six steps in order and yields progress events for the frontend (SSE).

Events are dicts: {"event": "step", "step", "status", ...}, then one of
{"event": "result", "data": Result} or {"event": "error", "message"}. Quote content is never logged.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app import llm
from app.agent.compare import compare
from app.agent.draft_email import draft_email
from app.agent.extract import extract_quote, pdf_to_text
from app.agent.normalize import normalize
from app.agent.recommend import recommend
from app.agent.risk_check import risk_check
from app.analytics import log_event
from app.schemas import Quote, Result

STEPS = [
    ("extract", "Reading quotes"),
    ("normalize", "Normalizing prices"),
    ("compare", "Comparing vendors"),
    ("risk_check", "Checking terms"),
    ("recommend", "Choosing a vendor"),
    ("draft_email", "Drafting email"),
]
MAX_CONTEXT = 1000


class PipelineError(Exception):
    """An error whose message is safe to show to the user."""


@dataclass
class QuoteInput:
    """One uploaded quote: raw PDF bytes or pasted text."""

    pdf: bytes | None = None
    text: str | None = None

    def to_text(self) -> str:
        if self.text is not None:
            return self.text
        assert self.pdf is not None
        return pdf_to_text(self.pdf)


def _label(quotes: list[Quote]) -> list[str]:
    """Unique vendor labels, falling back to 'Vendor A' when the name was not found."""
    labels, seen = [], set()
    for i, q in enumerate(quotes):
        name = q.vendor or f"Vendor {chr(65 + i)}"
        if name in seen:
            name = f"{name} ({chr(65 + i)})"
        seen.add(name)
        labels.append(name)
    return labels


def _step(name: str, status: str, **extra) -> dict:
    label = dict(STEPS)[name]
    return {"event": "step", "step": name, "label": label, "status": status, **extra}


def run_pipeline(
    inputs: list[QuoteInput],
    context: str | None = None,
    llm_fn: Callable | None = None,
    use_llm_risk_pass: bool = True,
) -> Iterator[dict]:
    llm_fn = llm_fn or llm.generate_structured
    context = (context or "").strip()[:MAX_CONTEXT] or None
    started = time.perf_counter()
    log_event("upload_started", quotes=len(inputs))

    def ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    current = "extract"
    try:
        if not 2 <= len(inputs) <= 3:
            raise PipelineError("Upload 2 or 3 quotes to compare.")

        yield _step("extract", "running")
        texts, quotes = [], []
        for n, qi in enumerate(inputs, 1):
            try:
                text = qi.to_text()
            except Exception:
                raise PipelineError(f"Could not read quote {n}. Is it a text-based PDF?") from None
            if len(text.strip()) < 40:
                raise PipelineError(f"Quote {n} has no readable text. Scanned PDFs are not supported yet.")
            quote = extract_quote(text, llm_fn)
            if not quote.line_items:
                raise PipelineError(f"Could not find any prices in quote {n}.")
            texts.append(text)
            quotes.append(quote)
        labels = _label(quotes)
        yield _step("extract", "done", elapsed_ms=ms(), detail=f"Read {len(quotes)} quotes")

        current = "normalize"
        yield _step("normalize", "running")
        normalized = [normalize(q, vendor=lab, resolve_fn=llm_fn) for q, lab in zip(quotes, labels, strict=True)]
        yield _step("normalize", "done", elapsed_ms=ms())

        current = "compare"
        yield _step("compare", "running")
        comparison = compare(normalized)
        yield _step("compare", "done", elapsed_ms=ms(), detail=f"{len(comparison.missing)} missing items")

        current = "risk_check"
        yield _step("risk_check", "running")
        flags = risk_check(quotes, normalized, comparison, texts=texts if use_llm_risk_pass else None,
                           llm_fn=llm_fn if use_llm_risk_pass else None)
        yield _step("risk_check", "done", elapsed_ms=ms(), detail=f"{len(flags)} flags")

        current = "recommend"
        yield _step("recommend", "running")
        rec = recommend(comparison, flags)
        yield _step("recommend", "done", elapsed_ms=ms())

        current = "draft_email"
        yield _step("draft_email", "running")
        email = draft_email(rec, comparison, quotes, normalized, flags, context=context, llm_fn=llm_fn)
        yield _step("draft_email", "done", elapsed_ms=ms())

        warnings = [w for q in quotes for w in q.warnings] + [w for n in normalized for w in n.warnings]
        elapsed = ms()
        result = Result(quotes=quotes, normalized=normalized, comparison=comparison, flags=flags,
                        recommendation=rec, email=email, warnings=warnings, time_to_results_ms=elapsed)
        log_event("results_shown", quotes=len(quotes), flags=len(flags))
        log_event("time_to_results_ms", value=elapsed)
        yield {"event": "result", "data": result.model_dump(mode="json")}
    except PipelineError as e:
        yield _step(current, "error")
        yield {"event": "error", "step": current, "message": str(e)}
    except Exception as e:  # never leak quote content or stack traces to the client
        print(f"pipeline failure in step {current}: {type(e).__name__}")
        yield _step(current, "error")
        yield {"event": "error", "step": current, "message": "Something went wrong analyzing the quotes. Please try again."}
