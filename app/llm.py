"""LLM client wrapper. All model calls go through here so the provider can be swapped.

Env vars: LLM_PROVIDER (default "gemini"), GEMINI_API_KEY, MODEL_NAME.
"""

from __future__ import annotations

import os
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY")) and os.getenv("LLM_PROVIDER", "gemini") == "gemini"


def generate_structured(prompt: str, schema: type[T]) -> T:
    """Call the model and return a validated instance of `schema`."""
    provider = os.getenv("LLM_PROVIDER", "gemini")
    if provider != "gemini":
        raise NotImplementedError(f"LLM_PROVIDER={provider!r} is not implemented yet")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=os.getenv("MODEL_NAME", "gemini-2.5-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
        ),
    )
    return schema.model_validate_json(response.text)
