"""Observe the unchanged installed release through its verified loopback HTTP port.

Docker is inspected only. Credentials, container logs and secret file contents are
never read. Importing this module performs no Docker or network operation.
"""

import asyncio
import json
import re
import stat
import subprocess
import time
from pathlib import Path

import httpx2 as httpx

from scripts.natural_evaluation import api_payload, digest, write_new

COMMAND = [
    "python",
    "-m",
    "uvicorn",
    "telescope_rag.api.container:create_container_app",
    "--factory",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--no-access-log",
    "--no-proxy-headers",
]


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _json(path: Path) -> dict:
    _safe_path(path)
    _require(path.is_file() and path.stat().st_size <= 1_000_000, "installation_file_invalid")
    try:
        value = json.loads(path.read_bytes())
        _require(isinstance(value, dict), "installation_file_invalid")
        return value
    except (OSError, ValueError):
        raise ValueError("installation_file_invalid") from None


def _safe_path(path: Path) -> None:
    for part in (path, *path.parents):
        details = part.lstat()
        _require(
            not stat.S_ISLNK(details.st_mode)
            and not getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            "installation_path_invalid",
        )


def _safe_error(error: Exception) -> str:
    value = str(error)
    return (
        value
        if type(error) is ValueError and re.fullmatch(r"[a-z][a-z0-9_]{1,80}", value)
        else type(error).__name__
    )


def _docker(*arguments: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["docker", *arguments], capture_output=True, text=True, timeout=20, check=False
        )
        _require(result.returncode == 0, "docker_inspection_failed")
        values = json.loads(result.stdout)
        _require(isinstance(values, list), "docker_inspection_failed")
        return values
    except (OSError, ValueError, subprocess.SubprocessError):
        # Docker stderr/full inspect may contain environment values. Never expose them.
        raise ValueError("docker_inspection_failed") from None


def _same_path(value: str, expected: Path) -> bool:
    return isinstance(value, str) and Path(value).resolve() == expected.resolve()


def _environment(values: list[str]) -> dict:
    result = {}
    for item in values:
        name, separator, value = item.partition("=")
        _require(bool(separator) and name not in result, "container_environment_changed")
        result[name] = value
    return result


def _mounts(container: dict, expected: dict) -> None:
    mounts = container["Mounts"]
    _require(len(mounts) == len(expected), "container_mounts_changed")
    _require({m["Destination"] for m in mounts} == set(expected), "container_mounts_changed")
    for mount in mounts:
        kind, source, writable = expected[mount["Destination"]]
        valid_source = (
            mount.get("Name") == source if kind == "volume" else _same_path(mount["Source"], source)
        )
        _require(
            mount["Type"] == kind and mount["RW"] is writable and valid_source,
            "container_mounts_changed",
        )


def preflight(plan: dict, install_root: Path) -> dict:
    """Read installation metadata and Docker configuration; return a safe receipt."""
    try:
        _safe_path(install_root.absolute())
        root = install_root.resolve()
        owner = _json(root / "installation.json")
        state = _json(root / "current.json")
        manifest_path = root / "releases/v0.1.0/release.json"
        manifest = _json(manifest_path)
        instance = owner["instance"]
        _require(
            owner["schema_version"] == "portable-installation-v1"
            and re.fullmatch(r"telescope-portable(?:-[a-z0-9-]{1,30})?", instance) is not None
            and re.fullmatch(r"[0-9a-f]{32}", owner["id"]) is not None,
            "installation_owner_invalid",
        )
        _require(
            state["version"] == manifest["version"] == "v0.1.0"
            and manifest["schema_version"] == "portable-mvp-release-v1"
            and manifest["platform"] == "linux/amd64"
            and digest(manifest_path) == plan["release_manifest_sha256"]
            and manifest["knowledge"]["prepared_digest"] == plan["prepared_digest"]
            and state["knowledge_id"] == manifest["knowledge_id"],
            "installed_release_differs_from_plan",
        )
        images = manifest["images"]
        _require(
            state["api_image"] == images["api"]["reference"] == "telescope-rag-mvp:v0.1.0"
            and state["qdrant_image"] == images["qdrant"]["image_id"],
            "installed_image_changed",
        )
        data = root / "knowledge" / manifest["knowledge_id"]
        _require(_same_path(state["data_root"], data), "installation_data_path_changed")
        port = state["port"]
        _require(type(port) is int and 1024 <= port <= 65535, "installation_port_invalid")
        api, database = _docker("container", "inspect", f"{instance}-api", f"{instance}-qdrant")
        api_image, database_image = _docker(
            "image", "inspect", images["api"]["image_id"], images["qdrant"]["image_id"]
        )
        for container, image, category, service in (
            (api, api_image, "api", "api"),
            (database, database_image, "qdrant", "qdrant"),
        ):
            labels = container["Config"]["Labels"]
            _require(
                labels.get("telescope.installation_id") == owner["id"]
                and labels.get("com.docker.compose.project") == instance
                and labels.get("com.docker.compose.service") == service,
                "container_owner_changed",
            )
            _require(
                container["Image"] == image["Id"] == images[category]["image_id"],
                "container_image_changed",
            )
            _require(container["State"]["Running"] is True, "container_not_running")
            _require(
                not container["HostConfig"].get("ExtraHosts")
                and not container["HostConfig"].get("Dns")
                and not container["HostConfig"].get("Privileged"),
                "container_network_override_changed",
            )
            baseline = _environment(image["Config"]["Env"])
            if category == "api":
                baseline.update(APP_ENV="development", LANGSMITH_TRACING="false")
            _require(
                _environment(container["Config"]["Env"]) == baseline,
                "container_environment_changed",
            )
            _require(
                container["Config"].get("Entrypoint") == image["Config"].get("Entrypoint"),
                "container_entrypoint_changed",
            )
            if category == "qdrant":
                _require(
                    all(
                        container["Config"].get(key) == image["Config"].get(key)
                        for key in ("Cmd", "User", "WorkingDir")
                    ),
                    "database_command_changed",
                )
        config, host = api["Config"], api["HostConfig"]
        _require(config["Cmd"] == COMMAND, "container_factory_changed")
        _require(
            config["User"] == "10001:10001"
            and config["WorkingDir"] == "/app"
            and host["ReadonlyRootfs"] is True
            and not host["Privileged"]
            and host["Memory"] == 1_073_741_824
            and host["NanoCpus"] == 2_000_000_000
            and host["PidsLimit"] == 128
            and host["CapDrop"] == ["ALL"]
            and host["SecurityOpt"] == ["no-new-privileges:true"],
            "container_resources_changed",
        )
        binding = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}
        _require(
            host["PortBindings"] == binding and api["NetworkSettings"]["Ports"] == binding,
            "container_port_binding_changed",
        )
        _require(
            not database["HostConfig"].get("PortBindings")
            and not any(database["NetworkSettings"].get("Ports", {}).values()),
            "database_port_is_published",
        )
        secrets = root / "secrets"
        _mounts(
            api,
            {
                "/runtime": ("bind", data, False),
                "/run/secrets/openrouter_key": ("bind", secrets / "openrouter.key", False),
                "/run/secrets/qdrant_read_key": ("bind", secrets / "read.key", False),
            },
        )
        _mounts(
            database,
            {
                "/qdrant/storage": ("volume", state["volume"], True),
                "/qdrant/config/production.yaml": ("bind", secrets / "qdrant.yaml", False),
            },
        )
        _require(
            state["volume"] == f"{instance}-knowledge-{manifest['knowledge_id'][:24]}",
            "installation_volume_changed",
        )
        (volume,) = _docker("volume", "inspect", state["volume"])
        _require(
            volume["Labels"].get("telescope.installation_id") == owner["id"]
            and volume["Labels"].get("telescope.knowledge_id") == state["knowledge_id"],
            "installation_volume_owner_changed",
        )
        knowledge, egress = f"{instance}-knowledge", f"{instance}-egress"
        _require(
            set(api["NetworkSettings"]["Networks"]) == {knowledge, egress}
            and set(database["NetworkSettings"]["Networks"]) == {knowledge}
            and "telescope-m3-qdrant"
            in database["NetworkSettings"]["Networks"][knowledge]["Aliases"],
            "container_network_changed",
        )
        private, outbound = _docker("network", "inspect", knowledge, egress)
        _require(
            private["Name"] == knowledge
            and private["Internal"] is True
            and outbound["Name"] == egress
            and outbound["Internal"] is False,
            "container_network_changed",
        )
        return {
            "schema_version": "natural-evaluation-portable-preflight-v1",
            "status": "verified",
            "version": "v0.1.0",
            "installation_id": owner["id"],
            "instance": instance,
            "knowledge_id": manifest["knowledge_id"],
            "prepared_digest": plan["prepared_digest"],
            "release_manifest_sha256": digest(manifest_path),
            "api_container_id": api["Id"],
            "qdrant_container_id": database["Id"],
            "api_started_at": api["State"]["StartedAt"],
            "qdrant_started_at": database["State"]["StartedAt"],
            "api_image_id": api["Image"],
            "qdrant_image_id": database["Image"],
            "installation_sha256": digest(root / "installation.json"),
            "current_sha256": digest(root / "current.json"),
            "base_url": f"http://127.0.0.1:{port}",
            "internal_trace_available": False,
        }
    except (KeyError, TypeError, IndexError, OSError):
        raise ValueError("installation_configuration_invalid") from None


async def verify_http(client) -> dict:
    """Only readiness and schema GETs. No provider request is dispatched here."""
    async with asyncio.timeout(15):
        ready = await client.get("/health/ready")
        _require(
            ready.status_code == 200 and ready.json().get("status") == "ready", "api_not_ready"
        )
        response = await client.get("/openapi.json")
        _require(response.status_code == 200, "api_schema_unavailable")
        try:
            schema = response.json()
            post = schema["paths"]["/api/v1/chat"]["post"]
            components = schema["components"]["schemas"]
            properties = components["LocalChatResponse"]["properties"]
            _require(
                schema["info"]["version"] == "0.1.0"
                and post["responses"]["200"]["content"]["application/json"]["schema"]
                == {"$ref": "#/components/schemas/LocalChatResponse"}
                and post["requestBody"]["content"]["application/json"]["schema"]
                == {"$ref": "#/components/schemas/ChatRequest"}
                and properties["schema_version"]["const"] == "local-mvp-response-v1"
                and properties["mode"]["const"] == "local_mvp"
                and components["ChatRequest"]["properties"]["language"]["enum"]
                == ["auto", "ar", "en"],
                "api_schema_changed",
            )
        except (KeyError, TypeError):
            raise ValueError("api_schema_changed") from None
    return {"status": "verified", "readiness_http_status": 200, "openapi_http_status": 200}


def _client(base_url: str):
    return httpx.AsyncClient(
        base_url=base_url,
        transport=httpx.AsyncHTTPTransport(retries=0),
        timeout=155,
        follow_redirects=False,
        trust_env=False,
    )


async def _case(client, case: dict) -> dict:
    from telescope_rag.api.local import LocalChatResponse

    row = {
        "case_id": case["case_id"],
        "language": case["language"],
        "request_payload": api_payload(case),
        "http_status": None,
        "response": None,
        "error": None,
        "trace": {
            "schema_version": "natural-evaluation-http-observation-v1",
            "case_id": case["case_id"],
            "internal_trace_available": False,
            "cost": None,
        },
    }
    started = time.perf_counter()
    try:
        async with asyncio.timeout(155):
            response = await client.post("/api/v1/chat", json=row["request_payload"])
        row["http_status"] = response.status_code
        try:
            row["response"] = response.json()
        except ValueError:
            row["response_text"] = response.text
            row["error"] = "invalid_json_response"
        if response.status_code == 200 and row["error"] is None:
            try:
                LocalChatResponse.model_validate_json(response.content)
            except ValueError:
                row["error"] = "invalid_local_mvp_response"
    except asyncio.CancelledError:
        row["error"] = "CancelledError"
    except Exception as error:
        row["error"] = type(error).__name__
    row["elapsed_seconds"] = time.perf_counter() - started
    return row


async def run_portable(
    plan_dir: Path, plan: dict, install_root: Path, output: Path, requests: list[dict], limit: int
) -> list[dict]:
    """Serial, one attempt per approved case; preserve failed/partial receipts."""
    _require(type(limit) is int and 1 <= limit <= min(50, len(requests)), "invalid_case_limit")
    _require(
        len({r["case_id"] for r in requests}) == len(requests)
        and all(re.fullmatch(r"U\d{2}-(?:ar-JO|en)", r["case_id"]) for r in requests),
        "invalid_case_ids",
    )
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    rows, failure, before = [], None, None
    try:
        before = await asyncio.to_thread(preflight, plan, install_root)
        write_new(output / "preflight-before.json", before)
        async with _client(before["base_url"]) as client:
            http_receipt = await verify_http(client)
            current = await asyncio.to_thread(preflight, plan, install_root)
            _require(current == before, "installation_changed_before_first_question")
            http_receipt["runtime_unchanged_before_first_question"] = True
            write_new(output / "http-preflight.json", http_receipt)
            for case in requests[:limit]:
                row = await _case(client, case)
                write_new(output / f"{case['case_id']}.json", row)
                rows.append(row)
                if row["http_status"] != 200 or row["error"] is not None:
                    break
    except Exception as error:
        failure = _safe_error(error)
    finally:
        for name in ("preflight-before.json", "http-preflight.json"):
            if not (output / name).exists():
                write_new(output / name, {"status": "failed", "error": failure})
        try:
            after = await asyncio.to_thread(preflight, plan, install_root)
            _require(before == after, "installation_changed_during_run")
            write_new(output / "preflight-after.json", after)
        except Exception as error:
            code = _safe_error(error)
            write_new(output / "preflight-after.json", {"status": "failed", "error": code})
            failure = failure or code
        write_new(
            output / "execution-index.json",
            {
                "requested_cases": limit,
                "attempted_cases": len(rows),
                "not_attempted_case_ids": [r["case_id"] for r in requests[len(rows) : limit]],
                "case_files": [f"{r['case_id']}.json" for r in rows],
                "retries": 0,
                "status": "failed" if failure else "complete" if len(rows) == limit else "stopped",
                "error": failure,
                "plan_sha256": digest(plan_dir / "plan.json"),
                "internal_trace_available": False,
            },
        )
    if failure:
        raise ValueError(failure)
    return rows
