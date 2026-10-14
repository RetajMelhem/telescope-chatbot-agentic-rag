"""Transport input cannot provide tools, prompts, or runtime configuration."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=4000)
    language: Literal["auto", "ar", "en"] = "auto"
    history: list[HistoryMessage] = Field(default_factory=list, max_length=6)

    @field_validator("query")
    @classmethod
    def require_nonblank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The question must contain text.")
        return value

    @model_validator(mode="after")
    def bound_history(self) -> Self:
        if sum(len(message.content) for message in self.history) > 8000:
            raise ValueError("Conversation history exceeds the allowed size.")
        return self


class HealthResponse(BaseModel):
    request_id: str
    status: Literal["live", "ready"]
