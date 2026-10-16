"""Versioned planner meanings, never a runtime classifier or source-policy override."""

from types import MappingProxyType

PURPOSE_CONTRACT_VERSION = "planner-purpose-source-contract-v1"

INTENDED_USE_DEFINITIONS = MappingProxyType(
    {
        "general_excerpt": (
            "Report literal published information with its source attribution, including contact "
            "details, hours, fee notices or explicitly requested page wording. This does not "
            "establish an unresolved applicability, professional role, biography, procedure "
            "scope or category relationship. Use the corresponding specific purpose when "
            "that relationship itself is what the target asks to establish."
        ),
        "doctor_role": (
            "Establish a doctor's professional role or specialty as a factual relationship. "
            "Requires explicit eligible main-directory/profile evidence for that owner; "
            "a derivative heading, copied wording or identity label is not authority."
        ),
        "profile_detail": (
            "Establish a named doctor's biography, training, experience or other requested "
            "profile details. Name-only profiles do not establish these details. "
            "Preserve the requested source and each distinct doctor's ownership."
        ),
        "procedure_specific": (
            "Establish information as applying to a particular procedure. A generic FAQ "
            "without verified procedure ownership cannot establish that application. "
            "This remains public information, not personal treatment suitability."
        ),
        "consultation_eligibility": (
            "Establish whether, when or for whom a consultation offer or fee arrangement "
            "applies, including a visitor asking about their visit. Published advertising "
            "and separate-fee wording do not resolve an unverified applicability or "
            "free-versus-paid relationship. A request merely to report fee wording has "
            "a reporting purpose instead. Unknown public applicability remains public."
        ),
        "technique_category": (
            "Establish a technique's category or membership in a comparison group. "
            "Detached category names or parallel layout order do not establish membership. "
            "Literal reporting of an intact published row is not a new category assertion."
        ),
        "service_description": (
            "Explain source-supported service content, methods, audience, benefits, "
            "limitations or other descriptive details. A service heading alone cannot "
            "establish a damaged or excluded description. A more specific relationship "
            "purpose takes precedence when that is what the target asks to establish."
        ),
        "service_name": (
            "Identify or list literal published service names. A name supports naming "
            "only; it does not restore missing descriptions or establish suitability, "
            "equivalence across languages or a doctor-to-service relationship."
        ),
    }
)


def purpose_contract_manifest() -> dict:
    """A fresh serialization; callers cannot mutate the shared definitions."""
    return {
        "version": PURPOSE_CONTRACT_VERSION,
        "intended_use_definitions": dict(INTENDED_USE_DEFINITIONS),
        "selection_rule": (
            "Choose by the relationship the answer target asks to establish, not the topic "
            "or which label permits more quotes. Never relabel to bypass source restrictions. "
            "Separate independent purposes; do not split coherent shared qualifications."
        ),
        "source_language_basis": "exact admitted chunk language within each document",
        "scope_validation": (
            "Explicit document scope with owner/type/language filters must have a nonempty "
            "combined catalog intersection. Membership is not relevance, answer support, "
            "complete source coverage or permission to fetch. No plan repair or retry."
        ),
    }
