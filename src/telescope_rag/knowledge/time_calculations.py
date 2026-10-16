"""Pure posted-hours comparisons on an explicitly supplied reviewed source plan."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from telescope_rag.knowledge.hours import (
    DayHours,
    HoursAssessment,
    HoursDecision,
    HoursQuery,
    HoursSubject,
    PublicHoursPlan,
    PublishedHours,
    hours_plan_digest,
    hours_source_digest,
)
from telescope_rag.retrieval.assembly import EvidenceCatalog

_ZONE = ZoneInfo("Asia/Amman")
_DAY = timedelta(days=1)


def _subject_key(subject: HoursSubject) -> tuple[str, str, str]:
    return subject.kind, subject.id, subject.owner_kind


def _wall_instants(wall: datetime) -> tuple[datetime, ...]:
    # Round trips reject nonexistent wall times. UTC keys distinguish the two
    # occurrences of a historical repeated wall time without guessing its fold.
    values = {}
    for fold in (0, 1):
        value = wall.replace(tzinfo=_ZONE, fold=fold)
        utc = value.astimezone(UTC)
        if utc.astimezone(_ZONE).replace(tzinfo=None) == wall:
            values[utc] = value
    return tuple(values[k] for k in sorted(values))


def _rule(record: PublishedHours, day: date) -> tuple[DayHours | None, bool]:
    dated = next((r for r in record.exceptions if r.on_date == day), None)
    return (
        (dated, True)
        if dated is not None
        else (next((r for r in record.weekly if r.weekday == day.weekday()), None), False)
    )


def _contains(rule: DayHours, day: date, at: datetime, *, carry_only: bool = False) -> bool | None:
    found = False
    for interval in rule.intervals:
        if carry_only and interval.closes <= 1440:
            continue
        try:
            midnight = datetime.combine(day, datetime.min.time())
            starts = _wall_instants(midnight + timedelta(minutes=interval.opens))
            ends = _wall_instants(midnight + timedelta(minutes=interval.closes))
        except (OverflowError, ValueError):
            return None
        if len(starts) != 1 or len(ends) != 1:
            return None
        found |= starts[0].astimezone(UTC) <= at.astimezone(UTC) < ends[0].astimezone(UTC)
    return found


def _record_at(record: PublishedHours, at: datetime) -> tuple[str, str, bool]:
    day = at.date()
    if (record.valid_from and day < record.valid_from) or (
        record.valid_through and day > record.valid_through
    ):
        return "unknown", "outside_effective_dates", False
    if record.conditional:
        return "unknown", "conditional_hours", False
    today, dated = _rule(record, day)
    # A dated rule explicitly replaces this calendar date, including any
    # previous weekly spillover. No dated rule is inferred from a holiday name.
    if dated:
        inside = _contains(today, day, at)
        if inside is None:
            return "unknown", "timezone_boundary_unresolved", True
        return (
            ("within_posted_hours" if inside else "outside_posted_hours"),
            "published_schedule",
            True,
        )
    yesterday = None
    try:
        yesterday, _ = _rule(record, day - _DAY)
        carry = _contains(yesterday, day - _DAY, at, carry_only=True) if yesterday else None
    except OverflowError:
        carry = None
    inside = _contains(today, day, at) if today is not None else None
    if inside is None and today is not None or carry is None and yesterday is not None:
        return "unknown", "timezone_boundary_unresolved", False
    if carry and today is not None and today.state == "closed":
        return "unknown", "conflicting_hours", False
    if inside or carry:
        return "within_posted_hours", "published_schedule", False
    if today is not None and today.state == "closed":
        return "outside_posted_hours", "published_schedule", False
    if today is None or yesterday is None:
        return "unknown", "missing_hours", False
    return "outside_posted_hours", "published_schedule", False


class PublicHoursCatalog:
    """Bind a reviewed mapping to exact source bytes; not a source-semantic verifier.

    The trusted caller authenticates the plan digest and review authority. This
    class cannot prove that source prose entails an authored normalized schedule.
    No default plan/client, free-text interpretation, provider or I/O is present.
    """

    def __init__(
        self,
        *,
        plan: PublicHoursPlan,
        catalog: EvidenceCatalog,
        expected_plan_digest: str,
        max_source_age: timedelta,
    ) -> None:
        plan = PublicHoursPlan.model_validate_json(plan.model_dump_json())
        if (
            hours_plan_digest(plan) != expected_plan_digest
            or plan.prepared_digest != catalog.prepared_digest
            or type(max_source_age) is not timedelta
            or max_source_age <= timedelta(0)
            or len({r.record_id for r in plan.schedules}) != len(plan.schedules)
        ):
            raise ValueError("hours_plan_binding_invalid")
        for record in plan.schedules:
            for reference in record.evidence:
                chunk = catalog.chunks.get(reference.chunk_id)
                if chunk is None or hours_source_digest(chunk) != reference.chunk_digest:
                    raise ValueError("hours_source_binding_invalid")
                owner = (
                    chunk.doctor_id
                    if record.subject.owner_kind == "literal"
                    else chunk.canonical_doctor_id
                )
                if (
                    chunk.snapshot_id != plan.snapshot_id
                    or chunk.fetched_at.utcoffset() is None
                    or (record.subject.kind == "doctor" and owner != record.subject.id)
                    or (
                        record.subject.kind != "doctor"
                        and (chunk.doctor_id is not None or chunk.canonical_doctor_id is not None)
                    )
                    or chunk.source_issue_codes
                ):
                    raise ValueError("hours_source_owner_or_scope_invalid")
        self._plan, self._catalog, self._max_age = plan, catalog, max_source_age

    def evaluate(self, query: HoursQuery, *, now: datetime) -> HoursAssessment:
        if type(query) is not HoursQuery or type(now) is not datetime or now.utcoffset() is None:
            raise ValueError("hours_evaluation_input_invalid")
        query = HoursQuery.model_validate_json(query.model_dump_json())
        now = now.astimezone(UTC)
        records = tuple(
            r
            for r in self._plan.schedules
            if query.subject is not None and _subject_key(r.subject) == _subject_key(query.subject)
        )
        ids = tuple(dict.fromkeys(e.chunk_id for r in records for e in r.evidence))
        sources = tuple(self._catalog.chunks[i] for i in ids)
        candidates, ambiguous = (), query.mode == "local" and query.clock_basis == "unspecified"
        audit = []

        def result(status, reason, *, dated=False):
            return HoursAssessment(
                subject=query.subject,
                status=status,
                reason=reason,
                evaluated_at=now,
                local_candidates=candidates,
                clock_ambiguous=ambiguous,
                dated_exception_applied=dated,
                dated_exceptions_unverified=not dated,
                record_ids=tuple(r.record_id for r in records),
                evidence=sources,
                decisions=tuple(audit),
            )

        if query.subject is None:
            return result("clarification_required", "ambiguous_subject")
        if query.mode == "now":
            candidates = (now.astimezone(_ZONE),)
        elif query.mode == "instant":
            candidates = (query.instant.astimezone(UTC).astimezone(_ZONE),)
        else:
            if query.local_date is None:
                return result("clarification_required", "missing_date")
            hours = (
                (query.hour,)
                if query.clock_basis == "24h"
                else (
                    (query.hour % 12,)
                    if query.clock_basis == "am"
                    else (query.hour % 12 + 12,)
                    if query.clock_basis == "pm"
                    else (query.hour % 12, query.hour % 12 + 12)
                )
            )
            times = []
            for hour in hours:
                values = _wall_instants(
                    datetime.combine(query.local_date, datetime.min.time()).replace(
                        hour=hour, minute=query.minute
                    )
                )
                if len(values) != 1:
                    return result(
                        "clarification_required",
                        "nonexistent_local_time" if not values else "ambiguous_local_time",
                    )
                times.extend(values)
            candidates = tuple(times)
        if not records:
            return result("unknown", "missing_hours")
        outcomes = []
        for at in candidates:
            decisions = []
            for record in records:
                citations = tuple(self._catalog.chunks[e.chunk_id] for e in record.evidence)
                reason = (
                    "source_from_future"
                    if any(c.fetched_at > now for c in citations)
                    else "stale_hours"
                    if any(now - c.fetched_at > self._max_age for c in citations)
                    else "historical_hours_unverified"
                    if record.valid_from is None
                    and not any(r.on_date == at.date() for r in record.exceptions)
                    and any(at.astimezone(UTC) < c.fetched_at for c in citations)
                    else None
                )
                decision = ("unknown", reason, False) if reason else _record_at(record, at)
                decisions.append(decision)
                audit.append(
                    HoursDecision(
                        record_id=record.record_id,
                        at=at,
                        status=decision[0],
                        reason=decision[1],
                        dated_exception_applied=decision[2],
                    )
                )
            statuses = {d[0] for d in decisions}
            if {"within_posted_hours", "outside_posted_hours"} <= statuses:
                outcomes.append(("unknown", "conflicting_hours", False))
            elif "unknown" in statuses:
                outcomes.append(next(d for d in decisions if d[0] == "unknown"))
            else:
                outcomes.append(
                    (decisions[0][0], "published_schedule", all(d[2] for d in decisions))
                )
        if len({d[0] for d in outcomes}) > 1:
            return result("clarification_required", "ambiguous_time")
        return result(outcomes[0][0], outcomes[0][1], dated=all(d[2] for d in outcomes))
