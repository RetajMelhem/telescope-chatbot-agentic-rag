"""Typed numerical/source-binding checks, not automated semantic extraction of schedules."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from test_offline_workflow import catalog, source

from telescope_rag.knowledge.hours import (
    DatedHours,
    HoursEvidence,
    HoursInterval,
    HoursQuery,
    HoursSubject,
    PublicHoursPlan,
    PublishedHours,
    WeeklyHours,
    hours_plan_digest,
    hours_source_digest,
)
from telescope_rag.knowledge.time_calculations import PublicHoursCatalog

ZONE = ZoneInfo("Asia/Amman")
NOW = datetime(2026, 10, 17, tzinfo=UTC)
CLINIC = HoursSubject(kind="clinic", id="synthetic-center")
PHARMACY = HoursSubject(kind="pharmacy", id="synthetic-pharmacy")


def reference(chunk):
    return HoursEvidence(chunk_id=chunk.chunk_id, chunk_digest=hours_source_digest(chunk))


def rules(*, always=False, hours=None):
    return tuple(
        WeeklyHours(
            weekday=day,
            state="intervals",
            intervals=tuple(
                HoursInterval(opens=a, closes=b)
                for a, b in (
                    hours
                    if hours is not None
                    else ((0, 1440),)
                    if always
                    else ((840 if day == 4 else 540, 1440),)
                )
            ),
        )
        for day in range(7)
    )


def fixture(*, subject=CLINIC, weekly=None, exceptions=(), changes=None, item=None):
    item = item or source(1, "Synthetic posted hours; reservations are recommended.").model_copy(
        update={"fetched_at": datetime(2026, 10, 14, tzinfo=UTC)}
    )
    record = PublishedHours(
        record_id="synthetic-reviewed",
        subject=subject,
        weekly=rules(always=subject == PHARMACY) if weekly is None else weekly,
        exceptions=exceptions,
        evidence=(reference(item),),
        **(changes or {}),
    )
    engine, plan, evidence = bind((record,), (item,))
    return engine, plan, evidence, item


def bind(records, items):
    evidence = catalog(*items)
    plan = PublicHoursPlan(
        prepared_digest=evidence.prepared_digest,
        snapshot_id=items[0].snapshot_id,
        schedules=records,
        review_note="Explicit synthetic mapping for numerical tests; not production knowledge.",
    )
    engine = PublicHoursCatalog(
        plan=plan,
        catalog=evidence,
        expected_plan_digest=hours_plan_digest(plan),
        max_source_age=timedelta(hours=168),
    )
    return engine, plan, evidence


def local(engine, hour, minute=0, *, day=date(2026, 10, 16), subject=CLINIC, basis="24h", now=NOW):
    return engine.evaluate(
        HoursQuery(
            subject=subject,
            mode="local",
            local_date=day,
            hour=hour,
            minute=minute,
            clock_basis=basis,
        ),
        now=now,
    )


@pytest.mark.parametrize("weekday", range(7))
def test_all_weekday_opening_closing_and_midnight_boundaries(weekday):
    engine, _, _, item = fixture()
    day = date(2026, 10, 19) + timedelta(days=weekday)
    opening = 14 if weekday == 4 else 9
    for hour, minute, expected in (
        (opening - 1, 59, "outside_posted_hours"),
        (opening, 0, "within_posted_hours"),
        (23, 59, "within_posted_hours"),
    ):
        answer = local(engine, hour, minute, day=day)
        assert answer.status == expected
        assert answer.evidence == (item,) and answer.dated_exceptions_unverified
        assert not answer.actual_attendance_verified and not answer.query_interpretation_verified
    assert local(engine, 0, day=day + timedelta(days=1)).status == "outside_posted_hours"


def test_complete_minute_grid_matches_independent_published_weekly_fixture():
    engine, *_ = fixture()
    checked = 0
    for weekday in range(7):
        day = date(2026, 10, 19) + timedelta(days=weekday)
        opening = 840 if weekday == 4 else 540
        for minute in range(1440):
            answer = local(engine, minute // 60, minute % 60, day=day)
            expected = "within_posted_hours" if minute >= opening else "outside_posted_hours"
            assert answer.status == expected, (weekday, minute, answer.reason)
            checked += 1
    assert checked == 10080


@pytest.mark.parametrize("hour", [0, 7, 12, 19, 23])
def test_pharmacy_is_separate_and_24_hours_does_not_inherit_center_closures(hour):
    engine, *_ = fixture(subject=PHARMACY)
    assert local(engine, hour, subject=PHARMACY).status == "within_posted_hours"
    assert local(engine, hour, subject=CLINIC).reason == "missing_hours"


@pytest.mark.parametrize(
    "hour,basis,expected",
    [
        (7, "unspecified", "clarification_required"),
        (12, "unspecified", "outside_posted_hours"),
        (7, "am", "outside_posted_hours"),
        (7, "pm", "within_posted_hours"),
        (12, "am", "outside_posted_hours"),
        (12, "pm", "outside_posted_hours"),
        (19, "24h", "within_posted_hours"),
    ],
)
def test_am_pm_is_never_guessed_and_noon_midnight_remain_distinct(hour, basis, expected):
    engine, *_ = fixture()
    answer = local(engine, hour, basis=basis)
    assert answer.status == expected
    if basis == "unspecified":
        assert answer.clock_ambiguous and len(answer.local_candidates) == 2
        assert answer.reason == (
            "ambiguous_time" if expected == "clarification_required" else "published_schedule"
        )
        assert len(answer.decisions) == 2


def test_ambiguous_time_with_equal_outcomes_retains_both_interpretations():
    engine, *_ = fixture(subject=PHARMACY)
    answer = local(engine, 7, subject=PHARMACY, basis="unspecified")
    assert answer.status == "within_posted_hours" and answer.clock_ambiguous
    assert len(answer.local_candidates) == len(answer.decisions) == 2


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"subject": None}, "ambiguous_subject"),
        ({"local_date": None}, "missing_date"),
        ({"subject": HoursSubject(kind="doctor", id="synthetic-center")}, "missing_hours"),
    ],
)
def test_ambiguous_subject_date_and_absent_doctor_hours_stay_explicit(changes, reason):
    engine, *_ = fixture()
    query = HoursQuery(
        subject=CLINIC, mode="local", local_date=date(2026, 10, 16), hour=19, clock_basis="24h"
    )
    answer = engine.evaluate(query.model_copy(update=changes), now=NOW)
    assert answer.reason == reason
    assert answer.status == ("unknown" if reason == "missing_hours" else "clarification_required")
    if reason == "missing_hours":
        assert not answer.evidence


def test_server_clock_now_and_explicit_utc_instant_are_identical():
    engine, *_ = fixture()
    now = datetime(2026, 10, 16, 16, 0, tzinfo=UTC)
    a = engine.evaluate(HoursQuery(subject=CLINIC, mode="now"), now=now)
    b = engine.evaluate(HoursQuery(subject=CLINIC, mode="instant", instant=now), now=now)
    assert a == b and a.local_candidates[0].hour == 19 and a.status == "within_posted_hours"


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (8, 59, False),
        (9, 0, True),
        (11, 59, True),
        (12, 0, False),
        (13, 59, False),
        (14, 0, True),
        (17, 0, False),
    ],
)
def test_split_shifts_preserve_lunch_gap_and_half_open_ends(hour, minute, expected):
    engine, *_ = fixture(weekly=rules(hours=((540, 720), (840, 1020))))
    assert (local(engine, hour, minute).status == "within_posted_hours") == expected


@pytest.mark.parametrize(
    "day,hour,minute,expected",
    [
        (15, 21, 59, False),
        (15, 22, 0, True),
        (16, 0, 0, True),
        (16, 1, 59, True),
        (16, 2, 0, False),
    ],
)
def test_overnight_thursday_carry_and_exact_friday_close(day, hour, minute, expected):
    weekly = list(rules(hours=((540, 1020),)))
    weekly[3] = WeeklyHours(
        weekday=3, state="intervals", intervals=(HoursInterval(opens=1320, closes=1560),)
    )
    engine, *_ = fixture(weekly=tuple(weekly))
    assert (
        local(engine, hour, minute, day=date(2026, 10, day)).status == "within_posted_hours"
    ) == expected


@pytest.mark.parametrize(
    "closed,hour,expected",
    [
        (True, 1, "outside_posted_hours"),
        (True, 19, "outside_posted_hours"),
        (False, 1, "outside_posted_hours"),
        (False, 10, "within_posted_hours"),
        (False, 12, "outside_posted_hours"),
    ],
)
def test_explicit_calendar_exception_overrides_weekly_and_previous_night(closed, hour, expected):
    weekly = rules(hours=((1320, 1560),))
    exception = DatedHours(
        on_date=date(2026, 10, 16),
        state="closed" if closed else "intervals",
        intervals=() if closed else (HoursInterval(opens=600, closes=720),),
    )
    engine, *_ = fixture(weekly=weekly, exceptions=(exception,))
    answer = local(engine, hour)
    assert answer.status == expected and answer.dated_exception_applied
    assert not answer.dated_exceptions_unverified


def test_missing_weekday_does_not_mean_closed_and_explicit_closed_day_is_required():
    engine, *_ = fixture(
        weekly=(
            WeeklyHours(
                weekday=3, state="intervals", intervals=(HoursInterval(opens=540, closes=1020),)
            ),
        )
    )
    assert local(engine, 10).reason == "missing_hours"
    engine, *_ = fixture(weekly=(WeeklyHours(weekday=4, state="closed"),))
    assert local(engine, 10).status == "outside_posted_hours"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"conditional": True}, "conditional_hours"),
        ({"valid_from": date(2026, 10, 20)}, "outside_effective_dates"),
        ({"valid_through": date(2026, 10, 15)}, "outside_effective_dates"),
    ],
)
def test_source_conditions_and_effective_dates_are_not_dropped(changes, reason):
    engine, *_ = fixture(changes=changes)
    answer = local(engine, 19)
    assert answer.status == "unknown" and answer.reason == reason and answer.evidence


@pytest.mark.parametrize(
    "age,expected",
    [
        (timedelta(hours=168), "within_posted_hours"),
        (timedelta(hours=168, microseconds=1), "unknown"),
        (timedelta(seconds=-1), "unknown"),
    ],
)
def test_source_age_exact_boundary_and_future_fetch_are_explicit(age, expected):
    item = source(1).model_copy(update={"fetched_at": NOW - age})
    engine, *_ = fixture(item=item)
    answer = local(engine, 19, day=date(2026, 10, 18))
    assert answer.status == expected
    if expected == "unknown":
        assert answer.reason == ("source_from_future" if age < timedelta(0) else "stale_hours")


def test_a_recent_undated_publication_does_not_establish_historical_hours():
    engine, *_ = fixture()
    assert local(engine, 19, day=date(2026, 10, 10)).reason == "historical_hours_unverified"
    dated = DatedHours(on_date=date(2026, 10, 10), state="closed")
    engine, *_ = fixture(exceptions=(dated,))
    assert local(engine, 19, day=date(2026, 10, 10)).status == "outside_posted_hours"


@pytest.mark.parametrize(
    "day,reason",
    [(date(2021, 3, 26), "nonexistent_local_time"), (date(2021, 10, 29), "ambiguous_local_time")],
)
def test_historical_timezone_gap_and_fold_are_not_silently_shifted(day, reason):
    item = source(1).model_copy(
        update={"fetched_at": datetime.combine(day - timedelta(days=1), datetime.min.time(), UTC)}
    )
    engine, *_ = fixture(item=item)
    answer = local(
        engine,
        0,
        30,
        day=day,
        now=datetime.combine(day, datetime.min.time(), UTC) + timedelta(days=1),
    )
    assert answer.status == "clarification_required" and answer.reason == reason


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"mode": "now", "hour": 7},
        {"mode": "instant", "instant": datetime(2026, 10, 16)},
        {"mode": "local", "hour": 0, "clock_basis": "am"},
        {"mode": "local", "hour": 24, "clock_basis": "24h"},
        {"mode": "local", "hour": 7, "clock_basis": "24h", "minute": 60},
        {"mode": "now", "availability": True},
        {"mode": "local", "hour": "7", "clock_basis": "24h"},
    ],
)
def test_invalid_untyped_and_private_operation_inputs_are_refused(bad):
    with pytest.raises(ValidationError):
        HoursQuery(subject=CLINIC, **bad)


@pytest.mark.parametrize("values", [(5, 5), (10, 9), (-1, 10), (0, 1441), (1440, 1500), (True, 10)])
def test_invalid_interval_bounds_do_not_become_repaired_hours(values):
    with pytest.raises(ValidationError):
        HoursInterval(opens=values[0], closes=values[1])


@pytest.mark.parametrize("conflict", [False, True])
def test_separate_source_claims_are_preserved_and_disagreement_is_not_voted_away(conflict):
    _, plan, _, a = fixture()
    b = source(2, "Synthetic independent language claim.").model_copy(
        update={"fetched_at": a.fetched_at, "language": "ar"}
    )
    second = plan.schedules[0].model_copy(
        update={
            "record_id": "independent-ar-claim",
            "evidence": (reference(b),),
            "weekly": rules(hours=((0, 60),)) if conflict else rules(),
        }
    )
    engine, _, _ = bind((plan.schedules[0], second), (a, b))
    answer = local(engine, 19)
    assert answer.status == ("unknown" if conflict else "within_posted_hours")
    assert answer.reason == ("conflicting_hours" if conflict else "published_schedule")
    assert answer.evidence == (a, b) and len(answer.record_ids) == 2
    assert len(answer.decisions) == 2


def test_two_same_field_doctors_and_canonical_identities_remain_independent():
    items = tuple(
        source(
            i,
            "Synthetic same specialty.",
            doctor_id=who,
            doctor_name=f"Synthetic {who}",
            canonical_doctor_id=f"canonical-{who}",
        ).model_copy(
            update={"block_type": "doctor", "fetched_at": datetime(2026, 10, 14, tzinfo=UTC)}
        )
        for i, who in enumerate(("a", "b"), 1)
    )
    records = tuple(
        PublishedHours(
            record_id=f"doctor-{who}",
            subject=HoursSubject(kind="doctor", id=f"canonical-{who}", owner_kind="canonical"),
            weekly=rules(hours=((540, 720),) if who == "a" else ((840, 1080),)),
            evidence=(reference(item),),
        )
        for who, item in zip(("a", "b"), items, strict=True)
    )
    engine, _, _ = bind(records, items)
    answers = [local(engine, 10, subject=r.subject) for r in records]
    assert [a.status for a in answers] == ["within_posted_hours", "outside_posted_hours"]
    assert [a.evidence for a in answers] == [(items[0],), (items[1],)]
    assert local(engine, 10, subject=HoursSubject(kind="doctor", id="a")).reason == "missing_hours"
    assert local(engine, 10, subject=HoursSubject(kind="doctor", id="A")).reason == "missing_hours"


@pytest.mark.parametrize(
    "fault",
    [
        "plan_digest",
        "prepared_digest",
        "snapshot",
        "chunk_digest",
        "missing_chunk",
        "duplicate_record",
        "doctor_owner",
        "doctor_to_center",
        "canonical_doctor_to_center",
        "source_caveat",
        "age",
    ],
)
def test_exact_plan_source_and_owner_bindings_fail_before_any_calculation(fault):
    _, plan, evidence, item = fixture()
    record = plan.schedules[0]
    options = {
        "plan": plan,
        "catalog": evidence,
        "expected_plan_digest": hours_plan_digest(plan),
        "max_source_age": timedelta(hours=168),
    }
    if fault == "plan_digest":
        options["expected_plan_digest"] = "wrong"
    elif fault == "age":
        options["max_source_age"] = timedelta(0)
    elif fault in {"prepared_digest", "snapshot"}:
        plan = plan.model_copy(
            update={"prepared_digest" if fault == "prepared_digest" else "snapshot_id": "wrong"}
        )
    elif fault == "duplicate_record":
        plan = plan.model_copy(update={"schedules": (record, record)})
    elif fault in {"chunk_digest", "missing_chunk"}:
        ref = record.evidence[0].model_copy(
            update={"chunk_digest": "0" * 64}
            if fault == "chunk_digest"
            else {"chunk_id": "missing"}
        )
        plan = plan.model_copy(
            update={"schedules": (record.model_copy(update={"evidence": (ref,)}),)}
        )
    elif fault == "doctor_owner":
        plan = plan.model_copy(
            update={
                "schedules": (
                    record.model_copy(
                        update={"subject": HoursSubject(kind="doctor", id="missing")}
                    ),
                )
            }
        )
    else:
        item = item.model_copy(
            update={"doctor_id": "a", "doctor_name": "Synthetic A"}
            if fault == "doctor_to_center"
            else {"canonical_doctor_id": "canonical-a"}
            if fault == "canonical_doctor_to_center"
            else {"source_issue_codes": ("unverified",)}
        )
        evidence = catalog(item)
        record = record.model_copy(update={"evidence": (reference(item),)})
        plan = plan.model_copy(
            update={"prepared_digest": evidence.prepared_digest, "schedules": (record,)}
        )
        options["catalog"] = evidence
    if fault not in {"plan_digest", "age"}:
        options.update(plan=plan, expected_plan_digest=hours_plan_digest(plan))
    with pytest.raises(ValueError, match="hours_"):
        PublicHoursCatalog(**options)


@pytest.mark.parametrize(
    "fault",
    [
        "closed_with_times",
        "empty_open",
        "overlap",
        "unsorted",
        "duplicate_weekday",
        "duplicate_exception",
    ],
)
def test_malformed_day_and_record_shapes_are_not_silently_sorted_or_merged(fault):
    _, plan, _, _ = fixture()
    record = plan.schedules[0]
    with pytest.raises(ValidationError):
        if fault in {"closed_with_times", "empty_open"}:
            WeeklyHours(
                weekday=4,
                state="closed" if fault == "closed_with_times" else "intervals",
                intervals=(HoursInterval(opens=540, closes=1020),)
                if fault == "closed_with_times"
                else (),
            )
        elif fault in {"overlap", "unsorted"}:
            intervals = (
                ((540, 800), (700, 900)) if fault == "overlap" else ((840, 1020), (540, 720))
            )
            WeeklyHours(
                weekday=4,
                state="intervals",
                intervals=tuple(HoursInterval(opens=a, closes=b) for a, b in intervals),
            )
        else:
            changed = record.model_copy(
                update={"weekly": (record.weekly[0],) * 2}
                if fault == "duplicate_weekday"
                else {"exceptions": (DatedHours(on_date=date(2026, 10, 16), state="closed"),) * 2}
            )
            PublishedHours.model_validate_json(changed.model_dump_json())


def test_overnight_carry_can_support_a_missing_current_day_but_not_invent_its_closed_hours():
    engine, *_ = fixture(
        weekly=(
            WeeklyHours(
                weekday=3, state="intervals", intervals=(HoursInterval(opens=1320, closes=1560),)
            ),
        )
    )
    assert local(engine, 1).status == "within_posted_hours"
    assert local(engine, 2).reason == "missing_hours"
    conflicting = (
        WeeklyHours(
            weekday=3, state="intervals", intervals=(HoursInterval(opens=1320, closes=1560),)
        ),
        WeeklyHours(weekday=4, state="closed"),
    )
    engine, *_ = fixture(weekly=conflicting)
    assert local(engine, 1).reason == "conflicting_hours"


def test_gap_at_a_published_interval_boundary_remains_unknown_instead_of_shifting_hours():
    day = date(2021, 3, 26)
    item = source(1).model_copy(update={"fetched_at": datetime(2021, 3, 25, tzinfo=UTC)})
    engine, *_ = fixture(item=item, weekly=rules(always=True))
    answer = local(engine, 2, day=day, now=datetime(2021, 3, 27, tzinfo=UTC))
    assert answer.status == "unknown" and answer.reason == "timezone_boundary_unresolved"


def test_untyped_query_and_naive_server_clock_are_refused_and_inputs_remain_immutable():
    engine, plan, _, _ = fixture()
    before = plan.model_dump_json()
    with pytest.raises(ValueError, match="hours_evaluation_input_invalid"):
        engine.evaluate({"mode": "now"}, now=NOW)
    with pytest.raises(ValueError, match="hours_evaluation_input_invalid"):
        engine.evaluate(HoursQuery(subject=CLINIC, mode="now"), now=NOW.replace(tzinfo=None))
    assert local(engine, 19) == local(engine, 19) and plan.model_dump_json() == before
