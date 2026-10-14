"""Pure validation cases for hostile or incompatible external payloads."""

import pytest
from pydantic import BaseModel, ConfigDict

from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.validation import (
    load_json,
    output_schema,
    parse_chat,
    parse_usage,
    parse_vectors,
)


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"a":1e999}',
        "broken",
        b"\xff",
        '{"a":{"b":1,"b":2}}',
    ],
)
def test_invalid_json(raw) -> None:
    with pytest.raises(ProviderError, match="^invalid_provider_json$"):
        load_json(raw)


@pytest.mark.parametrize(
    "usage",
    [
        [],
        {"prompt_tokens": -1},
        {"completion_tokens": "2"},
        {"prompt_tokens": True},
        {"prompt_tokens": 1.0},
        {"completion_tokens_details": []},
        {"completion_tokens": 2, "completion_tokens_details": {"reasoning_tokens": 3}},
        {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 11},
    ],
)
def test_invalid_usage(usage) -> None:
    with pytest.raises(ProviderError, match="^invalid_provider_usage$"):
        parse_usage(usage, "chat")


def test_invalid_embedding_usage() -> None:
    with pytest.raises(ProviderError, match="^invalid_provider_usage$"):
        parse_usage({"prompt_tokens": 1, "completion_tokens": 2}, "embedding")


def test_schema_rejects_open_objects_defaults_and_nested_open_objects() -> None:
    class Open(BaseModel):
        answer: str

    class Default(BaseModel):
        model_config = ConfigDict(extra="forbid")
        answer: str = "guess"

    class Nested(BaseModel):
        model_config = ConfigDict(extra="forbid")
        answer: Open

    for model in (Open, Default, Nested):
        with pytest.raises(ProviderError, match="^unsupported_output_schema$"):
            output_schema(model)


@pytest.mark.parametrize(
    "content,code",
    [
        ('{"answer":"a","count":1,"extra":true}', "structured_output_invalid"),
        ('{"answer":"a"}', "structured_output_invalid"),
        ('{"answer":"a","count":1,"count":2}', "invalid_provider_json"),
        ('```json\n{"answer":"a","count":1}\n```', "invalid_provider_json"),
        ('{"answer":"a","count":NaN}', "invalid_provider_json"),
    ],
)
def test_structured_content_never_repaired(content, code) -> None:
    class Answer(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        answer: str
        count: int

    with pytest.raises(ProviderError, match=f"^{code}$"):
        parse_chat(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ]
            },
            Answer,
        )


@pytest.mark.parametrize(
    "data,code",
    [
        ([], "embedding_batch_mismatch"),
        ([None], "invalid_embedding_response"),
        ([{"index": True, "embedding": [1, 2]}], "embedding_index_mismatch"),
        ([{"index": 1, "embedding": [1, 2]}], "embedding_index_mismatch"),
        ([{"index": 0, "embedding": [1]}], "embedding_dimension_mismatch"),
        ([{"index": 0, "embedding": ["1", 2]}], "invalid_embedding_value"),
        ([{"index": 0, "embedding": [True, 2]}], "invalid_embedding_value"),
        ([{"index": 0, "embedding": [float("inf"), 2]}], "invalid_embedding_value"),
        ([{"index": 0, "embedding": [float("nan"), 2]}], "invalid_embedding_value"),
        ([{"index": 0, "embedding": [0, 0]}], "invalid_embedding_value"),
        ([{"index": 0, "embedding": [10**400, 2]}], "invalid_embedding_value"),
    ],
)
def test_invalid_vectors(data, code) -> None:
    with pytest.raises(ProviderError, match=f"^{code}$"):
        parse_vectors({"data": data}, 1, 2)


def test_duplicate_indices() -> None:
    with pytest.raises(ProviderError, match="^embedding_index_mismatch$"):
        parse_vectors(
            {"data": [{"index": 0, "embedding": [1, 2]}, {"index": 0, "embedding": [3, 4]}]}, 2, 2
        )
