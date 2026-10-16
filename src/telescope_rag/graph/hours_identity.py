"""Opt-in projection of admitted identity metadata, without name matching or scope changes."""

import json
from collections import defaultdict

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.hours_inputs import HoursBindings

IDENTITY_PROFILE = "identity_links_v13"
IDENTITY_PROMPT_VERSION = "offline-rag-planner-hours-identity-context-v13"


def identity_hours_manifest(hours: HoursBindings, sources: SourceBindings) -> str:
    """Expose exact existing alias relationships; a relationship is never hours evidence."""
    owner_handles = {value: handle for handle, value in sources.owners.items()}
    subject_handles = {
        (subject.owner_kind, subject.id): handle
        for handle, subject in hours.subjects.items()
        if subject.kind == "doctor"
    }
    document_handles = {identity: handle for handle, identity in sources.documents.items()}
    literal_targets: dict[str, str] = {}
    canonical_names: dict[str, str] = {}
    witnesses = defaultdict(list)
    aliases = defaultdict(set)
    for chunk in hours.catalog.chunks.values():
        identity, name = chunk.canonical_doctor_id, chunk.canonical_doctor_name
        if identity is None and name is None:
            continue
        if (
            not identity
            or not name
            or not chunk.doctor_id
            or not chunk.doctor_name
            or literal_targets.setdefault(chunk.doctor_id, identity) != identity
            or canonical_names.setdefault(identity, name) != name
        ):
            raise ValueError("hours_identity_metadata_inconsistent")
        literal = ("literal", chunk.doctor_id)
        canonical = ("canonical", identity)
        if (
            literal not in owner_handles
            or canonical not in owner_handles
            or literal not in subject_handles
            or canonical not in subject_handles
            or chunk.document_id not in document_handles
        ):
            raise ValueError("hours_identity_handle_unissued")
        aliases[identity, chunk.doctor_id].add(chunk.doctor_name)
        witnesses[identity, chunk.doctor_id].append(
            {"document_handle": document_handles[chunk.document_id], "chunk_id": chunk.chunk_id}
        )
    groups = []
    for identity in sorted(canonical_names):
        groups.append(
            {
                "canonical_subject_handle": subject_handles["canonical", identity],
                "canonical_owner_handle": owner_handles["canonical", identity],
                "approved_display_name": canonical_names[identity],
                "literal_members": [
                    {
                        "subject_handle": subject_handles["literal", literal],
                        "owner_handle": owner_handles["literal", literal],
                        "literal_labels": sorted(aliases[identity, literal]),
                        "metadata_witnesses": sorted(
                            witnesses[identity, literal],
                            key=lambda w: (w["document_handle"], w["chunk_id"]),
                        ),
                    }
                    for literal in sorted(literal_targets)
                    if literal_targets[literal] == identity
                ],
            }
        )
    manifest = json.loads(hours.manifest_json)
    manifest.update(
        version="public-hours-handles-identity-links-v2",
        identity_metadata={
            "basis": "Existing admitted canonical_doctor_id/name metadata only.",
            "meaning": "Each group identifies one confirmed person across its literal owners.",
            "scope": "Literal owners, source restrictions and hours selection stay separate.",
            "hours_authority": "Identity links establish no schedule, attendance or availability.",
            "unlisted_relationships": "Unconfirmed; matching labels or specialties imply no link.",
            "groups": groups,
        },
    )
    result = json.dumps(manifest, ensure_ascii=False)
    if len(result.encode()) > 96000:
        raise ValueError("hours_manifest_exceeds_bound")
    return result
