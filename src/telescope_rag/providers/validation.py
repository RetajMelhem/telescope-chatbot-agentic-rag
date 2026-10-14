"""Strict JSON/schema/usage validation. No response repair, coercion, or model substitution."""

import json
import math
from typing import Any

from pydantic import BaseModel, ValidationError

from telescope_rag.providers.contracts import OperationKind, T, UsageReport
from telescope_rag.providers.errors import ProviderError


def load_json(text: str | bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError("nonfinite_json")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite_json")
        return number

    try:
        result = json.loads(
            text, object_pairs_hook=pairs, parse_constant=reject_constant, parse_float=finite_float
        )
        if not isinstance(result, dict):
            raise ValueError("object_required")
        return result
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ProviderError("invalid_provider_json") from None


def output_schema(model: type[BaseModel]) -> dict[str, Any]:
    try:
        schema = model.model_json_schema()
        name = model.__name__
        if not name.isascii() or len(name) > 64 or not all(c.isalnum() or c in "_-" for c in name):
            raise ValueError("invalid_schema_name")

        def check(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("type") == "object":
                    props = value.get("properties", {})
                    if value.get("additionalProperties") is not False or set(
                        value.get("required", [])
                    ) != set(props):
                        raise ValueError("strict_closed_schema_required")
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        if schema.get("type") != "object":
            raise ValueError("object_schema_required")
        check(schema)
        return {"name": name, "strict": True, "schema": schema}
    except (ValueError, TypeError, RecursionError, AttributeError):
        raise ProviderError("unsupported_output_schema") from None


def parse_usage(value: Any, kind: OperationKind) -> UsageReport:
    if value is None:
        return UsageReport()
    if not isinstance(value, dict):
        raise ProviderError("invalid_provider_usage")
    details = value.get("completion_tokens_details")
    if details is not None and not isinstance(details, dict):
        raise ProviderError("invalid_provider_usage")
    try:
        report = UsageReport(
            input_tokens=value.get("prompt_tokens"),
            output_tokens=value.get("completion_tokens"),
            total_tokens=value.get("total_tokens"),
            reasoning_tokens=details.get("reasoning_tokens") if details else None,
        )
        if kind == "embedding" and report.output_tokens not in (None, 0):
            raise ValueError("unexpected_embedding_output_usage")
        if (
            report.reasoning_tokens is not None
            and report.output_tokens is not None
            and report.reasoning_tokens > report.output_tokens
        ):
            raise ValueError("reasoning_not_subset")
        if report.total_tokens is not None and report.input_tokens is not None:
            output = 0 if kind == "embedding" else report.output_tokens
            if output is not None and report.total_tokens != report.input_tokens + output:
                raise ValueError("inconsistent_total")
        return report
    except (ValueError, ValidationError):
        raise ProviderError("invalid_provider_usage") from None


def parse_chat(body: dict[str, Any], model: type[T]) -> T:
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderError("invalid_chat_response")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProviderError("invalid_chat_response")
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise ProviderError("provider_refusal")
    if choice.get("finish_reason") == "length":
        raise ProviderError("truncated_completion")
    if choice.get("finish_reason") != "stop" or message.get("tool_calls"):
        raise ProviderError("unexpected_completion_kind")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("missing_structured_output")
    load_json(content)
    try:
        return model.model_validate_json(content, strict=True)
    except (ValidationError, ValueError, TypeError):
        raise ProviderError("structured_output_invalid") from None


def parse_vectors(
    body: dict[str, Any], count: int, dimensions: int
) -> tuple[tuple[float, ...], ...]:
    data = body.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise ProviderError("embedding_batch_mismatch")
    ordered: dict[int, tuple[float, ...]] = {}
    for item in data:
        if not isinstance(item, dict):
            raise ProviderError("invalid_embedding_response")
        index, vector = item.get("index"), item.get("embedding")
        if type(index) is not int or not 0 <= index < count or index in ordered:
            raise ProviderError("embedding_index_mismatch")
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ProviderError("embedding_dimension_mismatch")
        if any(type(value) not in (int, float) for value in vector):
            raise ProviderError("invalid_embedding_value")
        try:
            values = tuple(float(value) for value in vector)
        except (ValueError, OverflowError):
            raise ProviderError("invalid_embedding_value") from None
        if not all(math.isfinite(value) for value in values) or not any(values):
            raise ProviderError("invalid_embedding_value")
        ordered[index] = values
    return tuple(ordered[index] for index in range(count))
