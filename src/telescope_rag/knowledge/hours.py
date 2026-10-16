"""Reviewed hours mappings and typed time requests; no text parser or serving adoption."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telescope_rag.ingestion.models import PreparedChunk, stable_id


class HoursRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class HoursSubject(HoursRecord):
    kind: Literal["clinic", "optical_center", "pharmacy", "doctor"]
    id: str = Field(min_length=1, max_length=256)
    owner_kind: Literal["literal", "canonical"] = "literal"

    @model_validator(mode="after")
    def owner_scope(self):
        if self.kind != "doctor" and self.owner_kind != "literal":
            raise ValueError("hours_subject_invalid")
        return self


class HoursInterval(HoursRecord):
    # Offsets from the named day's midnight. 1440 is its ending midnight;
    # larger closing offsets explicitly represent an overnight interval.
    opens: int = Field(ge=0, lt=1440)
    closes: int = Field(gt=0, lt=2880)

    @model_validator(mode="after")
    def ordered(self):
        if not self.opens < self.closes <= self.opens + 1440:
            raise ValueError("hours_interval_invalid")
        return self


class DayHours(HoursRecord):
    state: Literal["intervals", "closed"]
    intervals: tuple[HoursInterval, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def valid_intervals(self):
        if (self.state == "closed") != (not self.intervals) or any(
            b.opens < a.closes for a, b in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("hours_day_invalid")
        return self


class WeeklyHours(DayHours):
    weekday: int = Field(ge=0, le=6)


class DatedHours(DayHours):
    on_date: date


class HoursEvidence(HoursRecord):
    chunk_id: str = Field(min_length=1)
    chunk_digest: str = Field(min_length=64, max_length=64)


def hours_source_digest(chunk: PreparedChunk) -> str:
    return stable_id("public-hours-source-v1", chunk.model_dump_json())


class PublishedHours(HoursRecord):
    record_id: str = Field(min_length=1, max_length=256)
    subject: HoursSubject
    timezone: Literal["Asia/Amman"] = "Asia/Amman"
    weekly: tuple[WeeklyHours, ...] = Field(default=(), max_length=7)
    exceptions: tuple[DatedHours, ...] = Field(default=(), max_length=366)
    evidence: tuple[HoursEvidence, ...] = Field(min_length=1, max_length=16, repr=False)
    conditional: bool = False
    valid_from: date | None = None
    valid_through: date | None = None

    @model_validator(mode="after")
    def unique_rules(self):
        if (
            not (self.weekly or self.exceptions)
            or len({r.weekday for r in self.weekly}) != len(self.weekly)
            or len({r.on_date for r in self.exceptions}) != len(self.exceptions)
            or len({e.chunk_id for e in self.evidence}) != len(self.evidence)
            or (self.valid_from and self.valid_through and self.valid_from > self.valid_through)
        ):
            raise ValueError("hours_record_invalid")
        return self


class PublicHoursPlan(HoursRecord):
    version: Literal["public-hours-plan-v1"] = "public-hours-plan-v1"
    prepared_digest: str
    snapshot_id: str
    schedules: tuple[PublishedHours, ...] = Field(min_length=1, max_length=1000, repr=False)
    review_note: str = Field(min_length=1, repr=False)
    offline_only: Literal[True] = True


def hours_plan_digest(plan: PublicHoursPlan) -> str:
    return stable_id("public-hours-plan-v1", plan.model_dump_json())


class HoursQuery(HoursRecord):
    # All interpretation must be supplied by a separately validated caller.
    # No question text, fuzzy names, relative dates or availability are accepted.
    subject: HoursSubject | None
    mode: Literal["now", "instant", "local"]
    instant: datetime | None = None
    local_date: date | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    clock_basis: Literal["24h", "am", "pm", "unspecified"] | None = None

    @model_validator(mode="after")
    def exact_shape(self):
        local_fields = self.local_date is not None or self.hour is not None or self.clock_basis
        if (
            (self.mode == "now" and (self.instant is not None or local_fields or self.minute))
            or (
                self.mode == "instant"
                and (
                    self.instant is None
                    or self.instant.utcoffset() is None
                    or local_fields
                    or self.minute
                )
            )
            or (
                self.mode == "local"
                and (
                    self.instant is not None
                    or self.hour is None
                    or self.clock_basis is None
                    or (self.clock_basis != "24h" and not 1 <= self.hour <= 12)
                )
            )
        ):
            raise ValueError("hours_query_invalid")
        return self


HoursStatus = Literal[
    "within_posted_hours", "outside_posted_hours", "unknown", "clarification_required"
]
HoursReason = Literal[
    "published_schedule",
    "missing_hours",
    "conflicting_hours",
    "stale_hours",
    "source_from_future",
    "conditional_hours",
    "outside_effective_dates",
    "historical_hours_unverified",
    "timezone_boundary_unresolved",
    "ambiguous_subject",
    "missing_date",
    "ambiguous_time",
    "nonexistent_local_time",
    "ambiguous_local_time",
]


class HoursDecision(HoursRecord):
    record_id: str
    at: datetime
    status: HoursStatus
    reason: HoursReason
    dated_exception_applied: bool


class HoursAssessment(HoursRecord):
    subject: HoursSubject | None
    status: HoursStatus
    reason: HoursReason
    evaluated_at: datetime
    local_candidates: tuple[datetime, ...] = Field(max_length=2)
    clock_ambiguous: bool
    dated_exception_applied: bool
    dated_exceptions_unverified: bool
    record_ids: tuple[str, ...]
    evidence: tuple[PreparedChunk, ...] = Field(repr=False)
    decisions: tuple[HoursDecision, ...] = Field(max_length=2000, repr=False)
    basis: Literal["published_schedule_only"] = "published_schedule_only"
    query_interpretation_verified: Literal[False] = False
    actual_attendance_verified: Literal[False] = False
    offline_only: Literal[True] = True
