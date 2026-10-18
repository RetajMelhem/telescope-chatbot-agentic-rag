"""Recovery invariants: exact source bytes, bounded paths and unchanged knowledge."""

import hashlib
import io
import json
import shutil
import stat
import subprocess
import tarfile
import zipfile
from contextlib import nullcontext

import pytest
from pydantic import ValidationError

from telescope_rag.operations import release as r


@pytest.fixture
def package(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    content = json.dumps(
        {
            "owner": "د. لينا",
            "text": "معلومة المصدر؛ مع الشروط",
            "url": "https://telescopecenter.com/",
        },
        ensure_ascii=False,
    ).encode()
    path = r.BUNDLE + "a" * 64 + ".json"
    target = source / path
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    files = (r.FileEntry(path=path, sha256=r.file_hash(target), bytes=len(content)),)
    database = r.Database(points=1, points_sha256="a" * 64, config={"source": "fixture"})
    knowledge = r.Knowledge(files=files, database=database)
    archive = tmp_path / "knowledge.zip"
    r.write_zip(source, archive, files, ())
    assets = {
        name: r.Asset(name=f"{name}.zip", sha256="b" * 64, bytes=1)
        for name in ("knowledge", "database", "api", "qdrant")
    }
    assets["knowledge"] = r.Asset(
        name=archive.name, sha256=r.file_hash(archive), bytes=archive.stat().st_size
    )
    release = r.Release(
        version="v0.1.0",
        source_revision="c" * 40,
        knowledge_id=knowledge.identity,
        knowledge=knowledge,
        assets=assets,
        images={
            "api": r.Image(reference="telescope-rag-mvp:v0.1.0", image_id="sha256:" + "d" * 64),
            "qdrant": r.Image(reference=r.QDRANT_IMAGE, image_id="sha256:" + "e" * 64),
        },
    )
    return source, archive, release, content


@pytest.mark.parametrize(
    "path",
    [
        "../.env",
        "/.env",
        "C:/key",
        "data/../.env",
        "data//a.json",
        "data/./a.json",
        "data\\a.json",
        r.CACHE + "query.json",
        r.BUNDLE + "metadata/source-admission-plan.json",
        r.TOKENIZER + "README.md",
        r.METADATA + "private.key",
        r.TOKENIZER + "sub/LICENSE",
    ],
)
def test_nonruntime_or_escaping_paths_refused(path):
    assert not r.allowed_path(path)
    with pytest.raises(ValidationError):
        r.FileEntry(path=path, sha256="a" * 64, bytes=0)


def test_roundtrip_retains_arabic_ownership_and_provenance(package, tmp_path):
    _, archive, release, original = package
    destination = tmp_path / "restored"
    r.extract(destination, archive, release, resources=False)
    assert (destination / release.knowledge.files[0].path).read_bytes() == original
    assert list((destination / r.CACHE).iterdir()) == []
    r.verify_files(destination, release.knowledge, resources=False)
    (destination / release.knowledge.files[0].path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="file_mismatch"):
        r.verify_files(destination, release.knowledge, resources=False)


def test_code_only_update_keeps_data_identity(package):
    _, _, release, _ = package
    obj = release.model_dump(mode="json")
    obj["version"] = "v0.1.1"
    obj["source_revision"] = "f" * 40
    obj["images"]["api"]["reference"] = "telescope-rag-mvp:v0.1.1"
    updated = r.Release.model_validate_json(json.dumps(obj))
    assert updated.knowledge_id == release.knowledge_id
    changed = release.knowledge.model_copy(
        update={
            "database": release.knowledge.database.model_copy(update={"points_sha256": "f" * 64})
        }
    )
    assert changed.identity != release.knowledge_id


@pytest.mark.parametrize(
    "mutation", ["id", "extra_image", "missing_asset", "duplicate_asset", "image_reference"]
)
def test_manifest_bindings_reject_tampering(package, mutation):
    _, _, release, _ = package
    obj = release.model_dump(mode="json")
    if mutation == "id":
        obj["knowledge_id"] = "f" * 64
    elif mutation == "extra_image":
        obj["images"]["gateway"] = obj["images"]["api"]
    elif mutation == "missing_asset":
        del obj["assets"]["database"]
    elif mutation == "duplicate_asset":
        obj["assets"]["database"]["name"] = obj["assets"]["api"]["name"]
    else:
        obj["images"]["api"]["reference"] = "arbitrary:latest"
    with pytest.raises(ValidationError):
        r.Release.model_validate_json(json.dumps(obj))


@pytest.mark.parametrize(
    "mode", ["traversal", "extra", "duplicate", "symlink", "wrong_bytes", "wrong_hash"]
)
def test_malicious_or_damaged_zip_refused(package, tmp_path, mode):
    _, _, release, content = package
    name = release.knowledge.files[0].path
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zipped:
        info = zipfile.ZipInfo("../outside" if mode == "traversal" else name)
        if mode == "symlink":
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(
            info,
            b"x" * len(content)
            if mode == "wrong_hash"
            else content + (b"x" if mode == "wrong_bytes" else b""),
        )
        if mode in {"extra", "duplicate"}:
            with pytest.warns(UserWarning) if mode == "duplicate" else nullcontext():
                zipped.writestr(name if mode == "duplicate" else r.PLANS[0], content)
    asset = r.Asset(name=bad.name, sha256=r.file_hash(bad), bytes=bad.stat().st_size)
    modified = release.model_copy(update={"assets": {**release.assets, "knowledge": asset}})
    destination = tmp_path / "out"
    with pytest.raises(ValueError):
        r.extract(destination, bad, modified, resources=False)
    assert not (tmp_path / "outside").exists()
    if mode != "wrong_hash":
        assert not list(destination.rglob("*.json"))


def test_refuses_bad_archive_hash_and_nonempty_destination(package, tmp_path):
    _, archive, release, _ = package
    target = tmp_path / "out"
    target.mkdir()
    marker = target / "keep"
    marker.write_text("preserve")
    with pytest.raises(ValueError, match="target_not_empty"):
        r.extract(target, archive, release, resources=False)
    assert marker.read_text() == "preserve"
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="asset_mismatch"):
        r.extract(tmp_path / "second", archive, release, resources=False)
    assert not (tmp_path / "second").exists()


def test_capture_excludes_history_and_cache_but_keeps_required_files(tmp_path):
    for name in (
        *r.REQUIRED,
        r.BUNDLE + "a" * 64 + ".json",
        r.BUNDLE + "summary.json",
        r.CACHE + "query.json",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}")
    files = r.runtime_files(tmp_path)
    assert {entry.path for entry in files} == {*r.REQUIRED, r.BUNDLE + "a" * 64 + ".json"}


def test_secret_scan_reaches_nested_image_layers(tmp_path):
    # Synthetic marker; no real key or project secret is read by tests.
    marker = b"synthetic-secret-marker-for-test"

    def tar(payload, name):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            entry = tarfile.TarInfo(name)
            entry.size = len(payload)
            archive.addfile(entry, io.BytesIO(payload))
        return stream.getvalue()

    archive = tmp_path / "image.tar"
    archive.write_bytes(tar(tar(marker, "config"), "layer.tar"))
    with pytest.raises(ValueError, match="secret_detected"):
        r.inspect_archive(archive, (marker,))
    assert r.inspect_archive(archive, ()) > len(marker)
    with pytest.raises(ValueError, match="secret_detected"):
        r.scan_bytes(b"sk-or-v1-" + b"z" * 40)


def test_crypto_parser_header_is_not_private_key_material():
    header = b"-----BEGIN PRIVATE KEY-----"
    r.scan_bytes(b"library parser constant " + header)
    with pytest.raises(ValueError, match="secret_detected"):
        r.scan_bytes(header + b"\n" + b"A" * 64 + b"\n-----END PRIVATE KEY-----")


def test_public_vendor_exception_never_bypasses_known_keys(tmp_path, monkeypatch):
    raw = b"sk-or-v1-" + b"z" * 40  # Synthetic public fixture.
    name = "vendor.bin"
    monkeypatch.setattr(r, "PUBLIC_VENDOR_FILES", {name: hashlib.sha256(raw).hexdigest()})
    path = tmp_path / "vendor.tar"
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    r.inspect_archive(path, ())
    with pytest.raises(ValueError, match="secret_detected"):
        r.inspect_archive(path, (raw,))
    monkeypatch.setattr(r, "PUBLIC_VENDOR_FILES", {name: "a" * 64})
    with pytest.raises(ValueError, match="secret_detected"):
        r.inspect_archive(path, ())


def test_database_checks_all_payloads_vectors_and_pages(monkeypatch):
    rows = [
        {"id": 1, "payload": {"owner": "لينا"}, "vector": [0.1]},
        {"id": 2, "payload": {"qualifier": "only"}, "vector": [0.2]},
    ]
    config = {"params": {"vectors": {"size": 4096, "distance": "Cosine"}}}
    calls = []

    def request(base, route, key, data=None):
        calls.append((route, data))
        if route == "/":
            return {"version": "1.19.2"}
        if route == "/cluster":
            return {"result": {"status": "disabled"}}
        if route == "/collections":
            return {"result": {"collections": [{"name": r.COLLECTION}]}}
        if route == "/aliases":
            return {"result": {"aliases": []}}
        if route.endswith("/scroll"):
            final = "offset" in data
            return {
                "result": {
                    "points": rows[1:] if final else rows[:1],
                    "next_page_offset": None if final else 1,
                }
            }
        return {"result": {"points_count": 2, "config": config}}

    monkeypatch.setattr(r, "request_json", request)
    actual = r.database_state("fixture", "synthetic")
    assert actual.points_sha256 == hashlib.sha256(r.canonical(rows)).hexdigest()
    assert sum(data is not None for _, data in calls) == 2
    rows[1]["payload"]["qualifier"] = "changed"
    assert r.database_state("fixture", "synthetic").points_sha256 != actual.points_sha256
    rows[1]["id"] = 1
    with pytest.raises(ValueError, match="inventory_mismatch"):
        r.database_state("fixture", "synthetic")


@pytest.mark.parametrize(
    "base,route",
    [
        ("https://example.com", "/"),
        ("http://127.0.0.1:6333", "/snapshots"),
        ("http://127.0.0.1:6333", "/collections/arbitrary"),
    ],
)
def test_restore_reader_cannot_fetch_arbitrary_targets_or_write_routes(base, route):
    with pytest.raises(ValueError, match="refused"):
        r.request_json(base, route, "synthetic")


@pytest.mark.parametrize("action", ["extract", "verify-files", "verify-db"])
def test_windows_installer_keeps_mounts_as_single_docker_arguments(action):
    shell = shutil.which("powershell.exe")
    if shell is None:
        pytest.skip("Windows PowerShell compatibility case")
    script = r"""
$source=Join-Path $PWD 'install-mvp.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$definition=$ast.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Helper'
},$false)[0]
Invoke-Expression $definition.Extent.Text
$manifestPath='C:\release dir\release.json'
$Instance='telescope-portable-test'
$secretDir='C:\private dir'
$manifest=[PSCustomObject]@{images=[PSCustomObject]@{api=[PSCustomObject]@{reference='telescope-rag-mvp:v0.1.0'}}}
function Run-Docker { param([string[]]$Arguments) ConvertTo-Json -InputObject $Arguments -Compress }
Helper -Operation 'ACTION' -Data 'C:\data dir' -Target 'installed'
""".replace("ACTION", action)
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    arguments = json.loads(result.stdout)
    mount = arguments[arguments.index("--mount", arguments.index("--mount") + 1) + 1]
    assert mount == "type=bind,source=C:\\data dir,target=/runtime" + (
        "" if action == "extract" else ",readonly"
    )
    assert arguments[arguments.index("--entrypoint") + 2] == "telescope-rag-mvp:v0.1.0"
    assert ",readonly" not in arguments
