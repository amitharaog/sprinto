"""Thin wrapper around Claude for structured (schema-validated) outputs.

Every model call in the pipeline goes through `LLM.parse`, which returns a
validated Pydantic object. Tests swap in a fake with the same method.
"""
from __future__ import annotations

from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class StructuredLLM(Protocol):
    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T: ...


class LLM:
    """Claude via the official SDK, with server-side refusal fallback enabled."""

    def __init__(self, model: str | None = None):
        self.model = model or config.CLAUDE_MODEL
        self.client = anthropic.Anthropic()

    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": effort},
                # If a safety classifier declines, the API retries on a fallback model
                # inside the same call instead of failing the company.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}") from e

        if response.stop_reason == "refusal":
            raise LLMError("model declined the request (refusal)")
        if response.stop_reason == "max_tokens":
            raise LLMError("output hit max_tokens before the JSON was complete")
        if response.parsed_output is None:
            raise LLMError("model returned no parseable output")
        return response.parsed_output
