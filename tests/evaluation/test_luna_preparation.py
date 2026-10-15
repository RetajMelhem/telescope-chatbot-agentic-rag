"""Exact offline payload capture with synthetic sources, never real provider counts."""

import asyncio
import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.planner_review import PlannerFixture
from scripts.prepare_luna_screen import (
    CaptureError,
    ForbiddenTransport,
    RecordingRejectCounter,
    capture_case,
    capture_settings,
    parser,
    payload_bytes,
    prepare,
)
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.ingestion.models import (
    ExtractedDocument,
    PreparedChunk,
    PreparedDocument,
    RawPage,
    SourceSpan,
)
from telescope_rag.ingestion.review import prepared_digest
from telescope_rag.prompts.offline_v1 import PLANNER_SYSTEM, PROMPT_VERSION
from telescope_rag.providers.contracts import TokenCount
from telescope_rag.providers.errors import ProviderError
from telescope_rag.retrieval.assembly import EvidenceCatalog


class SyntheticCounter:
    verified = True
    version = "synthetic-character-units-not-production-tokens"

    def count(self, text):
        return len(text)


def synthetic_catalog(count=1, flags=()):
    chunks = []
    for i in range(1, count + 1):
        text = f"Synthetic passage {i}: improvement may be gradual; assessment is required."
        span = SourceSpan(
            block_id=f"synthetic-span-{i}", locator="main > p", original_text=text, end=len(text)
        )
        chunks.append(
            PreparedChunk(
                chunk_id=f"synthetic-chunk-{i}",
                point_id=str(UUID(int=i)),
                document_id="synthetic-document",
                canonical_url="https://telescopecenter.com/test/",
                page_title="Synthetic fixture",
                snapshot_id="synthetic-snapshot",
                fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
                parent_block_id=f"parent-{i}",
                block_type="section",
                language="en",
                section_path=(),
                source_issue_codes=flags,
                admission_policy_hash="synthetic-policy",
                source_spans=(span,),
                original_text=text,
                retrieval_text=text,
                content_hash=f"content-{i}",
                token_count=8,
                tokenizer_version="synthetic",
                embedding_format_version="synthetic",
                embedding_format_hash="synthetic",
                embedding_ready=True,
            )
        )
    document = PreparedDocument(
        document=ExtractedDocument(
            page=RawPage(
                snapshot_id="synthetic-snapshot",
                document_id="synthetic-document",
                canonical_url="https://telescopecenter.com/test/",
                fetched_at=chunks[0].fetched_at,
                content_hash="synthetic-html",
                html="<main><p>Synthetic source fixture.</p></main>",
            ),
            title="Synthetic fixture",
            units=(),
        ),
        chunks=tuple(chunks),
        embedding_ready=True,
    )
    return EvidenceCatalog((document,), expected_digest=prepared_digest((document,)))


def fixture(
    catalog,
    *,
    query="Synthetic source question",
    language="en",
    history=(),
    operation="search",
    state="public",
    intended_use="general_excerpt",
    resolution="candidate",
    witness_ids=None,
):
    manifest = json.loads(SourceBindings(catalog).manifest_json)
    witnesses = tuple(catalog.chunks) if witness_ids is None else witness_ids
    if state != "public":
        witnesses = ()
        resolution = state
    value = {
        "case_id": f"SYN-{language}",
        "family_id": "SYN",
        "language": language,
        "split": "development",
        "request": {"query": query, "history": list(history), "language": "auto"},
        "expected_plan": {
            "language": language,
            "parts": [
                {
                    "start": 0,
                    "end": len(query),
                    "state": state,
                    "operation": operation,
                    "intended_use": intended_use,
                    "retrieval_query": query
                    if operation == "search" and state == "public"
                    else None,
                    "document_handles": [manifest["documents"][0]["handle"]]
                    if state == "public"
                    else [],
                    "owner_handle": None,
                    "block_types": [],
                    "source_language": None,
                    "reference_text": None,
                    "history_indices": [],
                    "reason": None if state == "public" else "Synthetic scope exclusion.",
                }
            ],
        },
        "part_reviews": [
            {
                "part_index": 0,
                "witness_chunk_ids": list(witnesses),
                "expected_resolution": resolution,
                "semantic_rationale": "Synthetic fixture, not clinic acceptance.",
                "protected_text": [query],
            }
        ],
        "author_agent": "synthetic-author",
        "author_model": "gpt-6.1-sol",
    }
    return PlannerFixture.model_validate_json(json.dumps(value), strict=True)


def capture(case, catalog):
    return asyncio.run(
        capture_case(case, catalog, SyntheticCounter(), token_basis="synthetic_test")
    )


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Read this synthetic qualification."),
        ("ar", "اقرأ القيد التجريبي بدون تغييره."),
        ("ar-JO", "شو بحكي القيد التجريبي؟ خليه زي ما هو."),
    ],
)
def test_actual_graph_adapter_capture_preserves_language_unknown_count_and_zero_dispatch(
    language,
    query,
):
    catalog = synthetic_catalog()
    result = capture(fixture(catalog, language=language, query=query), catalog)
    assert [p["stage"] for p in result["payloads"]] == ["planning", "draft"]
    assert result["oracle_provenance"]["continuations"] == 1
    assert result["oracle_provenance"]["retrieval_batches"] == 1
    assert result["workflow_result"]["outcome"] == "failed"
    assert result["workflow_result"]["error_code"] == "provider_failed"
    assert result["workflow_result"]["offline_only"]
    assert not result["workflow_result"]["semantic_grounding_verified"]
    assert result["luna_input_tokens"] is result["estimated_provider_cost_usd"] is None
    assert result["http_attempts"] == result["provider_calls"] == result["index_calls"] == 0
    assert (
        result["budget_operations"]
        == result["budget_reservations"]
        == {
            "chat": 0,
            "embedding": 0,
        }
    )
    assert not result["planner_model_executed"] and not result["draft_model_executed"]
    assert not result["model_accuracy_assessed"] and not result["production_ready"]
    assert result["evidence"]["token_basis"] == "synthetic_test"
    for item in result["payloads"]:
        raw = payload_bytes(item["payload"])
        assert item["serialized_utf8"].encode() == raw
        assert item["serialized_bytes"] == len(raw)
        assert item["serialized_sha256"] == hashlib.sha256(raw).hexdigest()
        assert item["luna_input_tokens"] is None
        assert item["payload"]["max_completion_tokens"] == 1000
        assert item["payload"]["provider"] == {
            "require_parameters": True,
            "allow_fallbacks": False,
        }


def test_planning_payload_is_actual_request_manifest_schema_and_history_without_gold():
    catalog = synthetic_catalog()
    history = (
        {"role": "user", "content": "Synthetic previous name: Dr. Example."},
        {"role": "assistant", "content": "Synthetic untrusted previous reply."},
    )
    case = fixture(catalog, history=history)
    result = capture(case, catalog)
    planning, draft = [item["payload"] for item in result["payloads"]]
    assert planning["messages"][0] == {"role": "system", "content": PLANNER_SYSTEM}
    body = json.loads(planning["messages"][1]["content"])
    assert body == {
        "prompt_version": PROMPT_VERSION,
        "original_query": case.request.query,
        "requested_language": "auto",
        "history": list(history),
        "max_parts": 4,
        "source_manifest": json.loads(SourceBindings(catalog).manifest_json),
    }
    assert "expected_plan" not in body and "part_reviews" not in body
    assert "witness_chunk_ids" not in json.dumps(body)
    assert planning["model"] == "openai/gpt-6-luna" and planning["stream"] is False
    assert planning["response_format"]["type"] == "json_schema"
    assert planning["response_format"]["json_schema"]["strict"] is True
    generation = json.loads(draft["messages"][-1]["content"])
    assert generation["history"] == list(history)
    assert generation["parts"][0]["part_id"].endswith("-p1")
    assert generation["parts"][0]["part_id"].startswith(result["workflow_result"]["request_id"])
    assert generation["parts"][0]["eligible_quote_chunk_ids"] == ["synthetic-chunk-1"]
    assert (
        catalog.chunks["synthetic-chunk-1"].retrieval_text
        in generation["untrusted_candidate_rendering"]
    )


def test_captured_schema_properties_all_required_including_nullable_fields():
    catalog = synthetic_catalog()
    result = capture(fixture(catalog), catalog)

    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)

    for item in result["payloads"]:
        inspect(item["payload"]["response_format"]["json_schema"]["schema"])


def test_ambient_credentials_endpoints_and_budget_overrides_cannot_enter_capture(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=synthetic-dotenv-tripwire\n")
    for key, value in {
        "OPENROUTER_API_KEY": "synthetic-process-tripwire",
        "OPENROUTER_BASE_URL": "https://untrusted.invalid/api/v1",
        "QDRANT_URL": "http://untrusted.invalid:9999",
        "MAX_EVIDENCE_TOKENS": "1",
        "RETRIEVAL_TOP_K_PER_QUESTION": "999",
        "MAX_TOTAL_OUTPUT_TOKENS": "500000",
        "LANGSMITH_TRACING": "true",
    }.items():
        monkeypatch.setenv(key, value)
    config = capture_settings()
    assert str(config.openrouter_base_url) == "https://openrouter.ai/api/v1"
    assert config.max_evidence_tokens == 6000
    assert config.retrieval_top_k_per_question == 5
    assert config.max_total_output_tokens == 2000
    assert config.provider_max_retries == 0
    assert not config.langsmith_tracing
    catalog = synthetic_catalog()
    value = capture(fixture(catalog), catalog)
    encoded = json.dumps(value)
    assert "synthetic-dotenv-tripwire" not in encoded
    assert "synthetic-process-tripwire" not in encoded
    assert "synthetic-capture-only" not in encoded
    assert "Authorization" not in encoded
    assert "untrusted.invalid" not in encoded


def test_reject_counter_records_independent_complete_payload_and_always_refuses_count():
    value = {
        "messages": [{"role": "user", "content": "Synthetic nested input"}],
        "response_format": {"schema": {"required": ["nullable"]}},
    }
    original = copy.deepcopy(value)
    counter = RecordingRejectCounter()
    with pytest.raises(ProviderError, match="^token_count_unavailable$"):
        counter.count("chat", value)
    value["messages"][0]["content"] = "changed after capture"
    assert counter.captures[0]["payload"] == original
    with pytest.raises(ProviderError, match="^token_count_unavailable$"):
        counter.count("embedding", {})


def test_forbidden_mock_transport_still_stops_dispatch_if_counter_contract_is_broken(monkeypatch):
    def wrongly_count(self, kind, payload):
        return TokenCount(
            units=1, model=payload["model"], profile="synthetic-broken", basis="exact"
        )

    monkeypatch.setattr(RecordingRejectCounter, "count", wrongly_count)
    catalog = synthetic_catalog()
    with pytest.raises(CaptureError, match="^offline_transport_gate_reached$"):
        capture(fixture(catalog), catalog)


def test_complete_scope_reads_use_catalog_membership_without_oracle_retrieval():
    catalog = synthetic_catalog(count=2)
    value = capture(fixture(catalog, operation="read_source"), catalog)
    assert value["oracle_provenance"]["retrieval_batches"] == 0
    assert value["evidence"]["parts"][0]["admitted_scope_complete"] is True
    draft = json.loads(value["payloads"][1]["payload"]["messages"][-1]["content"])
    assert set(draft["parts"][0]["eligible_quote_chunk_ids"]) == set(catalog.chunks)
    for source in catalog.chunks.values():
        assert source.retrieval_text in draft["untrusted_candidate_rendering"]


def test_complete_scope_that_exceeds_default_assembly_cap_does_not_widen_for_capture():
    catalog = synthetic_catalog(count=17)
    value = capture(fixture(catalog, operation="read_source"), catalog)
    assert value["payload_capture_count"] == 1
    assert value["settings_caps"]["max_evidence_chunks"] == 16
    assert value["settings_caps"]["max_evidence_tokens"] == 6000
    assert value["evidence"]["parts"][0]["admitted_scope_complete"] is False
    assert value["workflow_result"]["parts"][0]["reason_code"] == "scope_incomplete"


def test_oracle_search_exceeding_real_top_k_is_rejected_not_silently_widened():
    catalog = synthetic_catalog(count=6)
    value = capture(fixture(catalog), catalog)
    assert value["payload_capture_count"] == 1
    assert value["settings_caps"]["retrieval_top_k_per_question"] == 5
    assert value["workflow_result"]["error_code"] == "retrieval_failed"
    assert value["evidence"] is None


@pytest.mark.parametrize("scenario", ["empty", "context", "excluded", "time"])
def test_nonanswerable_topologies_capture_only_planner_without_fake_draft(scenario):
    flags = ("generic_faq_specific_procedure_scope_unverified",) if scenario == "context" else ()
    catalog = synthetic_catalog(flags=flags)
    options = {"resolution": "unknown", "witness_ids": ()} if scenario == "empty" else {}
    if scenario == "context":
        options.update(intended_use="procedure_specific", resolution="unknown")
    elif scenario == "excluded":
        options.update(state="excluded")
    elif scenario == "time":
        options.update(operation="time_comparison", resolution="unknown")
    value = capture(fixture(catalog, **options), catalog)
    assert value["payload_capture_count"] == 1
    assert "generate_draft" not in value["workflow_stages"]
    assert all(not p["quotes"] for p in value["workflow_result"]["parts"])
    assert not value["draft_model_executed"]


def test_unknown_witness_fails_before_adapter_capture():
    catalog = synthetic_catalog()
    case = fixture(catalog, witness_ids=("unknown-source",))
    with pytest.raises(ValueError, match="^witness_unknown_or_duplicate$"):
        capture(case, catalog)


@pytest.mark.parametrize("option", ["--execute", "--api-key", "--endpoint", "--model"])
def test_cli_has_no_live_dispatch_credentials_or_endpoint_switches(option):
    with pytest.raises(SystemExit) as error:
        parser().parse_args(
            [
                "--cases",
                "cases.jsonl",
                "--bundle",
                "bundle",
                "--prepared-digest",
                "synthetic-prepared-digest",
                "--tokenizer",
                "tokenizer.json",
                "--output",
                "new-output",
                option,
            ]
        )
    assert error.value.code == 2


def test_existing_output_is_rejected_before_reading_cases_bundle_or_tokenizer(tmp_path):
    args = SimpleNamespace(
        output=tmp_path,
        cases=[tmp_path / "missing-cases"],
        bundle=tmp_path / "missing-bundle",
        tokenizer=tmp_path / "missing-tok",
    )
    with pytest.raises(CaptureError, match="^offline_capture_output_must_be_new$"):
        asyncio.run(prepare(args))


def test_forbidden_transport_is_a_mock_instead_of_a_real_network_client():
    forbidden = ForbiddenTransport()
    assert forbidden.transport.__class__.__name__ == "MockTransport"
    assert forbidden.attempts == 0
