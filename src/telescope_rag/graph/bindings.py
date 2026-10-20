"""Application-issued handles and literal plan checks; no semantic query heuristics."""

import json
from collections import defaultdict
from types import MappingProxyType

from telescope_rag.graph.contracts import (
    PlannerPart,
    PlannerReply,
    RetrievalQuery,
    ValidatedPlan,
    WorkflowRequest,
)
from telescope_rag.graph.purpose_contract import purpose_contract_manifest
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.retrieval.assembly import (
    AssemblyRequest,
    EvidenceCatalog,
    RequestPart,
    SourceScope,
)


class SourceFilterError(ValueError):
    """An impossible declared filter, distinct from an unsuccessful search."""


class SourceBindings:
    def __init__(
        self,
        catalog: EvidenceCatalog,
        *,
        include_block_types: bool = False,
        directory_authority: DirectoryAuthority | None = None,
        purpose_contract: bool = False,
    ):
        documents = {}
        owners = defaultdict(set)
        block_types = defaultdict(set)
        source_languages = defaultdict(set)
        doctor_documents = set()
        derivative_documents = set()
        for chunk in catalog.chunks.values():
            if purpose_contract:
                source_languages[chunk.document_id].add(chunk.language)
            documents.setdefault(chunk.document_id, (chunk.canonical_url, chunk.page_title))
            if include_block_types:
                block_types[chunk.document_id].add(chunk.block_type)
            if chunk.doctor_id is not None:
                owners[("literal", chunk.doctor_id)].add(chunk.doctor_name)
            if chunk.canonical_doctor_id is not None:
                owners[("canonical", chunk.canonical_doctor_id)].add(chunk.canonical_doctor_name)
            if directory_authority is not None and chunk.block_type == "doctor":
                doctor_documents.add(chunk.document_id)
                if (
                    "department_titles_non_authoritative_use_explicit_roles"
                    in chunk.source_issue_codes
                ):
                    derivative_documents.add(chunk.document_id)
        primary_documents = set()
        if directory_authority is not None:
            primary_documents = set(directory_authority.primary_directory_document_ids)
            if (
                directory_authority.prepared_digest != catalog.prepared_digest
                or len(primary_documents) != len(directory_authority.primary_directory_document_ids)
                or not primary_documents <= doctor_documents
                or primary_documents & derivative_documents
                or any(
                    c.admission_policy_hash != directory_authority.admission_policy_hash
                    for c in catalog.chunks.values()
                )
            ):
                raise ValueError("directory_authority_catalog_mismatch")
        self.directory_authority = directory_authority
        self.purpose_contract = purpose_contract
        self._catalog = catalog
        self.documents = MappingProxyType(
            {f"d{i:04}": identity for i, identity in enumerate(sorted(documents), 1)}
        )
        self.owners = MappingProxyType(
            {f"o{i:04}": identity for i, identity in enumerate(sorted(owners), 1)}
        )
        manifest = {
            "prepared_digest": catalog.prepared_digest,
            "documents": [
                {
                    "handle": handle,
                    "source_url": documents[identity][0],
                    "untrusted_title": documents[identity][1],
                    **(
                        {"available_block_types": sorted(block_types[identity])}
                        if include_block_types
                        else {}
                    ),
                    **(
                        {"available_source_languages": sorted(source_languages[identity])}
                        if purpose_contract
                        else {}
                    ),
                    **(
                        {
                            "source_role": "approved_primary_doctor_directory"
                            if identity in primary_documents
                            else "derivative_directory_titles_non_authoritative"
                            if identity in derivative_documents
                            else "unclassified"
                        }
                        if directory_authority is not None
                        else {}
                    ),
                }
                for handle, identity in self.documents.items()
            ],
            "owners": [
                {
                    "handle": handle,
                    "identity_kind": identity[0],
                    "literal_source_labels": sorted(n for n in owners[identity] if n is not None),
                }
                for handle, identity in self.owners.items()
            ],
        }
        if purpose_contract:
            manifest["purpose_contract"] = purpose_contract_manifest()
        if directory_authority is not None:
            manifest["source_role_basis"] = {
                "prepared_digest": directory_authority.prepared_digest,
                "admission_policy_hash": directory_authority.admission_policy_hash,
                "primary_role": "exact_reviewed_directory_membership",
                "derivative_role": "admitted_doctor_source_issue_code",
                "role_is_not_question_relevance_or_factual_support": True,
            }
        self.manifest_json = json.dumps(manifest, ensure_ascii=False)
        if len(self.manifest_json.encode()) > 96000:
            raise ValueError("planner_source_manifest_exceeds_bound")

    def with_reviewed_profile_limitations(self) -> str:
        """Opt-in view of an existing admission flag, without interpreting source text.

        Occurrence IDs retain the catalog's spans/provenance. Neither a document nor
        an owner inherits a flag from another occurrence. Unannotated sources are
        not classified as informative, and this view never changes plan validation.
        """
        if self.directory_authority is None or not self.purpose_contract:
            raise ValueError("profile_limitations_require_source_contract")
        documents = {identity: handle for handle, identity in self.documents.items()}
        owners = {identity: handle for handle, identity in self.owners.items()}
        code = "name_only_profile_no_specialty_or_biography_claim"
        manifest = json.loads(self.manifest_json)
        manifest["reviewed_profile_limitations"] = {
            "version": "reviewed-profile-limitations-v1",
            "issue_code": code,
            "basis": "exact admitted occurrence source_issue_codes; no new text classification",
            "meaning": (
                "These occurrences retain identity labels, not specialty or biography claims. "
                "They can support naming or literal quotation; they do not establish "
                "doctor_role or profile_detail."
            ),
            "scope_rule": (
                "Applies only to the listed occurrences, not other chunks, documents, "
                "languages or owners. Absence is not evidence of completeness or support. "
                "Other issue codes are not inventoried here. Preserve explicit user source "
                "restrictions; this annotation does not authorize broadening them."
            ),
            "occurrences": [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_handle": documents[chunk.document_id],
                    "literal_owner_handle": owners.get(("literal", chunk.doctor_id)),
                    "canonical_owner_handle": owners.get(("canonical", chunk.canonical_doctor_id)),
                    "source_language": chunk.language,
                    "block_type": chunk.block_type,
                }
                for chunk in sorted(self._catalog.chunks.values(), key=lambda c: c.chunk_id)
                if code in chunk.source_issue_codes
            ],
        }
        serialized = json.dumps(manifest, ensure_ascii=False)
        if len(serialized.encode()) > 96000:
            raise ValueError("planner_source_manifest_exceeds_bound")
        return serialized

    def _available_languages(self) -> frozenset[str]:
        """The published languages actually present in the admitted corpus."""
        return frozenset(
            language
            for chunk in self._catalog.chunks.values()
            for language in (getattr(chunk, "language", None),)
            if language
        )

    def _default_scope_language(
        self,
        proposal: PlannerPart,
        reply_language: str,
        scope: SourceScope,
    ) -> str | None:
        """The evidence language of an unrestricted public search, or None.

        This is a scope default, not a semantic decision. It never overrides a
        page, owner, block type or language restriction, and it never applies to
        a complete source read or to a non-public part.
        """
        if (
            scope.document_ids
            or scope.owner_id is not None
            or scope.block_types
            or scope.complete
            or proposal.state != "public"
            or proposal.operation != "search"
        ):
            return None
        if reply_language == "en":
            return "en"
        if reply_language in {"ar", "ar-JO"}:
            return "ar"
        return None

    def validate(
        self,
        reply: PlannerReply,
        request: WorkflowRequest,
        request_id: str,
        *,
        max_parts: int,
    ) -> ValidatedPlan:
        if (
            len(reply.parts) > max_parts
            or (request.language == "en" and reply.language != "en")
            or (request.language == "ar" and reply.language not in {"ar", "ar-JO"})
        ):
            raise ValueError("planner_request_contract_mismatch")
        parts, queries, operations = [], [], []
        for index, proposal in enumerate(reply.parts, 1):
            if (
                len(set(proposal.document_handles)) != len(proposal.document_handles)
                or any(h not in self.documents for h in proposal.document_handles)
                or (proposal.owner_handle is not None and proposal.owner_handle not in self.owners)
                or len(set(proposal.block_types)) != len(proposal.block_types)
                or len(set(proposal.history_indices)) != len(proposal.history_indices)
                or any(not 0 <= i < len(request.history) for i in proposal.history_indices)
            ):
                raise ValueError("planner_unknown_or_duplicate_binding")
            if proposal.reference_text is not None:
                reference = proposal.reference_text
                originals = [
                    request.query,
                    *[request.history[i].content for i in proposal.history_indices],
                ]
                if not reference.strip() or not any(reference in text for text in originals):
                    raise ValueError("planner_reference_not_literal_context")
            if proposal.state != "public":
                if (
                    proposal.retrieval_query is not None
                    or proposal.document_handles
                    or proposal.owner_handle is not None
                    or proposal.block_types
                    or proposal.source_language is not None
                    or proposal.reason is None
                    or not proposal.reason.strip()
                ):
                    raise ValueError("nonpublic_part_has_retrieval_or_no_reason")
            elif proposal.operation == "search":
                if proposal.retrieval_query is None or not proposal.retrieval_query.strip():
                    raise ValueError("public_search_requires_query")
                if (
                    proposal.reference_text is not None
                    and proposal.reference_text not in proposal.retrieval_query
                ):
                    raise ValueError("retrieval_query_lost_declared_reference")
            elif proposal.retrieval_query is not None:
                raise ValueError("nonsearch_operation_has_query")
            if (
                proposal.state == "public"
                and proposal.operation == "read_source"
                and not proposal.document_handles
            ):
                raise ValueError("complete_read_requires_source_handles")
            owner_kind, owner_id = self.owners.get(proposal.owner_handle, ("literal", None))
            scope = SourceScope(
                document_ids=tuple(self.documents[h] for h in proposal.document_handles),
                owner_id=owner_id,
                owner_kind=owner_kind,
                block_types=proposal.block_types,
                language=proposal.source_language,
                complete=proposal.state == "public" and proposal.operation == "read_source",
            )
            if scope.language is None:
                default_language = self._default_scope_language(proposal, reply.language, scope)
                if default_language is not None:
                    # An unrestricted public search otherwise reads the whole
                    # bilingual corpus, so a question in one language can be
                    # answered from the other language's page. The admitted corpus
                    # holds the same published content in both languages; the
                    # answer language is the published language of the evidence
                    # that should support it. This narrows nothing the visitor or
                    # the planner asked for: it applies only when no page, owner,
                    # block type or language was restricted.
                    narrowed = scope.model_copy(update={"language": default_language})
                    if default_language in self._available_languages():
                        scope = narrowed
            if (
                self.purpose_contract
                and proposal.state == "public"
                and scope.document_ids
                and (scope.owner_id is not None or scope.block_types or scope.language is not None)
                and not self._catalog.scope_members(scope)
            ):
                raise SourceFilterError("planner_source_filters_have_empty_intersection")
            part_id = f"{request_id}-p{index}"
            parts.append(
                RequestPart(
                    part_id=part_id,
                    start=proposal.start,
                    end=proposal.end,
                    state=proposal.state,
                    reason=proposal.reason or "",
                    intended_use=proposal.intended_use,
                    scope=scope,
                )
            )
            operations.append(proposal.operation)
            if proposal.state == "public" and proposal.operation == "search":
                queries.append(
                    RetrievalQuery(part_id=part_id, text=proposal.retrieval_query, scope=scope)
                )
        # Structural character accounting does not prove decomposition correctness.
        assembly = AssemblyRequest(original_query=request.query, parts=tuple(parts))
        return ValidatedPlan(reply.language, assembly, tuple(operations), tuple(queries))
