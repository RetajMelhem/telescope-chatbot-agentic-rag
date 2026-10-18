"""Capture existing public knowledge/vectors and images; never parse/chunk/embed."""

import argparse
import gzip
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

from telescope_rag.api.local import load_resources
from telescope_rag.operations.release import (
    QDRANT_IMAGE,
    Asset,
    Image,
    Knowledge,
    Release,
    database_state,
    file_hash,
    inspect_archive,
    read_release,
    runtime_files,
    verify_asset,
    verify_files,
    write_zip,
)


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, encoding="utf-8").strip()


def snapshot(path: Path, root: Path) -> None:
    key = (root / ".tools/qdrant-m3/admin.key").read_text(encoding="ascii").strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        "http://127.0.0.1:6333/snapshots", method="POST", headers={"api-key": key}
    )
    with opener.open(request, timeout=180) as response:
        result = json.load(response)["result"]
    name = result["name"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.snapshot", name):
        raise ValueError("release_snapshot_name_invalid")
    request = urllib.request.Request(
        "http://127.0.0.1:6333/snapshots/" + name, headers={"api-key": key}
    )
    with opener.open(request, timeout=180) as response, path.open("xb") as output:
        count = 0
        while block := response.read(1024 * 1024):
            count += len(block)
            if count >= 2 * 1024**3:
                raise ValueError("release_snapshot_too_large")
            output.write(block)


def image_asset(reference: str, output: Path, known: tuple[bytes, ...]) -> tuple[Image, Asset]:
    info = json.loads(docker("image", "inspect", reference))[0]
    if info["Os"] != "linux" or info["Architecture"] != "amd64":
        raise ValueError("release_image_platform_invalid")
    name = "image-" + info["Id"].split(":")[1][:24] + ".tar.gz"
    path = output / name
    with (
        path.open("xb") as destination,
        gzip.GzipFile(fileobj=destination, mode="wb", mtime=0) as compressed,
    ):
        process = subprocess.Popen(["docker", "image", "save", reference], stdout=subprocess.PIPE)
        try:
            shutil.copyfileobj(process.stdout, compressed)
        finally:
            process.stdout.close()
            if process.wait() != 0:
                raise ValueError("release_image_export_failed")
    inspect_archive(path, known)
    return Image(reference=reference, image_id=info["Id"]), describe(path)


def describe(path: Path) -> Asset:
    return Asset(name=path.name, sha256=file_hash(path), bytes=path.stat().st_size)


def build(root: Path, output: Path, version: str, reuse: Path | None) -> Release:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("release_version_invalid")
    # The user authorized these public source assets as release downloads, not keys.
    load_resources(root)
    source_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    changes = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    if changes:
        raise ValueError("release_requires_clean_checkpoint")
    api = json.loads(docker("image", "inspect", f"telescope-rag-mvp:{version}"))[0]
    if api["Config"]["Labels"].get("org.opencontainers.image.revision") != source_revision:
        raise ValueError("release_image_revision_mismatch")
    values = dotenv_values(root / ".env")
    known = tuple(
        {
            v.encode()
            for k, v in values.items()
            if v and any(x in k for x in ["KEY", "SECRET", "TOKEN"]) and len(v) >= 12
        }
        | {p.read_bytes().strip() for p in (root / ".tools/qdrant-m3").glob("*.key")}
    )
    key = (root / ".tools/qdrant-m3/read.key").read_text(encoding="ascii").strip()
    before = database_state("http://127.0.0.1:6333", key, known)
    knowledge = Knowledge(files=runtime_files(root), database=before)
    verify_files(root, knowledge)
    output.mkdir(parents=True, exist_ok=False)
    knowledge_path = output / f"knowledge-{knowledge.identity[:24]}.zip"
    snapshot_path = output / f"qdrant-{knowledge.identity[:24]}.snapshot"
    if reuse:
        old = read_release(reuse / "release.json")
        if old.knowledge_id != knowledge.identity:
            raise ValueError("release_reused_knowledge_changed")
        for category, dest in [("knowledge", knowledge_path), ("database", snapshot_path)]:
            source = reuse / old.assets[category].name
            verify_asset(source, old.assets[category])
            shutil.copyfile(source, dest)
    else:
        write_zip(root, knowledge_path, knowledge.files, known)
        print("Public knowledge captured; creating native database snapshot.", flush=True)
        snapshot(snapshot_path, root)
    print("Inspecting exported database and image archives for credentials.", flush=True)
    inspect_archive(snapshot_path, known)
    images = {}
    assets = {"knowledge": describe(knowledge_path), "database": describe(snapshot_path)}
    for category, reference in [
        ("api", f"telescope-rag-mvp:{version}"),
        ("qdrant", QDRANT_IMAGE),
    ]:
        images[category], assets[category] = image_asset(reference, output, known)
    if (
        database_state("http://127.0.0.1:6333", key, known) != before
        or runtime_files(root) != knowledge.files
    ):
        raise ValueError("release_sources_changed_during_capture")
    release = Release(
        version=version,
        source_revision=source_revision,
        knowledge_id=knowledge.identity,
        knowledge=knowledge,
        images=images,
        assets=assets,
    )
    (output / "release.json").write_text(release.model_dump_json(indent=2), encoding="utf-8")
    lines = [f"{a.sha256}  {a.name}" for a in assets.values()]
    lines.append(f"{file_hash(output / 'release.json')}  release.json")
    (output / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reuse-data-release", type=Path)
    args = parser.parse_args()
    try:
        release = build(Path.cwd(), args.output, args.version, args.reuse_data_release)
        print(
            json.dumps(
                {
                    "version": release.version,
                    "knowledge_id": release.knowledge_id,
                    "assets": {k: v.bytes for k, v in release.assets.items()},
                    "model_calls": 0,
                }
            )
        )
    except Exception:
        raise SystemExit(
            "Portable release capture failed; partial output is unapproved. Credentials are hidden."
        ) from None
