"""Synthetic tokenizer mechanics and sealed rebuild checks, without network or secrets."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import httpx2 as httpx
import pytest
from pydantic import ValidationError
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.admission import AdmissionPlan, UnitSelection, segment_key, unit_digest
from telescope_rag.ingestion.cli import admit_bundle
from telescope_rag.ingestion.extraction import extract_page
from telescope_rag.ingestion.models import PreparedDocument, RawPage, stable_id
from telescope_rag.ingestion.preparation import prepare_document
from telescope_rag.ingestion.review import build_audit, prepared_digest, write_bundle
from telescope_rag.ingestion.token_validation import count_admitted_bundle
from telescope_rag.providers import qwen_tokenizer as qwen
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders


@pytest.fixture
def synthetic_tokenizer(tmp_path, monkeypatch):
    # This tiny WordLevel tokenizer is NOT the production Qwen model/tokenizer.
    # Only its hash check is replaced in these tests; actual live-artifact counts
    # are recorded separately in the ignored preparation verification receipt.
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "[END]": 1, "Hello": 2}, "[UNK]"))
    tokenizer.normalizer = normalizers.NFC()
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="$A [END]", special_tokens=[("[END]", 1)]
    )
    raw = tokenizer.to_str().encode()
    path = tmp_path / "synthetic-tokenizer.json"
    path.write_bytes(raw)
    monkeypatch.setattr(qwen, "TOKENIZER_SHA256", hashlib.sha256(raw).hexdigest())
    return path


@pytest.mark.parametrize(
    "text", ["Hello", "مرحبا", "شو أوقات دوام المركز؟", "لا، الجمعة ١٠ صباحًا."]
)
def test_complete_local_count_includes_postprocessor(synthetic_tokenizer, text):
    counter = qwen.QwenPreparationCounter(synthetic_tokenizer)
    fixture = Tokenizer.from_file(str(synthetic_tokenizer))
    assert counter.count(text) == len(fixture.encode(text, add_special_tokens=False).ids) + 1
    assert counter.count(text) == len(fixture.encode(text, add_special_tokens=True).ids)
    assert not counter.receipt()["hosted_compatibility_verified"]


def test_count_does_not_inject_query_prefix(synthetic_tokenizer):
    counter = qwen.QwenPreparationCounter(synthetic_tokenizer)
    query = qwen.QUERY_PREFIX + "Hello"
    assert counter.count(query) > counter.count("Hello")
    fixture = Tokenizer.from_file(str(synthetic_tokenizer))
    assert counter.count(query) == len(fixture.encode(query).ids)


@pytest.mark.parametrize(
    "text",
    ["", "  ", None, 42, "x" * 1_000_001, "\ud800"],
    ids=["empty", "blank", "null", "integer", "oversized", "invalid-unicode"],
)
def test_invalid_count_input_is_safe(synthetic_tokenizer, text):
    counter = qwen.QwenPreparationCounter(synthetic_tokenizer)
    with pytest.raises(ValueError) as error:
        counter.count(text)
    assert str(error.value) in {"qwen_count_input_invalid", "qwen_count_failed"}


def test_changed_artifact_fails_before_loading(synthetic_tokenizer):
    synthetic_tokenizer.write_bytes(b"SECRET-like content")
    with pytest.raises(ValueError, match="^qwen_tokenizer_hash_mismatch$"):
        qwen.QwenPreparationCounter(synthetic_tokenizer)


def test_library_version_is_pinned(synthetic_tokenizer, monkeypatch):
    monkeypatch.setattr(qwen, "version", lambda name: "different")
    with pytest.raises(ValueError, match="library_mismatch"):
        qwen.QwenPreparationCounter(synthetic_tokenizer)


@pytest.mark.parametrize("setting", ["padding", "truncation"])
def test_padding_and_truncation_cannot_hide_overflow(synthetic_tokenizer, monkeypatch, setting):
    tokenizer = Tokenizer.from_file(str(synthetic_tokenizer))
    if setting == "padding":
        tokenizer.enable_padding(length=8)
    else:
        tokenizer.enable_truncation(max_length=8)
    raw = tokenizer.to_str().encode()
    synthetic_tokenizer.write_bytes(raw)
    monkeypatch.setattr(qwen, "TOKENIZER_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="padding_or_truncation"):
        qwen.QwenPreparationCounter(synthetic_tokenizer)


@pytest.mark.parametrize("role", ["query", "document"])
def test_upstream_format_cannot_authorize_hosted_dispatch(role):
    format = qwen.candidate_qwen_format()
    assert format.document_prefix == "" and format.query_prefix == qwen.QUERY_PREFIX
    assert not format.verified
    with pytest.raises(ProviderError) as error:
        format.format("original", role)
    assert error.value.code == "embedding_format_unverified"


def wire_payload():
    return {
        "model": qwen.QWEN_MODEL,
        "input": [qwen.QUERY_PREFIX + "Hello"],
        "dimensions": 4096,
        "encoding_format": "float",
        "provider": {
            "only": ["deepinfra/us"],
            "require_parameters": True,
            "allow_fallbacks": False,
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        "model",
        "dimensions",
        "float_dimensions",
        "encoding",
        "route",
        "fallbacks",
        "numeric_flag",
        "extra",
        "empty",
        "nontext",
        "oversized_batch",
    ],
)
def test_payload_counter_rejects_changed_hosted_contract(synthetic_tokenizer, change):
    payload = wire_payload()
    if change == "model":
        payload["model"] = "other"
    elif change == "dimensions":
        payload["dimensions"] = 2048
    elif change == "float_dimensions":
        payload["dimensions"] = 4096.0
    elif change == "encoding":
        payload["encoding_format"] = "base64"
    elif change == "route":
        payload["provider"]["only"] = ["other"]
    elif change == "fallbacks":
        payload["provider"]["allow_fallbacks"] = True
    elif change == "numeric_flag":
        payload["provider"]["require_parameters"] = 1
    elif change == "extra":
        payload["input_type"] = "search_query"
    elif change == "empty":
        payload["input"] = []
    elif change == "nontext":
        payload["input"] = [42]
    else:
        payload["input"] = ["Hello"] * 33
    counter = qwen.QwenEmbeddingCounter(synthetic_tokenizer)
    with pytest.raises(ProviderError):
        counter.count("embedding", payload)


def test_payload_counter_counts_formatted_inputs_and_refuses_chat(synthetic_tokenizer):
    payload = wire_payload()
    payload["input"].append("مرحبا")
    counter = qwen.QwenEmbeddingCounter(synthetic_tokenizer)
    actual = counter.count("embedding", payload)
    fixture = Tokenizer.from_file(str(synthetic_tokenizer))
    assert actual.units == sum(len(fixture.encode(t).ids) for t in payload["input"])
    assert actual.basis == "exact" and actual.model == qwen.QWEN_MODEL
    with pytest.raises(ProviderError) as error:
        counter.count("chat", {})
    assert error.value.code == "token_count_unavailable"


@pytest.mark.parametrize("reported", [qwen.QWEN_MODEL, "Qwen/Qwen3-Embedding-8B", "other"])
def test_hosted_route_and_explicit_model_identifier_validation(synthetic_tokenizer, reported):
    settings = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-key")
    counter = qwen.QwenEmbeddingCounter(synthetic_tokenizer)
    observed = []

    def handler(request):
        payload = json.loads(request.content)
        observed.append(payload)
        assert payload == wire_payload()
        return httpx.Response(
            200,
            json={
                "model": reported,
                "provider": "DeepInfra",
                "usage": {"prompt_tokens": counter.count("embedding", payload).units},
                "data": [{"index": 0, "embedding": [1.0] + [0.0] * 4095}],
            },
        )

    async def run():
        budget = ExecutionBudget(settings)
        async with OpenRouterProviders(
            settings, token_counter=counter, transport=httpx.MockTransport(handler)
        ) as providers:
            if reported == "other":
                with pytest.raises(ProviderError) as error:
                    await providers.embeddings.embed(
                        ["Hello"], role="query", format=qwen.hosted_qwen_format(), budget=budget
                    )
                assert error.value.code == "reported_model_mismatch"
            else:
                result = await providers.embeddings.embed(
                    ["Hello"], role="query", format=qwen.hosted_qwen_format(), budget=budget
                )
                assert result.receipts[0].reported_model == reported
                assert result.receipts[0].requested_model == qwen.QWEN_MODEL
                assert result.dimensions == 4096
        assert len(observed) == 1

    asyncio.run(run())


def test_model_mapping_requires_pinned_route():
    from telescope_rag.providers.contracts import EmbeddingFormat

    with pytest.raises(ValidationError):
        EmbeddingFormat(
            version="synthetic", verified=True, reported_model="Qwen/Qwen3-Embedding-8B"
        )


@pytest.fixture
def admitted_bundle(tmp_path):
    html = (
        "<main><h1>Synthetic information</h1><section class='doctor-profile'>"
        "<h2>Dr. Example</h2><p>Literal specialty.</p></section>"
        "<details><summary>هل تتوفر الخدمة؟</summary>"
        "<p>لا، الخدمة غير متوفرة يوم الجمعة.</p></details></main>"
    )
    page = RawPage(
        snapshot_id="synthetic-count",
        document_id="synthetic-doc",
        canonical_url="https://telescopecenter.com/synthetic-count/",
        fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
        html=html,
        content_hash=stable_id(html),
    )
    document = prepare_document(extract_page(page))
    audit = build_audit(
        (document,),
        snapshot_id=page.snapshot_id,
        collection_digest="synthetic-collection",
        crawl_coverage_confirmed=True,
    )
    original = tmp_path / "original"
    write_bundle(original, (document,), audit)
    plan = AdmissionPlan(
        snapshot_id=page.snapshot_id,
        collection_digest=audit.collection_digest,
        input_prepared_digest=audit.prepared_digest,
        decision_authority="Synthetic reviewer",
        decision_notes=("Synthetic source decisions only.",),
        primary_directory_document_ids=(page.document_id,),
        units=tuple(
            UnitSelection(
                document_id=page.document_id,
                unit_id=u.unit_id,
                unit_digest=unit_digest(u),
                disposition="retain",
                segment_keys=tuple(segment_key(s) for s in u.segments),
                context_keys=tuple(segment_key(s) for s in u.context),
                section_path=u.section_path,
                reason="synthetic_retention",
            )
            for u in document.document.units
        ),
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    admitted = tmp_path / "admitted"
    admit_bundle(original, plan_path, admitted)
    return admitted


def documents(bundle):
    return tuple(
        PreparedDocument.model_validate_json(p.read_bytes())
        for p in sorted(bundle.glob("*.json"))
        if p.name not in {"audit.json", "summary.json", "review-template.json"}
    )


def test_counted_rebuild_preserves_source_and_stays_unapproved(
    admitted_bundle, synthetic_tokenizer, tmp_path
):
    before = {p: p.read_bytes() for p in admitted_bundle.rglob("*.json")}
    output = tmp_path / "counted"
    summary = count_admitted_bundle(admitted_bundle, output, synthetic_tokenizer)
    original, counted = documents(admitted_bundle), documents(output)
    assert [d.document for d in original] == [d.document for d in counted]
    assert before == {p: p.read_bytes() for p in admitted_bundle.rglob("*.json")}
    chunks = [c for d in counted for c in d.chunks]
    counter = qwen.QwenPreparationCounter(synthetic_tokenizer)
    assert chunks and all(
        0 < c.token_count == counter.count(c.retrieval_text) <= 1200 for c in chunks
    )
    assert all(not c.embedding_ready and c.embedding_format_hash is None for c in chunks)
    assert not summary["approved"] and not summary["embedding_ready"]
    assert summary["gap_codes"] == ["embedding_format_unverified"]
    receipt = json.loads((output / "metadata/token-count-receipt.json").read_bytes())
    assert receipt["input_prepared_digest"] == prepared_digest(original)
    assert receipt["output_prepared_digest"] == prepared_digest(counted)
    directory = json.loads((output / "metadata/primary-directory.json").read_bytes())
    assert directory["prepared_digest"] == prepared_digest(counted)
    valid_ids = {c.chunk_id for c in chunks}
    assert all(
        set(e["chunk_ids"]) <= valid_ids
        for p in directory["pages"]
        for es in p["entries"].values()
        for e in es
    )
    review = json.loads((output / "review-template.json").read_bytes())
    assert review["source_reviewed"] and not review["approved"]
    assert "لا، الخدمة غير متوفرة يوم الجمعة." in "\n".join(c.retrieval_text for c in chunks)
    with pytest.raises(ValueError, match="output_exists"):
        count_admitted_bundle(admitted_bundle, output, synthetic_tokenizer)


def test_verified_hosted_profile_produces_ready_but_unapproved_bundle(
    admitted_bundle, synthetic_tokenizer, tmp_path
):
    output = tmp_path / "hosted-counted"
    summary = count_admitted_bundle(
        admitted_bundle, output, synthetic_tokenizer, profile="openrouter-deepinfra-v1"
    )
    assert summary["embedding_ready"] and not summary["approved"]
    assert not summary["gap_codes"]
    chunks = [c for d in documents(output) for c in d.chunks]
    assert all(c.embedding_ready and c.embedding_format_hash for c in chunks)
    format = qwen.hosted_qwen_format()
    assert all(
        c.embedding_format_hash == stable_id("embedding-format-v1", format.model_dump_json())
        for c in chunks
    )


@pytest.mark.parametrize("change", ["source", "review", "receipt", "plan", "audit"])
def test_changed_sealed_input_fails_before_creating_output(
    admitted_bundle, synthetic_tokenizer, tmp_path, change
):
    if change == "source":
        path = next(p for p in admitted_bundle.glob("*.json") if len(p.stem) == 64)
        value = json.loads(path.read_bytes())
        value["document"]["title"] = "Changed"
    else:
        name = {
            "review": "review-template.json",
            "receipt": "metadata/source-admission-receipt.json",
            "plan": "metadata/source-admission-plan.json",
            "audit": "audit.json",
        }[change]
        path = admitted_bundle / name
        value = json.loads(path.read_bytes())
        if change == "review":
            value["source_reviewed"] = False
        elif change == "receipt":
            value["policy_hash"] = "changed"
        elif change == "plan":
            value["decision_authority"] = "changed"
        else:
            value["chunk_count"] += 1
    path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "counted"
    with pytest.raises(ValueError, match="source_binding_invalid"):
        count_admitted_bundle(admitted_bundle, output, synthetic_tokenizer)
    assert not output.exists()
