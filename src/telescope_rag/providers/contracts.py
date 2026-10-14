"""Narrow typed interfaces, explicit accounting profiles, and content-free receipts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telescope_rag.providers.errors import ProviderError

T = TypeVar("T", bound=BaseModel)
OperationKind = Literal["chat", "embedding"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, repr=False)


class TokenCount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    units: int = Field(ge=1)
    model: str = Field(min_length=1)
    profile: str = Field(min_length=1, max_length=128)
    basis: Literal["exact", "upper_bound"]


class TokenCounter(Protocol):
    def count(self, kind: OperationKind, payload: Mapping[str, Any]) -> TokenCount:
        """Count the complete effective input, including schema/context/instruction overhead."""


class UnavailableTokenCounter:
    def count(self, kind: OperationKind, payload: Mapping[str, Any]) -> TokenCount:
        raise ProviderError("token_count_unavailable")


class UsageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)

    def complete_for(self, kind: OperationKind) -> bool:
        return self.input_tokens is not None and (
            kind == "embedding" or self.output_tokens is not None
        )


@dataclass(frozen=True)
class AttemptReceipt:
    operation: int
    kind: OperationKind
    attempt: int
    requested_model: str
    reported_model: str | None
    provider: str | None
    status_code: int | None
    outcome: str
    input_reserved: int
    output_reserved: int
    count_profile: str
    count_basis: str
    usage: UsageReport


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    data: T = field(repr=False)
    receipts: tuple[AttemptReceipt, ...]


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: tuple[tuple[float, ...], ...] = field(repr=False)
    requested_model: str
    dimensions: int
    format_version: str
    receipts: tuple[AttemptReceipt, ...]


class EmbeddingFormat(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: str = Field(min_length=1, max_length=128)
    verified: bool = False
    query_prefix: str = Field(default="", repr=False)
    document_prefix: str = Field(default="", repr=False)
    provider_slug: Literal["deepinfra/us"] | None = None
    reported_model: Literal["Qwen/Qwen3-Embedding-8B"] | None = None

    @model_validator(mode="after")
    def bind_reported_model(self) -> "EmbeddingFormat":
        if self.reported_model is not None and self.provider_slug != "deepinfra/us":
            raise ValueError("Embedding model identifier requires its verified provider route.")
        return self

    def format(self, text: str, role: Literal["query", "document"]) -> str:
        if not self.verified:
            raise ProviderError("embedding_format_unverified")
        # The caller supplies original text; apply the explicit profile exactly once.
        return (self.query_prefix if role == "query" else self.document_prefix) + text


class ChatProvider(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        max_output_tokens: int,
        budget: "ExecutionBudget",
    ) -> StructuredResult[T]: ...


class EmbeddingProvider(Protocol):
    async def embed(
        self,
        texts: Sequence[str],
        *,
        role: Literal["query", "document"],
        format: EmbeddingFormat,
        budget: "ExecutionBudget",
    ) -> EmbeddingResult: ...


# Avoid a runtime import cycle while retaining the protocol annotations.
if TYPE_CHECKING:
    from telescope_rag.providers.budget import ExecutionBudget
