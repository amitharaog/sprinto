"""'Claude Code as the model' backend - for running the pipeline without an Anthropic API key.

Instead of calling the API, each model request is written to handoff/pending/<key>.json
(system prompt, user prompt, JSON schema). An agent such as Claude Code reads it, writes
the answer to handoff/answers/<key>.json, and the pipeline is re-run. Pages and contacts
are cached, so a re-run continues where it stopped. Answers are validated against the
same Pydantic schemas as the API path, and all decisions stay in code.
"""
from __future__ import annotations

import hashlib
import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from . import config
from .llm import LLMError

T = TypeVar("T", bound=BaseModel)
HANDOFF_DIR = config.ROOT / "handoff"


class NeedsAnswer(LLMError):
    """Raised when a request is waiting for an answer file."""


class HandoffLLM:
    def __init__(self, directory=HANDOFF_DIR):
        self.pending = directory / "pending"
        self.answers = directory / "answers"
        self.pending.mkdir(parents=True, exist_ok=True)
        self.answers.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(schema: type[BaseModel], system: str, user: str) -> str:
        return f"{schema.__name__}-{hashlib.sha1((system + chr(0) + user).encode()).hexdigest()[:12]}"

    def parse(self, *, system: str, user: str, schema: type[T], effort: str = "medium") -> T:
        key = self.key(schema, system, user)
        answer = self.answers / f"{key}.json"
        if answer.exists():
            try:
                return schema.model_validate_json(answer.read_text())
            except ValidationError as e:
                raise LLMError(f"answer {answer.name} doesn't match {schema.__name__}: {e}") from e
        (self.pending / f"{key}.json").write_text(json.dumps({
            "key": key, "schema_name": schema.__name__, "effort": effort,
            "system": system, "user": user, "json_schema": schema.model_json_schema(),
        }, indent=1))
        raise NeedsAnswer(f"waiting for model answer {key}")
