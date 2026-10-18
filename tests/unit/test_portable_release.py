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
from pathlib import Path

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


def test_windows_secret_acl_is_private_and_repeatable(tmp_path):
    shell = shutil.which("powershell.exe")
    if shell is None:
        pytest.skip("Windows PowerShell ACL case")
    script = r"""
$ErrorActionPreference='Stop'
$source=Join-Path $PWD 'install-mvp.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$definitions=$ast.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Private-Directory','Safe-Directory')
},$false)
foreach ($definition in $definitions) { Invoke-Expression $definition.Extent.Text }
Private-Directory 'TARGET'
Private-Directory 'TARGET'
$acl=(New-Object IO.DirectoryInfo('TARGET')).GetAccessControl()
$rules=$acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier])
if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 3) { throw 'ACL invalid' }
Write-Output 'private-repeatable'
""".replace("TARGET", str(tmp_path / "private").replace("'", "''"))
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "private-repeatable"


@pytest.mark.parametrize("saved_port", [0, 65536, 8123])
def test_saved_dashboard_port_cannot_be_invalid_or_overlap_api(saved_port):
    shell = shutil.which("powershell.exe")
    if shell is None:
        pytest.skip("Windows PowerShell state validation")
    script = r"""
$ast=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'install-mvp.ps1'),[ref]$null,[ref]$null)
$definition=$ast.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Get-QdrantPort'
},$false)[0]
Invoke-Expression $definition.Extent.Text
try { Get-QdrantPort ([PSCustomObject]@{port=8123;qdrant_port=SAVED}); exit 2 }
catch { Write-Output $_.Exception.Message }
""".replace("SAVED", str(saved_port))
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "distinct valid localhost ports" in result.stdout


@pytest.mark.parametrize(
    "scenario",
    ["fresh", "missing", "present", "code_update", "collision", "bad_snapshot", "restore_failure"],
)
@pytest.mark.parametrize("dashboard_port", [None, 6444, "override"])
def test_windows_installer_restores_missing_volume_without_overwriting_existing_data(
    package, tmp_path, scenario, dashboard_port
):
    shell = shutil.which("powershell.exe")
    if shell is None:
        pytest.skip("Windows PowerShell recovery case")
    _, _, release, _ = package
    root = tmp_path / "install dir"
    root.mkdir()
    owner = {"schema_version": "portable-installation-v1", "instance": "telescope-portable-test"}
    owner["id"] = "a" * 32
    (root / "installation.json").write_text(json.dumps(owner))
    data = root / "knowledge" / release.knowledge_id
    data.mkdir(parents=True)
    secrets = root / "secrets"
    secrets.mkdir()
    (secrets / "openrouter.key").write_text("sk-or-v1-" + "z" * 40)
    snapshot = root / "downloads" / "database.snapshot"
    snapshot.parent.mkdir()
    snapshot_bytes = b"synthetic snapshot"
    manifest = release.model_dump(mode="json")
    manifest["assets"]["database"] = {
        "name": snapshot.name,
        "bytes": len(snapshot_bytes),
        "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
    }
    if scenario not in {"present", "code_update"}:
        snapshot.write_bytes(b"corrupt" if scenario == "bad_snapshot" else snapshot_bytes)
    version = "v0.1.1" if scenario == "code_update" else "v0.1.0"
    manifest["version"] = version
    manifest["images"]["api"]["reference"] = f"telescope-rag-mvp:{version}"
    release_dir = root / "releases" / version
    release_dir.mkdir(parents=True)
    (release_dir / "release.json").write_text(json.dumps(manifest))
    volume = f"{owner['instance']}-knowledge-{release.knowledge_id[:24]}"
    state = {
        "version": "v0.1.0",
        "knowledge_id": release.knowledge_id,
        "data_root": str(data),
        "snapshot": str(snapshot),
        "volume": volume,
        "api_image": "telescope-rag-mvp:v0.1.0",
        "qdrant_image": manifest["images"]["qdrant"]["image_id"],
        "port": 8123,
    }
    if dashboard_port is not None:
        state["qdrant_port"] = 6444
    state_path = root / "current.json"
    has_current = scenario not in {"fresh", "collision"}
    if has_current:
        state_path.write_text(json.dumps(state))
    original_state = state_path.read_bytes() if has_current else None
    fixture = {
        "installer": str(Path(__file__).resolve().parents[2] / "install-mvp.ps1"),
        "root": str(root),
        "version": version,
        "images": manifest["images"],
        "volume_present": scenario in {"present", "code_update", "collision"},
        "restore_failure": scenario == "restore_failure",
        "log": str(tmp_path / "docker.json"),
        "override_dashboard_port": dashboard_port == "override",
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))
    runner = tmp_path / "run.ps1"
    runner.write_text(
        r"""
param([string]$FixturePath)
$ErrorActionPreference='Stop'
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+[IO.Path]::PathSeparator+$env:PSModulePath
$fixture=Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json
$global:recoveryCalls=New-Object Collections.ArrayList
$global:recoveryVolumePresent=$fixture.volume_present
function Invoke-WebRequest { throw 'Network forbidden in recovery test' }
function docker {
    $command=@($args | ForEach-Object { [string]$_ })
    [void]$global:recoveryCalls.Add($command)
    $global:LASTEXITCODE=0
    if ($command[0] -eq 'inspect') { $global:LASTEXITCODE=1; return }
    if ($command[0] -eq 'image' -and $command[1] -eq 'inspect') {
        if ($command[-1] -like 'telescope-rag-mvp:*') { return $fixture.images.api.image_id }
        return $fixture.images.qdrant.image_id
    }
    if ($command[0] -eq 'volume' -and $command[1] -eq 'inspect') {
        if ($global:recoveryVolumePresent) { return '[{"Name":"synthetic"}]' }
        $global:LASTEXITCODE=1; return
    }
    if ($command[0] -eq 'volume' -and $command[1] -eq 'create') {
        if ($global:recoveryVolumePresent) { throw 'Existing volume must not be overwritten' }
        $global:recoveryVolumePresent=$true; return $command[-1]
    }
    if ($command[0] -eq 'run') { return }
    if ($command[0] -eq 'compose') {
        if (-not $global:recoveryVolumePresent) { throw 'External volume missing' }
        if ($fixture.restore_failure -and $command -contains 'up' -and
            $command -contains 'qdrant_restore') { $global:LASTEXITCODE=1 }
        return
    }
    throw 'Unexpected Docker operation'
}
$code=0
try {
    $parameters=@{Version=$fixture.version;InstallRoot=$fixture.root;Instance='telescope-portable-test'}
    if ($fixture.override_dashboard_port) { $parameters.QdrantPort=6550 }
    & $fixture.installer @parameters
} catch { Write-Output $_.Exception.Message; $code=1 }
$log=ConvertTo-Json -InputObject @($global:recoveryCalls) -Depth 10
[IO.File]::WriteAllText($fixture.log, $log)
exit $code
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(runner), str(fixture_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    calls = json.loads(Path(fixture["log"]).read_text(encoding="utf-8-sig"))
    creates = [call for call in calls if call[:2] == ["volume", "create"]]
    restores = [
        call for call in calls if call[0] == "compose" and "up" in call and "qdrant_restore" in call
    ]
    failures = {"collision", "bad_snapshot", "restore_failure"}
    assert result.returncode == (1 if scenario in failures else 0), result.stdout + result.stderr
    if scenario in failures:
        expected_error = {
            "collision": "A target volume already exists",
            "bad_snapshot": "Cached asset does not match this release",
            "restore_failure": "Portable Docker operation failed",
        }
        assert expected_error[scenario] in result.stdout
        assert (state_path.read_bytes() if has_current else None) == original_state
        assert not any(call[0] == "compose" and "api" in call for call in calls)
        if scenario != "restore_failure":
            assert not creates and not restores
        return
    actual_state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    assert actual_state["knowledge_id"] == release.knowledge_id
    assert actual_state["volume"] == volume
    assert actual_state["port"] == (8123 if has_current else 8000)
    assert actual_state["qdrant_port"] == (
        6550 if dashboard_port == "override" else 6444 if has_current and dashboard_port else 6333
    )
    assert f"http://127.0.0.1:{actual_state['qdrant_port']}/dashboard/" in result.stdout
    assert "z" * 40 not in result.stdout + result.stderr
    assert actual_state["version"] == version
    assert data.is_dir()
    if scenario in {"present", "code_update"}:
        assert not creates and not restores
        assert not snapshot.exists()  # Code-only reuse must not need a snapshot/download.
    else:
        assert len(creates) == len(restores) == 1
        assert creates[0][-1] == volume
        restore_check = next(
            call for call in calls if "verify-db" in call and call[-1] == "restore"
        )
        startup = next(call for call in calls if call[0] == "compose" and "api" in call)
        assert calls.index(creates[0]) < calls.index(restores[0])
        assert calls.index(restores[0]) < calls.index(restore_check) < calls.index(startup)
        assert snapshot.read_bytes() == snapshot_bytes
    assert any("verify-db" in call and call[-1] == "installed" for call in calls)
