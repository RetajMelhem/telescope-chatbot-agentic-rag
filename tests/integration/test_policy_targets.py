"""Policy profile contracts and joint-owner evidence mechanics, not LLM accuracy."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_luna_planner_screen import preparation
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, source

from scripts import run_policy_target_screen as screen
from scripts.run_luna_planner_screen import development_packets
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.providers.openrouter import OpenRouterProviders


def test_candidate_changes_only_version_and_instructions_in_planner_wire():
    _, baseline = preparation("answer_targets")
    _, candidate = preparation("policy_targets")
    for old, new in zip(baseline, candidate, strict=True):
        a, b = old["payload"], new["payload"]
        assert {k: v for k, v in a.items() if k != "messages"} == {
            k: v for k, v in b.items() if k != "messages"
        }
        old_body, new_body = (json.loads(p["messages"][-1]["content"]) for p in (a, b))
        assert old_body.pop("prompt_version") != new_body.pop("prompt_version")
        assert old_body == new_body
        assert a["messages"][0] != b["messages"][0]


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Compare Synthetic Doctor A and Synthetic Doctor B, using the main directory."),
        ("ar", "قارن الطبيب التجريبي أ والطبيب التجريبي ب باستخدام الدليل الرئيسي."),
        ("ar-JO", "قارنلي الطبيب التجريبي أ والطبيب التجريبي ب من الدليل الرئيسي."),
    ],
)
def test_joint_comparison_keeps_same_field_doctors_and_citations_distinct(language, query):
    async def run():
        items = tuple(
            source(
                i,
                "Synthetic shared field.",
                document="main",
                doctor_id=f"doctor-{i}",
                doctor_name=f"Synthetic Doctor {i}",
            )
            for i in (1, 2)
        )
        evidence = catalog(*items)
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: tuple(s.chunk_id for s in items))

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            if payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply":
                reply = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            query,
                            intended_use="doctor_role",
                            source_language="en",
                            document_handles=(body["source_manifest"]["documents"][0]["handle"],),
                        ),
                    ),
                )
            else:
                assert len(body["parts"]) == 1
                assert set(body["parts"][0]["eligible_quote_chunk_ids"]) == {
                    s.chunk_id for s in items
                }
                reply = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            reason_code=None,
                            quotes=tuple(
                                QuoteDraft(chunk_id=s.chunk_id, quote=s.retrieval_text)
                                for s in items
                            ),
                        ),
                    )
                )
            return wire(reply)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            run = await OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="policy_targets",
            ).run(WorkflowRequest(query=query, language="ar" if language == "ar-JO" else language))
        assert run.result.outcome == "draft_ready"
        assert len(run.answer_targets) == 1 and len(run.evidence.groups) == 2
        assert [q.literal_owner_id for q in run.result.parts[0].quotes] == ["doctor-1", "doctor-2"]
        assert not run.result.semantic_grounding_verified

    asyncio.run(run())


def fixture(root):
    directory = root / screen.CASES
    directory.mkdir(parents=True)
    cases = [
        {
            "case_id": f"N{i:02}-{lang}",
            "request": {
                "query": f"Synthetic question {i} {lang}.",
                "history": [],
                "language": "en",
            },
            "criteria": "secret gold criterion",
            "witness": "secret-gold-witness",
        }
        for i in range(1, 5)
        for lang in ("ar", "ar-JO", "en")
    ]
    (directory / "cases.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps({"files": {"cases.json": screen.file_hash(directory / "cases.json")}}),
        encoding="utf-8",
    )
    return directory, screen.file_hash(directory / "manifest.json")


def test_new_cases_export_no_gold_or_case_ids(tmp_path, monkeypatch):
    _, digest = fixture(tmp_path)
    monkeypatch.setattr(screen, "MANIFEST_SHA256", digest)
    cases = screen.frozen_cases(tmp_path)
    bindings, _ = preparation("policy_targets")
    ids = tuple(c.case_id for c in cases)
    packets = development_packets(
        cases, bindings, profile="policy_targets", output_cap=4096, case_ids=ids, inventory=ids
    )
    assert len(packets) == 12
    for packet in packets:
        body = json.dumps(packet["payload"])
        assert "secret gold" not in body and "secret-gold" not in body
        assert packet["case_id"] not in body


@pytest.mark.parametrize("tamper", ["manifest", "cases", "inventory", "escape"])
def test_frozen_contrast_tampering_stops_before_dispatch(tmp_path, monkeypatch, tamper):
    directory, digest = fixture(tmp_path)
    if tamper in {"manifest", "cases"}:
        (directory / f"{tamper}.json").write_text("{}", encoding="utf-8")
    else:
        if tamper == "inventory":
            rows = json.loads((directory / "cases.json").read_bytes())
            rows["cases"][0]["case_id"] = "PL02-en"
            (directory / "cases.json").write_text(json.dumps(rows), encoding="utf-8")
            files = {"cases.json": screen.file_hash(directory / "cases.json")}
        else:
            files = {"../outside.json": "untrusted"}
        (directory / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        digest = screen.file_hash(directory / "manifest.json")
    monkeypatch.setattr(screen, "MANIFEST_SHA256", digest)
    with pytest.raises(ValueError, match="policy_.*changed"):
        screen.frozen_cases(tmp_path)
