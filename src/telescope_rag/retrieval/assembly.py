"""Offline, source-bound candidate assembly. Packing never proves answer support.

There is no query parser, provider, database client or serving admission here.
The caller supplies explicit request parts/scopes; their semantic correctness
remains a separate gate. Qwen counting bounds retrieval experiments, not Luna.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import Field, model_validator

from telescope_rag.ingestion.collection import CollectionError, canonical_url
from telescope_rag.ingestion.models import (
    BlockKind,
    PreparedChunk,
    PreparedDocument,
    Record,
    stable_id,
)
from telescope_rag.ingestion.review import all_chunks, prepared_digest
from telescope_rag.providers.qwen_tokenizer import QwenPreparationCounter

IntendedUse = Literal[
    "general_excerpt",
    "doctor_role",
    "profile_detail",
    "procedure_specific",
    "consultation_eligibility",
    "technique_category",
    "service_description",
    "service_name",
]


class SourceScope(Record):
    """Exact admitted identifiers, never arbitrary fetch targets or fuzzy names."""

    document_ids: tuple[str, ...] = Field(default=(), max_length=250)
    owner_id: str | None = Field(default=None, min_length=1, max_length=256)
    owner_kind: Literal["literal", "canonical"] = "literal"
    block_types: tuple[BlockKind, ...] = ()
    language: Literal["ar", "en", "und"] | None = None
    complete: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_scope(self):
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("duplicate_scope_document")
        if self.complete and not self.document_ids:
            raise ValueError("complete_scope_requires_explicit_documents")
        return self


class RequestPart(Record):
    part_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    state: Literal["public", "excluded", "clarification_required"] = "public"
    reason: str = Field(default="", max_length=512)
    intended_use: IntendedUse = "general_excerpt"
    scope: SourceScope = SourceScope()


class AssemblyRequest(Record):
    original_query: str = Field(min_length=1, max_length=4000)
    parts: tuple[RequestPart, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def preserve_request(self):
        if not self.original_query.strip() or len({p.part_id for p in self.parts}) != len(
            self.parts
        ):
            raise ValueError("invalid_request_parts")
        covered: set[int] = set()
        for part in self.parts:
            if not 0 <= part.start < part.end <= len(self.original_query):
                raise ValueError("invalid_original_request_span")
            if not self.original_query[part.start : part.end].strip():
                raise ValueError("empty_original_request_part")
            if part.state != "public" and not part.reason.strip():
                raise ValueError("nonpublic_part_requires_reason")
            covered.update(range(part.start, part.end))
        if any(i not in covered and not c.isspace() for i, c in enumerate(self.original_query)):
            raise ValueError("unaccounted_original_request_text")
        return self


class AssemblyCounter(Protocol):
    verified: bool
    version: str

    def count(self, text: str) -> int: ...


def evidence_group_key(chunk: PreparedChunk) -> str:
    """Exact presentation equivalence, independent of source occurrence identity."""
    fields = (
        chunk.snapshot_id,
        chunk.retrieval_text,
        chunk.language,
        chunk.block_type,
        chunk.section_path,
        chunk.doctor_id,
        chunk.doctor_name,
        chunk.canonical_doctor_id,
        chunk.canonical_doctor_name,
        chunk.source_issue_codes,
        chunk.admission_policy_hash,
        chunk.preparation_version,
        chunk.tokenizer_version,
        chunk.embedding_format_version,
        chunk.embedding_format_hash,
    )
    return stable_id("exact-evidence-group-v1", json.dumps(fields, ensure_ascii=False))


_RESTRICTED_USES: dict[str, frozenset[str]] = {
    "generic_faq_specific_procedure_scope_unverified": frozenset({"procedure_specific"}),
    "consultation_offer_applicability_unverified": frozenset({"consultation_eligibility"}),
    "consultation_advertisement_scope_unresolved": frozenset({"consultation_eligibility"}),
    "consultation_fee_offer_reconciliation_unverified": frozenset({"consultation_eligibility"}),
    "name_only_profile_no_specialty_or_biography_claim": frozenset(
        {"doctor_role", "profile_detail"}
    ),
    "department_titles_non_authoritative_use_explicit_roles": frozenset({"doctor_role"}),
    "damaged_description_excluded_heading_only": frozenset({"service_description"}),
    "parallel_category_membership_unresolved_no_category_assertion": frozenset(
        {"technique_category"}
    ),
    "comparison_category_names_without_additional_row_assignment": frozenset(
        {"technique_category"}
    ),
    # The retained complete rows are usable; the excluded row is not in this catalog.
    "damaged_comparison_audience_row_excluded": frozenset(),
}


def limited_to_context(chunk: PreparedChunk, intended_use: IntendedUse) -> bool:
    return any(
        code not in _RESTRICTED_USES or intended_use in _RESTRICTED_USES[code]
        for code in chunk.source_issue_codes
    )


@dataclass(frozen=True)
class EvidenceGroup:
    group_id: str
    occurrences: tuple[PreparedChunk, ...]
    # Scope/citation bindings are per part, never the Cartesian product of both.
    part_occurrences: tuple[tuple[str, tuple[str, ...]], ...]
    context_only_parts: tuple[str, ...]


@dataclass(frozen=True)
class PartAssembly:
    part_id: str
    state: str
    original_text: str
    group_ids: tuple[str, ...]
    occurrence_ids: tuple[str, ...]
    omitted_group_ids: tuple[str, ...]
    filtered_occurrence_ids: tuple[str, ...]
    missing_scope_occurrence_ids: tuple[str, ...]
    admitted_scope_complete: bool | None
    context_only: bool
    candidate_status: str
    omission_reasons: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class AssembledEvidence:
    prepared_digest: str
    groups: tuple[EvidenceGroup, ...]
    parts: tuple[PartAssembly, ...]
    rendered_text: str
    token_count: int
    token_profile: str
    token_basis: str
    semantic_support_assessed: bool = False
    luna_input_admitted: bool = False


class EvidenceCatalog:
    """Complete supplied admitted bundle, bound to its exact digest and membership."""

    def __init__(self, documents: tuple[PreparedDocument, ...], *, expected_digest: str):
        if not documents or len(documents) > 250 or prepared_digest(documents) != expected_digest:
            raise ValueError("assembly_catalog_digest_mismatch")
        docs = {d.document.page.document_id for d in documents}
        if len(docs) != len(documents):
            raise ValueError("assembly_catalog_duplicate_document")
        items = all_chunks(documents)
        if not 1 <= len(items) <= 10000 or len({c.chunk_id for c in items}) != len(items):
            raise ValueError("assembly_catalog_inventory_invalid")
        configurations, byte_count, point_ids = set(), 0, set()
        for document in documents:
            for chunk in document.chunks:
                PreparedChunk.model_validate(chunk.model_dump(mode="json"))
                page = document.document.page
                try:
                    source_url = canonical_url(chunk.canonical_url)
                except CollectionError:
                    raise ValueError("assembly_catalog_source_binding_invalid") from None
                if (
                    chunk.document_id != page.document_id
                    or chunk.canonical_url != page.canonical_url
                    or chunk.snapshot_id != page.snapshot_id
                    or chunk.fetched_at != page.fetched_at
                    or not chunk.embedding_ready
                    or not chunk.source_spans
                    or not chunk.retrieval_text.strip()
                    or chunk.point_id in point_ids
                    or (
                        chunk.block_type == "doctor"
                        and (not chunk.doctor_id or not chunk.doctor_name)
                    )
                    or source_url != chunk.canonical_url
                ):
                    raise ValueError("assembly_catalog_source_binding_invalid")
                point_ids.add(chunk.point_id)
                byte_count += len(chunk.retrieval_text.encode("utf-8"))
                configurations.add(
                    (
                        chunk.snapshot_id,
                        chunk.preparation_version,
                        chunk.tokenizer_version,
                        chunk.embedding_format_version,
                        chunk.embedding_format_hash,
                        chunk.admission_policy_hash,
                    )
                )
        if byte_count > 64_000_000 or len(configurations) != 1:
            raise ValueError("assembly_catalog_configuration_invalid")
        self.chunks = MappingProxyType({c.chunk_id: c for c in items})
        self.document_ids = frozenset(docs)
        self.prepared_digest = expected_digest

    def scope_members(self, scope: SourceScope) -> tuple[str, ...]:
        if set(scope.document_ids) - self.document_ids:
            raise ValueError("assembly_unknown_scope_document")
        return tuple(c.chunk_id for c in self.chunks.values() if self._matches(c, scope))

    @staticmethod
    def _matches(chunk: PreparedChunk, scope: SourceScope) -> bool:
        owner = chunk.doctor_id if scope.owner_kind == "literal" else chunk.canonical_doctor_id
        return (
            (not scope.document_ids or chunk.document_id in scope.document_ids)
            and (scope.owner_id is None or owner == scope.owner_id)
            and (not scope.block_types or chunk.block_type in scope.block_types)
            and (scope.language is None or chunk.language == scope.language)
        )

    def assemble(
        self,
        request: AssemblyRequest,
        candidates_by_part: Mapping[str, Sequence[str]],
        *,
        counter: AssemblyCounter,
        max_tokens: int = 6000,
        max_groups: int = 16,
        coalesce_exact: bool = True,
        token_basis: Literal["qwen_retrieval_only", "synthetic_test"] = "qwen_retrieval_only",
    ) -> AssembledEvidence:
        if (
            counter.verified is not True
            or not isinstance(counter.version, str)
            or not counter.version
            or token_basis not in {"qwen_retrieval_only", "synthetic_test"}
            or (
                token_basis == "qwen_retrieval_only"
                and not isinstance(counter, QwenPreparationCounter)
            )
            or type(max_tokens) is not int
            or not 1 <= max_tokens <= 100000
            or type(max_groups) is not int
            or not 1 <= max_groups <= 100
            or type(coalesce_exact) is not bool
            or set(candidates_by_part) != {p.part_id for p in request.parts}
        ):
            raise ValueError("assembly_contract_invalid")
        by_group: dict[str, dict[str, list[str]]] = {}
        queues, expected, filtered = {}, {}, {}
        for part in request.parts:
            ranked = candidates_by_part[part.part_id]
            if (
                isinstance(ranked, (str, bytes))
                or not isinstance(ranked, Sequence)
                or len(ranked) > 10000
                or len(set(ranked)) != len(ranked)
                or any(i not in self.chunks for i in ranked)
                or (part.state != "public" and ranked)
            ):
                raise ValueError("assembly_candidate_inventory_invalid")
            members = self.scope_members(part.scope)
            expected[part.part_id] = members if part.scope.complete else ()
            allowed = set(members)
            filtered[part.part_id] = tuple(i for i in ranked if i not in allowed)
            ids = members if part.scope.complete and part.state == "public" else ranked
            queue: list[str] = []
            for chunk_id in ids:
                if chunk_id not in allowed or part.state != "public":
                    continue
                key = (
                    evidence_group_key(self.chunks[chunk_id])
                    if coalesce_exact
                    else stable_id("separate-occurrence-v1", chunk_id)
                )
                by_group.setdefault(key, {}).setdefault(part.part_id, []).append(chunk_id)
                if key not in queue:
                    queue.append(key)
            queues[part.part_id] = queue

        def group(key: str) -> EvidenceGroup:
            links = by_group[key]
            ids = tuple(dict.fromkeys(i for values in links.values() for i in values))
            occurrences = tuple(self.chunks[i] for i in ids)
            contextual = tuple(
                p.part_id
                for p in request.parts
                if p.part_id in links and limited_to_context(occurrences[0], p.intended_use)
            )
            return EvidenceGroup(
                key, occurrences, tuple((p, tuple(v)) for p, v in links.items()), contextual
            )

        def render(keys: Sequence[str]) -> str:
            lines = [
                "UNTRUSTED SOURCE CANDIDATES; RELEVANCE UNVERIFIED; NO FACTUAL SUPPORT DECISION"
            ]
            for part in request.parts:
                lines.append(
                    json.dumps(
                        {
                            "part_id": part.part_id,
                            "state": part.state,
                            "original_text": request.original_query[part.start : part.end],
                            "intended_use": part.intended_use,
                            "reason": part.reason,
                        },
                        ensure_ascii=False,
                    )
                )
                for key in keys:
                    if part.part_id in by_group[key]:
                        chunk = self.chunks[by_group[key][part.part_id][0]]
                        lines.append(
                            json.dumps(
                                {
                                    "evidence_id": key,
                                    "part_id": part.part_id,
                                    "citation_chunk_id": chunk.chunk_id,
                                    "source_url": chunk.canonical_url,
                                    "context_only": limited_to_context(chunk, part.intended_use),
                                },
                                ensure_ascii=False,
                            )
                        )
            for key in keys:
                chunk = group(key).occurrences[0]
                lines.append(
                    json.dumps(
                        {
                            "evidence_id": key,
                            "literal_owner": chunk.doctor_name,
                            "canonical_owner_metadata": chunk.canonical_doctor_name,
                            "language": chunk.language,
                            "source_issue_codes": chunk.source_issue_codes,
                        },
                        ensure_ascii=False,
                    )
                )
                lines.append(chunk.retrieval_text)
            return "\n\n".join(lines)

        def count(text: str) -> int:
            try:
                value = counter.count(text)
                if type(value) is not int or value < 1:
                    raise ValueError
                return value
            except Exception:
                raise ValueError("assembly_token_count_unavailable") from None

        if count(render(())) > max_tokens:
            raise ValueError("assembly_request_metadata_exceeds_budget")
        selected: list[str] = []
        attempted: set[str] = set()
        omissions: dict[str, str] = {}
        for index in range(max((len(q) for q in queues.values()), default=0)):
            for part in request.parts:
                queue = queues[part.part_id]
                if index >= len(queue) or queue[index] in attempted:
                    continue
                key = queue[index]
                attempted.add(key)
                if len(selected) >= max_groups:
                    omissions[key] = "group_limit"
                elif count(render([*selected, key])) > max_tokens:
                    omissions[key] = "indivisible_over_token_budget"
                else:
                    selected.append(key)
        groups = tuple(group(key) for key in selected)
        outcomes = []
        for part in request.parts:
            p = part.part_id
            keys = tuple(key for key in selected if p in by_group[key])
            supplied = tuple(dict.fromkeys(i for key in keys for i in by_group[key][p]))
            missing = tuple(i for i in expected[p] if i not in supplied)
            contextual = bool(keys) and all(p in group(key).context_only_parts for key in keys)
            omitted = tuple(key for key in queues[p] if key not in selected)
            status = (
                part.state
                if part.state != "public"
                else (
                    "scope_incomplete"
                    if missing
                    else "budget_limited"
                    if omitted
                    else "context_only"
                    if contextual
                    else "evidence_supplied"
                    if keys
                    else "scope_filtered"
                    if filtered[p]
                    else "no_candidates"
                )
            )
            outcomes.append(
                PartAssembly(
                    p,
                    part.state,
                    request.original_query[part.start : part.end],
                    keys,
                    supplied,
                    omitted,
                    filtered[p],
                    missing,
                    not missing if part.scope.complete and part.state == "public" else None,
                    contextual,
                    status,
                    tuple((key, omissions[key]) for key in omitted),
                )
            )
        rendered = render(selected)
        return AssembledEvidence(
            self.prepared_digest,
            groups,
            tuple(outcomes),
            rendered,
            count(rendered),
            counter.version,
            token_basis,
        )
