"""Structured-output validation — for agents/tools that require the model's
final answer to conform to a schema (e.g. a downstream system parses it as
JSON). Runs after the response comes back, before it's handed to the caller.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError


class OutputValidationError(Exception):
    pass


def validate_json_output(raw_text: str, schema_model: type[BaseModel]) -> BaseModel:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(f"output is not valid JSON: {exc}") from exc
    try:
        return schema_model.model_validate(data)
    except ValidationError as exc:
        raise OutputValidationError(f"output does not match schema: {exc}") from exc


def check_basic_sanity(text: str, max_chars: int) -> None:
    if not text.strip():
        raise OutputValidationError("output is empty")
    if len(text) > max_chars:
        raise OutputValidationError(f"output exceeds max_chars ({len(text)} > {max_chars})")
