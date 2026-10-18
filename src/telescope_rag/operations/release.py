"""Versioned portable assets and isolated recovery checks; no model calls."""

import argparse
import hashlib
import io
import json
import re
import stat
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telescope_rag.api.local import (
    COLLECTION,
    HOURS_DIGEST,
    PREPARED_DIGEST,
    TOKENIZER_REVISION,
    load_resources,
)
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.qwen_tokenizer import TOKENIZER_SHA256

QDRANT_IMAGE = (
    "qdrant/qdrant@sha256:b7b0444c4c351c970b98e90a6f89c2ee4287c65b44e52b4cb503fa5b2aa927ad"
)
BUNDLE = "data/processed/m3-execution-approved-v6-v2/"
METADATA = "data/processed/m3-llm-semantic-token-validated-v6/metadata/"
TOKENIZER = f".tools/qwen-tokenizer/{TOKENIZER_REVISION}/"
PLANS = (
    "artifacts/m5-public-hours-v1/reviewed-hours-plan.json",
    "artifacts/public-website-links-v1/reviewed-links-plan.json",
)
CACHE = "data/processed/m4-query-cache-v1/"  # Empty runtime directory, never cached queries.
REQUIRED = (
    *PLANS,
    METADATA + "source-admission-plan.json",
    METADATA + "primary-directory.json",
    BUNDLE + "audit.json",
    BUNDLE + "metadata/review-approved.json",
    BUNDLE + "metadata/embedding-configuration.json",
    TOKENIZER + "tokenizer.json",
    TOKENIZER + "LICENSE",
)
Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_UNPACKED = 600_000_000


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def allowed_path(name: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", name) or "\\" in name:
        return False
    parts = PurePosixPath(name).parts
    if name != PurePosixPath(name).as_posix() or any(p in {"..", "."} for p in parts):
        return False
    if name in REQUIRED:
        return True
    return bool(re.fullmatch(re.escape(BUNDLE) + r"[0-9a-f]{64}\.json", name))


def not_link(path: Path) -> None:
    details = path.lstat()
    if path.is_symlink() or getattr(details, "st_file_attributes", 0) & 0x400:
        raise ValueError("release_reparse_path_refused")


class FileEntry(Record):
    path: str
    sha256: Hex
    bytes: int = Field(ge=0, le=20_000_000)

    @model_validator(mode="after")
    def safe_path(self) -> "FileEntry":
        if not allowed_path(self.path):
            raise ValueError("release_path_not_allowed")
        return self


class Database(Record):
    collection: Literal[COLLECTION] = COLLECTION
    version: Literal["1.19.2"] = "1.19.2"
    points: int = Field(ge=1, le=10000)
    points_sha256: Hex
    config: dict
    aliases: tuple[str, ...] = ()


class Knowledge(Record):
    prepared_digest: Literal[PREPARED_DIGEST] = PREPARED_DIGEST
    tokenizer_sha256: Literal[TOKENIZER_SHA256] = TOKENIZER_SHA256
    files: tuple[FileEntry, ...] = Field(min_length=1, max_length=1000)
    database: Database

    @model_validator(mode="after")
    def unique_inventory(self) -> "Knowledge":
        paths = [f.path for f in self.files]
        if paths != sorted(paths) or len({p.casefold() for p in paths}) != len(paths):
            raise ValueError("release_inventory_invalid")
        if sum(f.bytes for f in self.files) > MAX_UNPACKED:
            raise ValueError("release_inventory_too_large")
        return self

    @property
    def identity(self) -> str:
        return digest(self.model_dump(mode="json"))


class Asset(Record):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,100}$")
    sha256: Hex
    bytes: int = Field(ge=1, lt=2 * 1024**3)


class Image(Record):
    reference: str
    image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class Release(Record):
    schema_version: Literal["portable-mvp-release-v1"] = "portable-mvp-release-v1"
    version: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    platform: Literal["linux/amd64"] = "linux/amd64"
    knowledge_id: Hex
    knowledge: Knowledge
    assets: dict[Literal["knowledge", "database", "api", "qdrant"], Asset]
    images: dict[Literal["api", "qdrant"], Image]

    @model_validator(mode="after")
    def binding(self) -> "Release":
        if (
            self.knowledge_id != self.knowledge.identity
            or set(self.assets) != {"knowledge", "database", "api", "qdrant"}
            or set(self.images) != {"api", "qdrant"}
            or self.images["api"].reference != f"telescope-rag-mvp:{self.version}"
            or self.images["qdrant"].reference != QDRANT_IMAGE
            or len({a.name.casefold() for a in self.assets.values()}) != 4
        ):
            raise ValueError("release_binding_invalid")
        return self


def read_release(path: Path) -> Release:
    if path.stat().st_size > 1_000_000:
        raise ValueError("release_manifest_too_large")
    return Release.model_validate_json(path.read_bytes())


def verify_asset(path: Path, asset: Asset) -> None:
    not_link(path)
    if path.stat().st_size != asset.bytes or file_hash(path) != asset.sha256:
        raise ValueError("release_asset_mismatch")


def runtime_files(root: Path) -> tuple[FileEntry, ...]:
    paths = [root / p for p in REQUIRED]
    paths.extend(
        path
        for path in (root / BUNDLE).glob("*.json")
        if re.fullmatch(r"[0-9a-f]{64}\.json", path.name)
    )
    entries = []
    for path in sorted(set(paths)):
        for parent in [path, *path.parents]:
            if parent == root.parent:
                break
            not_link(parent)
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("release_path_escape")
        entries.append(
            FileEntry(
                path=path.relative_to(root).as_posix(),
                sha256=file_hash(path),
                bytes=path.stat().st_size,
            )
        )
    return tuple(sorted(entries, key=lambda f: f.path))


def verify_files(root: Path, knowledge: Knowledge, *, resources: bool = True) -> None:
    for entry in knowledge.files:
        path = root / entry.path
        for parent in [path, *path.parents]:
            if parent == root.parent:
                break
            not_link(parent)
        if path.stat().st_size != entry.bytes or file_hash(path) != entry.sha256:
            raise ValueError("release_file_mismatch")
    if resources:
        loaded = load_resources(root)
        if (
            len(loaded.catalog.chunks) != knowledge.database.points
            or hours_plan_digest(loaded.hours) != HOURS_DIGEST
        ):
            raise ValueError("release_catalog_inventory_mismatch")


def extract(root: Path, archive: Path, release: Release, *, resources: bool = True) -> None:
    verify_asset(archive, release.assets["knowledge"])
    if root.exists():
        not_link(root)
        if any(root.iterdir()):
            raise ValueError("release_extract_target_not_empty")
    else:
        root.mkdir(parents=True)
    inventory = {f.path: f for f in release.knowledge.files}
    with zipfile.ZipFile(archive) as zipped:
        items = zipped.infolist()
        if len(items) != len(inventory) or {i.filename for i in items} != set(inventory):
            raise ValueError("release_zip_inventory_mismatch")
        # Validate the whole archive before writing its first entry.
        for item in items:
            mode = item.external_attr >> 16
            if (
                not allowed_path(item.filename)
                or stat.S_ISLNK(mode)
                or item.is_dir()
                or item.flag_bits & 1
                or item.file_size != inventory[item.filename].bytes
            ):
                raise ValueError("release_zip_entry_invalid")
        for item in items:
            path = root / item.filename
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("release_path_escape")
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(item) as source, path.open("xb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
    verify_files(root, release.knowledge, resources=resources)
    # The existing read-only query cache adapter requires its directory to exist.
    # Shipping an empty directory avoids distributing historical test questions.
    (root / CACHE).mkdir(parents=True, exist_ok=True)


def scan_bytes(data: bytes, known: Iterable[bytes] = ()) -> None:
    if any(secret and secret in data for secret in known) or re.search(
        rb"sk-or-v1-[A-Za-z0-9_-]{30,}|github_pat_[A-Za-z0-9_]{30,}"
        rb"|-----BEGIN ((?:RSA |EC |OPENSSH )?PRIVATE KEY)-----\r?\n"
        rb"(?:[A-Za-z0-9+/=]{16,}\r?\n)+-----END \1-----",
        data,
    ):
        raise ValueError("release_secret_detected")


def inspect_archive(path: Path, known: tuple[bytes, ...]) -> int:
    """Inspect nested snapshot/image layers without extracting arbitrary paths."""
    total = 0

    def inspect(data, depth):
        nonlocal total
        if depth > 5:
            raise ValueError("release_archive_nesting_refused")
        with tarfile.open(fileobj=data, mode="r:*") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                if member.size > 600_000_000 or total + member.size > 4_000_000_000:
                    raise ValueError("release_archive_expansion_refused")
                source = archive.extractfile(member)
                raw = source.read()
                total += len(raw)
                scan_bytes(raw, known)
                if raw[:2] == b"\x1f\x8b" or raw[257:262] == b"ustar":
                    inspect(io.BytesIO(raw), depth + 1)

    with path.open("rb") as source:
        inspect(source, 0)
    return total


def write_zip(
    root: Path, path: Path, files: tuple[FileEntry, ...], known: tuple[bytes, ...]
) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for entry in files:
            data = (root / entry.path).read_bytes()
            scan_bytes(data, known)
            if len(data) != entry.bytes or hashlib.sha256(data).hexdigest() != entry.sha256:
                raise ValueError("release_source_changed_during_capture")
            info = zipfile.ZipInfo(entry.path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def request_json(base: str, route: str, key: str, data: dict | None = None) -> dict:
    if base not in {
        "http://127.0.0.1:6333",
        "http://telescope-m3-qdrant:6333",
        "http://qdrant_restore:6333",
    }:
        raise ValueError("release_database_target_refused")
    if route not in {
        "/",
        "/collections",
        "/aliases",
        "/cluster",
        f"/collections/{COLLECTION}",
        f"/collections/{COLLECTION}/points/scroll",
    }:
        raise ValueError("release_database_route_refused")
    request = urllib.request.Request(
        base + route,
        headers={"api-key": key, "Content-Type": "application/json"},
        data=canonical(data) if data is not None else None,
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=10
    ) as response:
        raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("release_database_response_too_large")
        return json.loads(raw)


def database_state(base: str, key: str, known: tuple[bytes, ...] = ()) -> Database:
    if request_json(base, "/", key)["version"] != "1.19.2":
        raise ValueError("release_database_version_mismatch")
    if request_json(base, "/cluster", key)["result"]["status"] != "disabled":
        raise ValueError("release_single_node_required")
    collections = request_json(base, "/collections", key)["result"]["collections"]
    aliases = request_json(base, "/aliases", key)["result"]["aliases"]
    if collections != [{"name": COLLECTION}] or aliases:
        raise ValueError("release_database_scope_mismatch")
    info = request_json(base, f"/collections/{COLLECTION}", key)["result"]
    rows = []
    offset = None
    for _ in range(101):
        body = {"limit": 32, "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        result = request_json(base, f"/collections/{COLLECTION}/points/scroll", key, body)["result"]
        rows.extend(result["points"])
        scan_bytes(canonical(result["points"]), known)
        offset = result["next_page_offset"]
        if offset is None:
            break
    if (
        offset is not None
        or len(rows) != info["points_count"]
        or len({p["id"] for p in rows}) != len(rows)
    ):
        raise ValueError("release_database_inventory_mismatch")
    vectors = info["config"]["params"]["vectors"]
    if vectors.get("size") != 4096 or vectors.get("distance") != "Cosine":
        raise ValueError("release_vector_configuration_mismatch")
    return Database(
        points=len(rows),
        points_sha256=digest(sorted(rows, key=lambda p: p["id"])),
        config=info["config"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["extract", "verify-files", "verify-db"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("/runtime"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--key-file", type=Path, default=Path("/run/secrets/qdrant_read_key"))
    parser.add_argument("--target", choices=["restore", "installed"], default="installed")
    args = parser.parse_args()
    try:
        release = read_release(args.manifest)
        if args.action == "extract":
            if args.archive is None:
                raise ValueError("release_archive_required")
            extract(args.root, args.archive, release)
        else:
            verify_files(args.root, release.knowledge)
            if args.action == "verify-db":
                key = args.key_file.read_text(encoding="ascii").strip()
                base = (
                    "http://qdrant_restore:6333"
                    if args.target == "restore"
                    else "http://telescope-m3-qdrant:6333"
                )
                deadline = time.monotonic() + 90
                while True:
                    try:
                        actual = database_state(base, key)
                        if actual != release.knowledge.database:
                            raise ValueError("release_restored_database_mismatch")
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise ValueError("release_database_wait_expired") from None
                        time.sleep(1)
        print(json.dumps({"verified": args.action, "knowledge_id": release.knowledge_id}))
    except Exception:
        raise SystemExit(
            "Portable release verification failed; no credentials have been printed."
        ) from None


if __name__ == "__main__":
    main()
