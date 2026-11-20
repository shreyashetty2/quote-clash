"""Anonymous product events written to stdout as JSON. Never pass quote content here."""

from __future__ import annotations

import json
import sys
import time

ALLOWED = {
    "upload_started",
    "results_shown",
    "flag_feedback",
    "choice_changed_answer",
    "email_copied",
    "time_to_results_ms",
}


def log_event(name: str, **props: int | float | str | bool | None) -> None:
    if name not in ALLOWED:
        raise ValueError(f"unknown analytics event {name!r}")
    record = {"event": name, "ts": int(time.time()), **props}
    print(json.dumps(record), file=sys.stdout, flush=True)
