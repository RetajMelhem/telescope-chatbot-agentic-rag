"""Exact reviewed directory membership; no URL/title or question classification."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from telescope_rag.ingestion.admission import AdmissionPlan, admission_hash


class DirectoryAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    prepared_digest: str = Field(min_length=1)
    admission_policy_hash: str = Field(min_length=1)
    primary_directory_document_ids: tuple[str, ...] = Field(min_length=1, max_length=250)


def reviewed_directory_authority(
    plan: AdmissionPlan, metadata: Mapping[str, Any], *, prepared_digest: str
) -> DirectoryAuthority:
    """Project an already authenticated admission plan and its matching metadata.

    Callers authenticate file hashes/approval separately. These exact membership
    checks establish no semantic relationship between a question and a source.
    """
    pages = metadata.get("pages")
    if (
        metadata.get("prepared_digest") != prepared_digest
        or metadata.get("policy_hash") != admission_hash(plan)
        or not isinstance(pages, list)
        or any(not isinstance(p, dict) or not isinstance(p.get("document_id"), str) for p in pages)
    ):
        raise ValueError("directory_authority_metadata_mismatch")
    ids = tuple(p["document_id"] for p in pages)
    if (
        not ids
        or len(set(ids)) != len(ids)
        or set(ids) != set(plan.primary_directory_document_ids)
        or len(set(plan.primary_directory_document_ids)) != len(plan.primary_directory_document_ids)
    ):
        raise ValueError("directory_authority_membership_mismatch")
    return DirectoryAuthority(
        prepared_digest=prepared_digest,
        admission_policy_hash=admission_hash(plan),
        primary_directory_document_ids=tuple(sorted(ids)),
    )
