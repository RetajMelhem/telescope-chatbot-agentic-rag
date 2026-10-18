"""Installed HTTP boundary tests: fake Docker and MockTransport only."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from fastapi import FastAPI

from scripts import natural_evaluation_portable as portable
from scripts.natural_evaluation import digest, write_new
from telescope_rag.api.routes.local_chat import router


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "installation"
    (root / "releases/v0.1.0").mkdir(parents=True)
    owner = {
        "schema_version": "portable-installation-v1",
        "instance": "telescope-portable",
        "id": "a" * 32,
    }
    manifest = {
        "schema_version": "portable-mvp-release-v1",
        "version": "v0.1.0",
        "platform": "linux/amd64",
        "knowledge_id": "b" * 64,
        "knowledge": {"prepared_digest": "c" * 64},
        "images": {
            "api": {"reference": "telescope-rag-mvp:v0.1.0", "image_id": "sha256:" + "d" * 64},
            "qdrant": {
                "reference": "qdrant/qdrant@sha256:" + "e" * 64,
                "image_id": "sha256:" + "e" * 64,
            },
        },
    }
    state = {
        "version": "v0.1.0",
        "knowledge_id": manifest["knowledge_id"],
        "data_root": str(root / "knowledge" / manifest["knowledge_id"]),
        "volume": f"telescope-portable-knowledge-{'b' * 24}",
        "port": 8123,
        "api_image": manifest["images"]["api"]["reference"],
        "qdrant_image": manifest["images"]["qdrant"]["image_id"],
    }
    for path, value in (
        (root / "installation.json", owner),
        (root / "current.json", state),
        (root / "releases/v0.1.0/release.json", manifest),
    ):
        write_new(path, value)
    images = [
        {
            "Id": manifest["images"][name]["image_id"],
            "Config": {"Env": ["PATH=/app/.venv/bin:/usr/bin"], "Entrypoint": None},
        }
        for name in ("api", "qdrant")
    ]
    knowledge, egress = "telescope-portable-knowledge", "telescope-portable-egress"
    binding = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8123"}]}

    def mount(destination, source, *, writable=False, volume=False):
        return {
            "Destination": destination,
            "Source": str(source),
            "Name": str(source),
            "RW": writable,
            "Type": "volume" if volume else "bind",
        }

    containers = []
    for index, name in enumerate(("api", "qdrant")):
        containers.append(
            {
                "Id": str(index + 1) * 64,
                "Image": images[index]["Id"],
                "State": {"Running": True, "StartedAt": "2026-10-18T00:00:00Z"},
                "Config": {
                    "Env": images[index]["Config"]["Env"].copy(),
                    "Entrypoint": None,
                    "Cmd": portable.COMMAND.copy() if name == "api" else None,
                    "User": "10001:10001" if name == "api" else None,
                    "WorkingDir": "/app" if name == "api" else None,
                    "Labels": {
                        "telescope.installation_id": owner["id"],
                        "com.docker.compose.project": owner["instance"],
                        "com.docker.compose.service": name,
                    },
                },
                "HostConfig": {
                    "ReadonlyRootfs": True,
                    "Privileged": False,
                    "Memory": 1_073_741_824,
                    "NanoCpus": 2_000_000_000,
                    "PidsLimit": 128,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PortBindings": binding if name == "api" else {},
                },
                "NetworkSettings": {
                    "Ports": binding if name == "api" else {"6333/tcp": None},
                    "Networks": {
                        knowledge: {"Aliases": ["telescope-m3-qdrant"]},
                        **({egress: {"Aliases": []}} if name == "api" else {}),
                    },
                },
                "Mounts": [],
            }
        )
    containers[0]["Config"]["Env"] += ["APP_ENV=development", "LANGSMITH_TRACING=false"]
    containers[0]["Mounts"] = [
        mount("/runtime", state["data_root"]),
        mount("/run/secrets/openrouter_key", root / "secrets/openrouter.key"),
        mount("/run/secrets/qdrant_read_key", root / "secrets/read.key"),
    ]
    containers[1]["Mounts"] = [
        mount("/qdrant/storage", state["volume"], writable=True, volume=True),
        mount("/qdrant/config/production.yaml", root / "secrets/qdrant.yaml"),
    ]
    networks = [{"Name": knowledge, "Internal": True}, {"Name": egress, "Internal": False}]
    volume = {
        "Labels": {
            "telescope.installation_id": owner["id"],
            "telescope.knowledge_id": state["knowledge_id"],
        }
    }
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return deepcopy(
            {"container": containers, "image": images, "network": networks, "volume": [volume]}[
                arguments[0]
            ]
        )

    monkeypatch.setattr(portable, "_docker", docker)
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    plan = {
        "release_manifest_sha256": digest(root / "releases/v0.1.0/release.json"),
        "prepared_digest": manifest["knowledge"]["prepared_digest"],
    }
    write_new(plan_dir / "plan.json", plan)
    return SimpleNamespace(
        root=root,
        plan=plan,
        plan_dir=plan_dir,
        state=state,
        images=images,
        containers=containers,
        networks=networks,
        volume=volume,
        calls=calls,
    )


def test_preflight_derives_loopback_endpoint_without_reading_credentials(installation):
    receipt = portable.preflight(installation.plan, installation.root)
    assert receipt["status"] == "verified"
    assert receipt["base_url"] == "http://127.0.0.1:8123"
    assert receipt["internal_trace_available"] is False
    assert not (installation.root / "secrets").exists()
    assert {c[0] for c in installation.calls} == {"container", "image", "volume", "network"}
    assert all(c[1] == "inspect" for c in installation.calls)


@pytest.mark.parametrize(
    "change,code",
    [
        ("image", "container_image_changed"),
        ("owner", "container_owner_changed"),
        ("env", "container_environment_changed"),
        ("tracing", "container_environment_changed"),
        ("factory", "container_factory_changed"),
        ("data", "container_mounts_changed"),
        ("writable_data", "container_mounts_changed"),
        ("public_api", "container_port_binding_changed"),
        ("public_database", "database_port_is_published"),
        ("network", "container_network_changed"),
        ("volume_owner", "installation_volume_owner_changed"),
        ("resources", "container_resources_changed"),
        ("dns", "container_network_override_changed"),
    ],
)
def test_preflight_refuses_different_runtime_before_any_http(installation, change, code):
    api, database = installation.containers
    if change == "image":
        api["Image"] = "sha256:" + "f" * 64
    elif change == "owner":
        api["Config"]["Labels"]["telescope.installation_id"] = "wrong"
    elif change == "env":
        api["Config"]["Env"].append("OPENROUTER_API_KEY=synthetic-private-marker")
    elif change == "tracing":
        api["Config"]["Env"][-1] = "LANGSMITH_TRACING=true"
    elif change == "factory":
        api["Config"]["Cmd"] = ["python", "-m", "other"]
    elif change == "data":
        api["Mounts"][0]["Source"] = str(installation.root / "other")
    elif change == "writable_data":
        api["Mounts"][0]["RW"] = True
    elif change == "public_api":
        api["HostConfig"]["PortBindings"]["8000/tcp"][0]["HostIp"] = "0.0.0.0"
    elif change == "public_database":
        database["NetworkSettings"]["Ports"]["6333/tcp"] = [
            {"HostIp": "0.0.0.0", "HostPort": "6333"}
        ]
    elif change == "network":
        installation.networks[0]["Internal"] = False
    elif change == "volume_owner":
        installation.volume["Labels"]["telescope.installation_id"] = "wrong"
    elif change == "resources":
        api["HostConfig"]["Memory"] = 2_000_000_000
    elif change == "dns":
        api["HostConfig"]["ExtraHosts"] = ["telescope-m3-qdrant:198.51.100.1"]
    with pytest.raises(ValueError, match=f"^{code}$") as raised:
        portable.preflight(installation.plan, installation.root)
    assert "synthetic-private-marker" not in str(raised.value)


@pytest.mark.parametrize(
    "field,value",
    [("version", "v0.2.0"), ("knowledge_id", "f" * 64), ("data_root", "other"), ("port", "8000")],
)
def test_changed_installation_state_is_rejected(installation, field, value):
    installation.state[field] = value
    (installation.root / "current.json").write_text(
        json.dumps(installation.state), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        portable.preflight(installation.plan, installation.root)
    assert installation.calls == []


def test_docker_failure_never_exposes_full_inspect_or_stderr(monkeypatch):
    def run(arguments, **kwargs):
        assert arguments == ["docker", "container", "inspect", "example"]
        assert kwargs["capture_output"] and kwargs["timeout"] == 20
        return SimpleNamespace(
            returncode=1, stdout="synthetic-private-marker", stderr="synthetic-private-marker"
        )

    monkeypatch.setattr(portable.subprocess, "run", run)
    with pytest.raises(ValueError, match="^docker_inspection_failed$"):
        portable._docker("container", "inspect", "example")


def schema():
    app = FastAPI(version="0.1.0")
    app.include_router(router)
    return app.openapi()


def answer(language="en"):
    return {
        "schema_version": "local-mvp-response-v1",
        "mode": "local_mvp",
        "answer_style": "conversational",
        "request_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
        "answer": "Unknown",
        "answer_format": "plain_text",
        "language": language,
        "questions": [
            {
                "id": "q1",
                "question": "Question?",
                "status": "unknown",
                "answer": "Unknown",
                "citation_ids": [],
                "reason_code": None,
                "admitted_scope_complete": None,
                "hours": None,
            }
        ],
        "citations": [],
        "unresolved_questions": ["q1"],
        "knowledge": None,
    }


def mock_http(monkeypatch, *, post_status=200, invalid=False, get_status=200, hook=None):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/health/ready":
            return httpx.Response(get_status, json={"status": "ready"})
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json=schema())
        if hook:
            hook()
        payload = json.loads(request.content)
        body = (
            {"error": "synthetic"} if invalid or post_status != 200 else answer(payload["language"])
        )
        return httpx.Response(post_status, json=body)

    monkeypatch.setattr(
        portable,
        "_client",
        lambda base_url: httpx.AsyncClient(
            base_url=base_url,
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
            trust_env=False,
        ),
    )
    return seen


def questions():
    return [
        {"case_id": "U01-ar-JO", "language": "ar-JO", "query": "اعطيني رقمكم", "history": []},
        {
            "case_id": "U01-en",
            "language": "en",
            "query": "What's your phone number?",
            "history": [],
        },
    ]


def execute(installation, output):
    return asyncio.run(
        portable.run_portable(
            installation.plan_dir, installation.plan, installation.root, output, questions(), 2
        )
    )


def test_actual_http_shape_maps_arabic_and_retains_honest_observations(
    installation, tmp_path, monkeypatch
):
    seen = mock_http(monkeypatch)
    output = tmp_path / "run"
    rows = execute(installation, output)
    assert [r.method for r in seen] == ["GET", "GET", "POST", "POST"]
    assert all(str(r.url).startswith("http://127.0.0.1:8123/") for r in seen)
    assert json.loads(seen[2].content) == {"query": "اعطيني رقمكم", "language": "ar", "history": []}
    assert rows[0]["language"] == "ar-JO" and rows[0]["error"] is None
    assert rows[0]["trace"] == {
        "schema_version": "natural-evaluation-http-observation-v1",
        "case_id": "U01-ar-JO",
        "internal_trace_available": False,
        "cost": None,
    }
    assert json.loads((output / "execution-index.json").read_bytes())["status"] == "complete"
    assert digest(output / "preflight-before.json") == digest(output / "preflight-after.json")
    with pytest.raises(FileExistsError):
        execute(installation, output)
    assert len(seen) == 4


@pytest.mark.parametrize("status,invalid", [(503, False), (200, True)])
def test_error_is_saved_and_stops_without_repeat(
    installation, tmp_path, monkeypatch, status, invalid
):
    seen = mock_http(monkeypatch, post_status=status, invalid=invalid)
    output = tmp_path / "run"
    rows = execute(installation, output)
    assert len(rows) == 1 and [r.method for r in seen].count("POST") == 1
    assert rows[0]["http_status"] == status and rows[0]["response"] == {"error": "synthetic"}
    if invalid:
        assert rows[0]["error"] == "invalid_local_mvp_response"
    index = json.loads((output / "execution-index.json").read_bytes())
    assert index["not_attempted_case_ids"] == ["U01-en"] and index["retries"] == 0


def test_readiness_failure_preserves_receipts_without_post(installation, tmp_path, monkeypatch):
    seen = mock_http(monkeypatch, get_status=503)
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="api_not_ready"):
        execute(installation, output)
    assert [r.method for r in seen] == ["GET"]
    assert json.loads((output / "execution-index.json").read_bytes())["attempted_cases"] == 0
    assert json.loads((output / "http-preflight.json").read_bytes())["status"] == "failed"


def test_container_drift_after_dispatch_preserves_partial_results_and_fails_binding(
    installation, tmp_path, monkeypatch
):
    def drift():
        installation.containers[0]["State"]["StartedAt"] = "2026-10-18T01:00:00Z"

    seen = mock_http(monkeypatch, post_status=503, hook=drift)
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="installation_changed_during_run"):
        execute(installation, output)
    assert len([r for r in seen if r.method == "POST"]) == 1
    assert (output / "U01-ar-JO.json").is_file()
    assert json.loads((output / "preflight-after.json").read_bytes())["status"] == "failed"


def test_preflight_failure_retains_safe_failed_receipts(installation, tmp_path, monkeypatch):
    installation.containers[0]["Config"]["Env"].append("EXTRA=synthetic-private-marker")
    seen = mock_http(monkeypatch)
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="container_environment_changed"):
        execute(installation, output)
    assert seen == []
    saved = "".join(path.read_text("utf-8") for path in output.glob("*.json"))
    assert "synthetic-private-marker" not in saved and "container_environment_changed" in saved


def test_wrong_api_schema_blocks_every_post(installation, tmp_path, monkeypatch):
    wrong = schema()
    wrong["paths"]["/api/v1/chat"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "#/components/schemas/OfflineChatResponse"}
    monkeypatch.setattr(__import__(__name__, fromlist=["schema"]), "schema", lambda: wrong)
    seen = mock_http(monkeypatch)
    with pytest.raises(ValueError, match="api_schema_changed"):
        execute(installation, tmp_path / "run")
    assert [r.method for r in seen] == ["GET", "GET"]


def test_recheck_immediately_before_first_question_blocks_changed_container(
    installation, tmp_path, monkeypatch
):
    original = portable.verify_http

    async def ready_then_changed(client):
        receipt = await original(client)
        installation.containers[0]["Id"] = "9" * 64
        return receipt

    monkeypatch.setattr(portable, "verify_http", ready_then_changed)
    seen = mock_http(monkeypatch)
    with pytest.raises(ValueError, match="installation_changed_before_first_question"):
        execute(installation, tmp_path / "run")
    assert [r.method for r in seen] == ["GET", "GET"]


@pytest.mark.parametrize("error", [httpx.ReadTimeout, asyncio.CancelledError])
def test_unknown_dispatch_failure_is_saved_once_without_retry(
    installation, tmp_path, monkeypatch, error
):
    def fail_dispatch():
        raise error("synthetic-private-marker")

    seen = mock_http(monkeypatch, hook=fail_dispatch)
    output = tmp_path / "run"
    rows = execute(installation, output)
    assert len(rows) == 1 and [r.method for r in seen].count("POST") == 1
    assert rows[0]["error"] == error.__name__ and rows[0]["http_status"] is None
    assert "synthetic-private-marker" not in (output / "U01-ar-JO.json").read_text("utf-8")
