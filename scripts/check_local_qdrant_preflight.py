"""Check dedicated localhost Qdrant; explicit absent-name PATCH probes cannot create data.

No provider client, embedding, candidate writer, alias operation or deletion is invoked.
"""

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.check_frozen_benchmark import verify
from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.qdrant_audit import QdrantCandidateAudit
from telescope_rag.ingestion.runner import read_secret

MANIFEST_SHA = "ee9ace13c784f6c8182ec9f9db4cf76fdc39dc24dc82ba9ad62c8c1b18dbd499"


def inspect_container(name: str) -> dict:
    result = subprocess.run(
        ["docker", "inspect", name], capture_output=True, timeout=10, check=False
    )
    if result.returncode:
        raise ValueError("local_container_inspection_failed")
    record = json.loads(result.stdout)[0]
    # Never emit Config.Env, labels containing unknown data, raw logs or credentials.
    return {
        "id": record["Id"],
        "image": record["Image"],
        "status": record["State"]["Status"],
        "networks": sorted(record["NetworkSettings"]["Networks"]),
        "ports": record["NetworkSettings"]["Ports"],
        "restart_policy": record["HostConfig"]["RestartPolicy"]["Name"],
        "user": record["Config"]["User"],
        "read_only_root": record["HostConfig"]["ReadonlyRootfs"],
        "mounts": [
            {k: m.get(k) for k in ("Type", "Name", "Source", "Destination", "RW")}
            for m in record["Mounts"]
        ],
    }


class RestrictedAudit(QdrantCandidateAudit):
    def __init__(self, settings, key, role, candidate, events, absent):
        super().__init__(settings, key)
        self.role, self.candidate, self.events, self.absent = role, candidate, events, absent

    async def _request(self, method, path, body=None, *, authenticated=True):
        if len(self.events) >= 40:
            raise ValueError("local_preflight_request_cap")
        local_collection = re.fullmatch(r"collections/telescope_public_[a-f0-9]{24}", path)
        if method == "PATCH":
            if (
                body != {}
                or not authenticated
                or path not in self.absent
                or path == f"collections/{self.candidate}"
                or not local_collection
            ):
                raise ValueError("local_preflight_mutation_not_permitted")
        elif method != "GET" or body is not None:
            raise ValueError("local_preflight_mutation_not_permitted")
        elif path not in {"", "collections", "aliases"} and not local_collection:
            raise ValueError("local_preflight_path_not_permitted")
        status, data = await super()._request(method, path, body, authenticated=authenticated)
        self.events.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "credential_role": self.role if authenticated else "none",
            }
        )
        if method == "GET" and status == 404:
            self.absent.add(path)
        return status, data


async def check(root: Path) -> dict:
    benchmark = root / "artifacts/m3-retrieval-benchmark-v1"
    frozen = verify(root, benchmark, MANIFEST_SHA)
    plan = json.loads(
        (root / "artifacts/m3-embedding-execution-preflight-v1/offline-plan.json").read_bytes()
    )
    candidate = plan["candidate"]
    db = inspect_container("telescope-m3-qdrant")
    gateway = inspect_container("telescope-m3-qdrant-gateway")
    if db["status"] != "running" or db["networks"] != ["telescope-m3-local"]:
        raise ValueError("local_database_isolation_invalid")
    old = json.loads((root / "artifacts/m3-candidate-run/local-qdrant.json").read_bytes())
    if (
        db["id"] != old["container_id"]
        or db["image"] != "sha256:" + old["image"].split("sha256:")[1]
    ):
        raise ValueError("local_database_identity_changed")
    if not any(
        m["Name"] == "telescope-m3-qdrant-storage" and m["Destination"] == "/qdrant/storage"
        for m in db["mounts"]
    ):
        raise ValueError("local_storage_identity_changed")
    if gateway["status"] != "running" or gateway["ports"] != {
        "6333/tcp": [{"HostIp": "127.0.0.1", "HostPort": "6333"}]
    }:
        raise ValueError("local_loopback_publication_invalid")
    if gateway["networks"] != ["telescope-m3-local", "telescope-m3-loopback"]:
        raise ValueError("local_gateway_networks_invalid")
    if any(m["Destination"] != "/etc/nginx/nginx.conf" or m["RW"] for m in gateway["mounts"]):
        raise ValueError("local_gateway_unexpected_mount")
    if not gateway["read_only_root"] or gateway["user"] != "101:101":
        raise ValueError("local_gateway_privileges_invalid")
    secrets = root / ".tools/qdrant-m3"
    protected = [secrets / n for n in ("admin.key", "read.key", "config.yaml")]
    fingerprints = {p: hashlib.sha256(p.read_bytes()).digest() for p in protected}
    admin_key, reader_key = read_secret(secrets / "admin.key"), read_secret(secrets / "read.key")
    settings = Settings(
        _env_file=None,
        openrouter_api_key="",
        qdrant_api_key=admin_key,
        qdrant_url="http://127.0.0.1:6333",
        provider_max_retries=0,
        provider_timeout_seconds=5,
    )
    events, absent = [], set()
    reader = RestrictedAudit(settings, reader_key, "reader", candidate, events, absent)
    admin = RestrictedAudit(settings, admin_key, "admin", candidate, events, absent)
    try:
        async with asyncio.timeout(45):
            initial = await reader.preflight(candidate, 4096, expected_version="1.19.2")
            before = await admin._ok("GET", "collections")
            if before != {"collections": []}:
                raise ValueError("local_target_not_empty")
            path = "collections/" + initial["permission_probe_collection"]
            # Same absent-target update with admin must reach the missing-collection result.
            # This distinguishes role denial from a gateway that rejects every PATCH.
            control, _ = await admin._request("PATCH", path, {})
            if control != 404:
                raise ValueError("local_admin_update_control_failed")
            missing, _ = await reader._request("GET", path)
            after = await admin._ok("GET", "collections")
            aliases_after = await reader.aliases()
            if missing != 404 or after != before or aliases_after != initial["aliases_before"]:
                raise ValueError("local_preflight_state_changed")
    finally:
        await admin.aclose()
        await reader.aclose()
    if not all(hashlib.sha256(p.read_bytes()).digest() == h for p, h in fingerprints.items()):
        raise ValueError("local_secret_or_configuration_file_changed")
    approval = json.loads(
        (
            root / "data/processed/m3-llm-semantic-token-validated-v6/metadata/review-approved.json"
        ).read_bytes()
    )
    if approval["approved"]:
        raise ValueError("original_execution_approval_changed")
    return {
        "status": "local_qdrant_preflight_passed",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "target": "http://127.0.0.1:6333",
        "database": db,
        "gateway": gateway,
        "preflight": initial,
        "admin_absent_update_control_status": control,
        "collections_before": before["collections"],
        "collections_after": after["collections"],
        "aliases_unchanged": True,
        "probe_still_absent": True,
        "keys_and_config_unchanged_during_check": True,
        "distinct_roles_verified": True,
        "events": events,
        "http_attempts": len(events),
        "permission_probe_attempts": sum(e["method"] == "PATCH" for e in events),
        "collections_created": 0,
        "points_written": 0,
        "active_alias_changed": False,
        "prepared_digest": frozen["prepared_digest"],
        "benchmark_manifest_sha256": MANIFEST_SHA,
        "source_approval_false_preserved": True,
        "paid_execution_authorized": False,
        "provider_calls": 0,
        "embedding_calls": 0,
        "dotenv_read": False,
        "limits": "Local database checks only; no paid-provider access, pricing, query/search "
        "implementation, source-policy runtime or chatbot acceptance is established.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-absent-update-probe", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.allow_absent_update_probe:
        parser.error("Explicit --allow-absent-update-probe is required; this is not GET-only.")
    if args.output.exists():
        parser.error("Use a new output path; preflight evidence is immutable.")
    root = Path(__file__).resolve().parents[1]
    result = asyncio.run(check(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "target",
                    "http_attempts",
                    "permission_probe_attempts",
                    "collections_created",
                    "points_written",
                    "distinct_roles_verified",
                    "source_approval_false_preserved",
                    "provider_calls",
                    "embedding_calls",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
