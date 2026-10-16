"""Closed opt-in planner inputs and request-owned computation receipts."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, model_validator

from telescope_rag.knowledge.hours import (
    HoursAssessment,
    HoursQuery,
    HoursRecord,
    PublishedHours,
)
from telescope_rag.retrieval.assembly import SourceScope


class HoursFieldQuote(HoursRecord):
    quote: str = Field(min_length=1, max_length=512, repr=False)
    origin: Literal["part", "query_reference", "history"]
    history_index: int | None = Field(ge=0, le=5)


class HoursInput(HoursRecord):
    intent: Literal["schedule", "now", "local"]
    subject_handle: str | None = Field(max_length=64)
    subject_quote: HoursFieldQuote | None
    date_value: str | None = Field(max_length=10)
    date_quote: HoursFieldQuote | None
    hour: int | None = Field(ge=0, le=23)
    minute: int | None = Field(ge=0, le=59)
    clock_basis: Literal["24h", "am", "pm", "unspecified"] | None
    time_quote: HoursFieldQuote | None

    @model_validator(mode="after")
    def shape(self):
        if (
            (self.subject_handle is not None and self.subject_quote is None)
            or (
                self.intent == "schedule"
                and any(
                    v is not None
                    for v in (
                        self.date_value,
                        self.date_quote,
                        self.hour,
                        self.minute,
                        self.clock_basis,
                        self.time_quote,
                    )
                )
            )
            or (
                self.intent == "now"
                and (
                    self.time_quote is None
                    or any(
                        v is not None
                        for v in (
                            self.date_value,
                            self.date_quote,
                            self.hour,
                            self.minute,
                            self.clock_basis,
                        )
                    )
                )
            )
            or (
                self.intent == "local"
                and (
                    self.hour is None
                    or self.minute is None
                    or self.clock_basis is None
                    or self.time_quote is None
                    or (self.date_value is not None and self.date_quote is None)
                )
            )
        ):
            raise ValueError("hours_input_shape_invalid")
        return self


@dataclass(frozen=True)
class HoursFieldBinding:
    name: str
    origin: str
    history_index: int | None
    start: int
    end: int
    quote: str = field(repr=False)


@dataclass(frozen=True)
class ComputedHours:
    part_id: str
    supplied: HoursInput = field(repr=False)
    scope: SourceScope
    query: HoursQuery = field(repr=False)
    field_bindings: tuple[HoursFieldBinding, ...] = field(repr=False)
    schedules: tuple[PublishedHours, ...] = field(repr=False)
    assessment: HoursAssessment = field(repr=False)
