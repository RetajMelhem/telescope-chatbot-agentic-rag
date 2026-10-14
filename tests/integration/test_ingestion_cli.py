"""Draft preparation CLI integrity checks using a synthetic, mocked collection."""

import asyncio
import hashlib
import json

import httpx2 as httpx
import pytest

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.cli import prepare_snapshot
from telescope_rag.ingestion.collection import CollectionManifest, collect
from telescope_rag.ingestion.models import RawPage

HTML = """<!doctype html><html><head><title>Synthetic public FAQ</title></head>
<body><main><h1>Public information</h1>
<details><summary>What are the working hours?</summary>
<p>Friday hours require checking the published notice.</p></details>
<details><summary>هل تتوفر الخدمة؟</summary><p>لا، الخدمة غير متوفرة.</p></details>
</main></body></html>"""


@pytest.fixture
def snapshot(tmp_path):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow:\n",
                headers={"Content-Type": "text/plain"},
            )
        assert request.url.path == "/faqs/"
        return httpx.Response(
            200, content=HTML.encode("utf-8"), headers={"Content-Type": "text/html"}
        )

    async def public_resolution(host):
        assert host == "telescopecenter.com"
        return ("8.8.8.8",)

    directory = tmp_path / "source-snapshot"
    manifest = asyncio.run(
        collect(
            Settings(_env_file=None, app_env="test", crawl_delay_seconds=0),
            directory,
            "synthetic-cli-snapshot",
            transport=httpx.MockTransport(handler),
            resolver=public_resolution,
            seeds=("https://telescopecenter.com/faqs/",),
        )
    )
    assert requests == [
        "https://telescopecenter.com/robots.txt",
        "https://telescopecenter.com/faqs/",
    ]
    assert manifest.coverage_complete and len(manifest.pages) == 1
    return directory


def raw_page_path(snapshot):
    return next((snapshot / "raw").glob("*.json"))


def rewrite_page_and_manifest(snapshot, page):
    raw_page_path(snapshot).write_text(page.model_dump_json(), encoding="utf-8")
    path = snapshot / "manifest.json"
    manifest = CollectionManifest.model_validate_json(path.read_bytes())
    path.write_text(
        manifest.model_copy(update={"pages": (page,)}).model_dump_json(), encoding="utf-8"
    )


def test_prepare_snapshot_produces_bound_bilingual_draft_and_unapproved_review(snapshot, tmp_path):
    output = tmp_path / "prepared"
    summary = prepare_snapshot(snapshot, output)
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    template = json.loads((output / "review-template.json").read_text(encoding="utf-8"))
    page = RawPage.model_validate_json(raw_page_path(snapshot).read_bytes())
    prepared_name = hashlib.sha256(page.document_id.encode("utf-8")).hexdigest()
    prepared = json.loads((output / f"{prepared_name}.json").read_text(encoding="utf-8"))

    assert summary["document_count"] == 1 and summary["chunk_count"] == 2
    plan = json.loads(
        (output / "metadata" / "embedding-input-plan.json").read_text(encoding="utf-8")
    )
    assert plan["prepared_digest"] == audit["prepared_digest"]
    assert plan["occurrence_count"] == 2 and plan["unique_input_count"] == 2
    assert summary["unique_embedding_inputs"] == 2
    assert summary["reused_embedding_occurrences"] == 0
    assert summary["approved"] is False and summary["embedding_ready"] is False
    assert (
        audit["collection_digest"]
        == hashlib.sha256((snapshot / "manifest.json").read_bytes()).hexdigest()
    )
    assert audit["crawl_coverage_complete"] is True
    assert audit["directory_coverage_status"] == "requires_source_review"
    assert {"token_count_unavailable", "embedding_format_unverified"} <= set(audit["gap_codes"])
    assert audit["approved"] is False and audit["token_validated_chunks"] == 0
    assert len(audit["hours"]) == 1 and audit["hours"][0]["interpretation_status"] == "unresolved"
    assert template["approved"] is False and template["source_reviewed"] is False
    assert template["collection_digest"] == audit["collection_digest"]
    assert template["prepared_digest"] == audit["prepared_digest"]
    assert prepared["document"]["page"]["html"] == HTML
    assert all(chunk["token_count"] is None for chunk in prepared["chunks"])
    assert all(chunk["embedding_ready"] is False for chunk in prepared["chunks"])
    assert "لا، الخدمة غير متوفرة." in prepared["chunks"][1]["retrieval_text"]


@pytest.mark.parametrize(
    "case, code",
    [
        ("raw_bytes", "raw_content_hash_mismatch"),
        ("decoded_html", "raw_decoded_html_mismatch"),
        ("page_json", "raw_page_manifest_mismatch"),
        ("missing_page", "raw_page_manifest_mismatch"),
        ("extra_page", "raw_page_manifest_mismatch"),
        ("snapshot", "raw_page_manifest_mismatch"),
        ("missing_html", "raw_html_missing_or_oversized"),
        ("oversized_html", "raw_html_missing_or_oversized"),
    ],
)
def test_prepare_snapshot_integrity_failure_creates_no_prepared_bundle(
    snapshot, tmp_path, case, code
):
    page_path = raw_page_path(snapshot)
    page = RawPage.model_validate_json(page_path.read_bytes())
    html_path = page_path.with_suffix(".html")
    if case == "raw_bytes":
        html_path.write_bytes(b"<main><p>Changed raw bytes.</p></main>")
    elif case == "decoded_html":
        # Both JSON copies agree, and the original bytes/hash agree. The decoded
        # extraction input must independently match those immutable original bytes.
        rewrite_page_and_manifest(snapshot, page.model_copy(update={"html": "<p>Invented.</p>"}))
    elif case == "page_json":
        page_path.write_text(
            page.model_copy(update={"html": "<p>Changed.</p>"}).model_dump_json(), encoding="utf-8"
        )
    elif case == "missing_page":
        page_path.unlink()
    elif case == "extra_page":
        (snapshot / "raw" / "extra.json").write_text(page.model_dump_json(), encoding="utf-8")
    elif case == "snapshot":
        rewrite_page_and_manifest(snapshot, page.model_copy(update={"snapshot_id": "different"}))
    elif case == "missing_html":
        html_path.unlink()
    elif case == "oversized_html":
        html_path.write_bytes(b"x" * 2_000_001)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match=f"^{code}$"):
        prepare_snapshot(snapshot, output)
    assert not output.exists()


def test_prepare_snapshot_rerun_preserves_immutable_review_bundle(snapshot, tmp_path):
    output = tmp_path / "prepared"
    prepare_snapshot(snapshot, output)
    before = {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    with pytest.raises(FileExistsError):
        prepare_snapshot(snapshot, output)
    assert {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    } == before
