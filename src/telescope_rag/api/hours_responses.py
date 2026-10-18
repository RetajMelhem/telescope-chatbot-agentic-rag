"""Versioned offline hours output; normalized records stay separate from source quotations."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from telescope_rag.api.responses import OfflineChatResponse, ResponseQuestion, ResponseRecord
from telescope_rag.knowledge.hours import HoursReason, HoursSubject, PublishedHours
from telescope_rag.knowledge.public_links import WebsiteLink


class ResponseWebsiteLink(WebsiteLink):
    question_id: str


class ResponseHours(ResponseRecord):
    intent: Literal["schedule", "now", "local"]
    subject: HoursSubject | None
    status: Literal[
        "schedule_available",
        "within_posted_hours",
        "outside_posted_hours",
        "unknown",
        "clarification_required",
    ]
    reason: HoursReason | Literal["scope_incomplete"]
    timezone: Literal["Asia/Amman"] = "Asia/Amman"
    evaluated_at: datetime
    local_candidates: tuple[datetime, ...] = Field(max_length=2)
    clock_ambiguous: bool
    dated_exception_applied: bool
    dated_exceptions_unverified: bool
    schedules: tuple[PublishedHours, ...] = Field(max_length=1000, repr=False)
    basis: Literal["published_schedule_only"] = "published_schedule_only"
    query_interpretation_verified: Literal[False] = False
    actual_attendance_verified: Literal[False] = False


class HoursResponseQuestion(ResponseQuestion):
    hours: ResponseHours | None
    website_link_ids: tuple[str, ...] = ()


class HoursChatResponse(OfflineChatResponse):
    schema_version: Literal["offline-hours-response-v1"] = "offline-hours-response-v1"
    questions: tuple[HoursResponseQuestion, ...] = Field(min_length=1, max_length=4, repr=False)
    website_links: tuple[ResponseWebsiteLink, ...] = Field(default=(), max_length=32)
    website_links_digest: str | None = None
