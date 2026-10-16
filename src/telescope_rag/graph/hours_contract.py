"""Opt-in clock/operation and exact doctor-source relationship contracts."""

import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.hours_identity import identity_hours_manifest
from telescope_rag.graph.hours_inputs import HoursBindings, HoursPlannerPart, HoursPlannerReply
from telescope_rag.graph.hours_records import ComputedHours, HoursInput
from telescope_rag.retrieval.assembly import RequestPart

HoursProfile = Literal["v12", "identity_links_v13", "contracts_v14"]


class ContractHoursInput(HoursInput):
    hour: int | None = Field(
        ge=0,
        le=23,
        description="local only: 0..23 with 24h; 1..12 with am, pm or unspecified. Else null.",
    )
    clock_basis: Literal["24h", "am", "pm", "unspecified"] | None = Field(
        description="12 AM = 12/am or 0/24h; 12 PM = 12/pm or 12/24h. Never mix 0 with am/pm."
    )

    @model_validator(mode="after")
    def clock_pair(self):
        if self.intent == "local" and self.clock_basis != "24h" and not 1 <= self.hour <= 12:
            raise ValueError("hours_clock_pair_invalid")
        return self


class ContractHoursPlannerPart(HoursPlannerPart):
    retrieval_query: str | None = Field(
        max_length=4000,
        repr=False,
        description="Non-null only for public search. Hours/time_comparison always uses null.",
    )
    hours: ContractHoursInput | None = Field(
        description="Non-null exactly for public time_comparison; all other parts require null."
    )

    @model_validator(mode="after")
    def exclusive_operation(self):
        is_hours = self.state == "public" and self.operation == "time_comparison"
        if is_hours != (self.hours is not None) or (
            is_hours
            and (self.retrieval_query is not None or self.intended_use != "general_excerpt")
        ):
            raise ValueError("hours_operation_contract_invalid")
        return self


class ContractHoursPlannerReply(HoursPlannerReply):
    parts: tuple[ContractHoursPlannerPart, ...] = Field(min_length=1, max_length=4)


def hours_reply_model(profile: HoursProfile) -> type[HoursPlannerReply]:
    if profile not in {"v12", "identity_links_v13", "contracts_v14"}:
        raise ValueError("hours_profile_invalid")
    return ContractHoursPlannerReply if profile == "contracts_v14" else HoursPlannerReply


def contract_hours_manifest(hours: HoursBindings, sources: SourceBindings) -> str:
    """Exact document/type/language tuples for each issued doctor subject; no inference."""
    manifest = json.loads(identity_hours_manifest(hours, sources))
    document_handles = {identity: handle for handle, identity in sources.documents.items()}
    for entry in manifest["subjects"]:
        subject = hours.subjects[entry["handle"]]
        if subject.kind != "doctor":
            continue
        membership = {
            (document_handles[c.document_id], c.block_type, c.language)
            for c in hours.catalog.chunks.values()
            if (c.doctor_id if subject.owner_kind == "literal" else c.canonical_doctor_id)
            == subject.id
        }
        entry["source_membership"] = [
            {"document_handle": document, "block_type": kind, "source_language": language}
            for document, kind, language in sorted(membership)
        ]
    manifest["version"] = "public-hours-contract-handles-v3"
    result = json.dumps(manifest, ensure_ascii=False)
    if len(result.encode()) > 96000:
        raise ValueError("hours_manifest_exceeds_bound")
    return result


class ContractHoursBindings(HoursBindings):
    def bind(
        self,
        supplied: HoursInput,
        *,
        part: RequestPart,
        request: WorkflowRequest,
        reference_text: str | None,
        history_indices: tuple[int, ...],
        now: datetime,
    ) -> ComputedHours:
        # Also rechecked by the independent presenter, using this exact bindings object.
        ContractHoursInput.model_validate_json(supplied.model_dump_json())
        subject = self.subjects.get(supplied.subject_handle)
        if subject is not None and subject.kind == "doctor":
            if part.scope.owner_id is not None and (
                part.scope.owner_kind,
                part.scope.owner_id,
            ) != (subject.owner_kind, subject.id):
                raise ValueError("hours_subject_scope_mismatch")
            doctor_scope = part.scope.model_copy(
                update={"owner_id": subject.id, "owner_kind": subject.owner_kind}
            )
            if not self.catalog.scope_members(doctor_scope):
                raise ValueError("hours_doctor_subject_outside_source_scope")
        return super().bind(
            supplied,
            part=part,
            request=request,
            reference_text=reference_text,
            history_indices=history_indices,
            now=now,
        )
