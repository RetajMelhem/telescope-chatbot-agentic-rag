# Portable local MVP

This distribution restores the existing reviewed knowledge and stored vectors.
It does not crawl, parse, chunk or re-embed the corpus. It requires Windows,
Docker Desktop with Linux amd64 containers, internet for OpenRouter, and your own
valid OpenRouter key/credit. No host Python installation is required by the installer.
Other operating systems and ARM machines have not been validated.

## Install and run

Use a source copy containing `install-mvp.cmd` beside `install-mvp.ps1`, start
Docker Desktop, then run PowerShell in the project directory. Older source ZIPs
need the new launcher copied into the extracted project folder; the existing
v0.1.0 data and image assets remain compatible.

```powershell
.\install-mvp.cmd -Version v0.3.0
```

For the simplest installation, extract the complete project ZIP, start Docker
Desktop and double-click [install-mvp.cmd](../install-mvp.cmd). With no arguments
it installs v0.3.0 and keeps the window open afterward so you can read the result.
The launcher also accepts the existing installer's parameters, as shown above.

The `.cmd` launcher starts the existing `install-mvp.ps1` with
`-ExecutionPolicy Bypass` only for that PowerShell process. Downloaded, unsigned
scripts can therefore run under the usual `RemoteSigned` policy without manually
unblocking files. It does not change saved execution policies, unblock files or
elevate privileges. Only run a project copy you trust. Organization-enforced Group
Policy and Windows application controls still apply; this launcher does not
override those restrictions. See Microsoft's
[PowerShell process options](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1#-executionpolicy-executionpolicy).

The installer downloads assets from the matching GitHub Release, checks hashes,
loads the two images, restores a new database volume and checks every stored point,
vector and payload against the release fingerprint. It validates the source files,
admission/digests, tokenizer, hours and official link supplement before serving.
It uses the project's `.env` key when present, otherwise asks for a hidden key.
Existing `.env` and development database/containers are preserved.

The knowledge the installer restores is the reviewed snapshot: **107 documents /
955 chunks / 834 distinct evidence groups**, English and Arabic, with
4,096-dimensional vectors. The knowledge identity is
`a16414530c40e991c3b0b506d9b30d2bac3d57587d36aa39759cafaaa56faccb`, and it is
identical in v0.2.0 and v0.3.0, so those two releases share their knowledge
archive and native database snapshot and a code-only update needs no corpus
change.

Open [the chatbot](http://127.0.0.1:8000/) or [API docs](http://127.0.0.1:8000/docs).
If that port is busy, add `-Port 8001`. Each new question may spend OpenRouter credit;
installation and health checks make no model calls. Corpus vectors are restored,
but new queries still need query embeddings and Luna generation.

Open the [Qdrant dashboard](http://127.0.0.1:6333/dashboard/) to inspect collections
and points. In the dashboard's connection/API-key prompt, use the **read-only key**
from `%LOCALAPPDATA%\TelescopeRag\secrets\read.key` (under your custom `-InstallRoot`
when applicable). Keep that key private. The installer prints its file path,
never its value; no key is placed in the dashboard URL. Qdrant authentication
remains enabled. Read-only access can inspect data but cannot modify collections.

Both the chatbot and dashboard bind only to `127.0.0.1` on this computer. If port
6333 is occupied, install with `-QdrantPort 6335`, then open
`http://127.0.0.1:6335/dashboard/`. The selected port is saved and retained by
Start, later upgrades and rollback. Older installation records without a dashboard
port default to 6333 when used with this updated installer. The API and dashboard
ports must differ. Qdrant's gRPC port is not published.

```powershell
.\install-mvp.cmd -Action Status
.\install-mvp.cmd -Action Stop
.\install-mvp.cmd -Action Start
```

State, downloads, knowledge and private keys live in `%LOCALAPPDATA%\TelescopeRag`.
Use the same `-InstallRoot` and `-Instance` on every invocation if customizing them.
Instance names begin with `telescope-portable`; they cannot target the development
containers. Do not delete the installed directory while its containers are running.
The installer refuses unowned containers, existing restore volumes and reparse paths.
Fresh installs generate fresh database admin/read keys; only the read key reaches
the API. Secret files have Windows ACLs limited to the current user, SYSTEM and
Administrators. They are outside the public release. The API and data mounts remain
read-only and the UI binds only to loopback.

## What is included

| Location | Contents |
| --- | --- |
| Git repository | Application, UI, tests, locked dependencies, Docker/installer scripts and documentation |
| Release knowledge ZIP | Required prepared documents and approval/configuration/authority metadata; hours and link proofs; verified tokenizer and upstream license |
| Release Qdrant snapshot | Native full-storage snapshot of the single existing collection, including vectors and payloads |
| Two image archives | Ready-built API with dependencies, and the exact Qdrant image |
| Release manifest/checksums | File/asset hashes, image IDs, source revision and complete database fingerprint |

There are **two running containers**: API and Qdrant. During initial restore there
is one temporary Qdrant restore container; it is removed before normal serving.
The API reaches Qdrant directly on a private network. Nginx is unnecessary in this
distribution. Since v0.2.0, the authenticated database REST/dashboard port is also
published on localhost only; its internal Docker network remains private. The
Qdrant container also joins the publishable bridge used by the API, because Docker
does not publish ports for a container attached only to an internal network.
It remains a two-container installation. The existing
`telescope-m3-qdrant-gateway` supports the older host-Python launcher/dashboard;
it remains unchanged on the development machine.

No `.env`, keys, model weights, virtual environments, raw crawl history, historical
audit outputs, old bundles or cached test queries are distributed. The runtime
query-cache directory starts empty. The prepared source text, ownership, spans,
URLs, timestamps and sealed review metadata are retained unchanged. This is an
installable MVP archive, not an archive of every development/audit artifact.
Tokenizer bytes come from the pinned official
[Qwen revision](https://huggingface.co/Qwen/Qwen3-Embedding-8B/tree/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af),
with its upstream Apache license in the knowledge ZIP. Luna/Qwen model weights
run through OpenRouter and are not required locally.

## Updates, rollback and copies

Install a later released version with the same command and a new `-Version`.
Code-only releases retain the same knowledge identity: the installer reuses the
validated knowledge directory and database volume, without downloading/restoring
the data again. Each data release has a new knowledge identity and restores into
a separate volume. Previous data is preserved. The previous successful install can
be selected with `-Action Rollback`; rollback swaps current/previous records.
Update only while no user requests are running. Do not manually retag installed
images or edit manifests. Failed startup leaves the successful state record intact
and attempts to restart the prior version; a failed initial restore volume is
retained for diagnosis rather than overwritten automatically.

If Docker loses the installed database volume while the installation directory
survives (for example, after a Docker reset or switching to an empty Docker context),
rerun `.\install-mvp.cmd -Version v0.3.0` using the version you want installed.
The installer checks that the saved volume actually exists before reusing it.
A missing volume is recreated from the hash-verified release snapshot and all
stored points are checked before serving; intact volumes are reused. Existing
restore volumes are still refused, and failed recovery preserves the successful
installation record. `-Action Start` requires the existing database volume; use
`-Version` to recover missing data. Restoration makes no model calls.

For a second remote copy, download all assets plus matching source ZIP/tag and put
them together in Drive. Keep their original names and SHA256SUMS. A local copy can
be installed using `-ReleaseDirectory C:\path\to\release-assets`. No Drive
credentials or sync software is needed. Source code can also be updated/build from
the repository; the existing `run-mvp.ps1` remains the development launcher.

Public GitHub assets are convenient and versioned, but are not encrypted backups
or guaranteed permanent hosting. Keep the optional second copy and store your
provider key separately in a password manager. Hashes detect corruption; trust
also depends on the GitHub account and matching release source. No key or balance
is transferred by a release. Native snapshot restoration is pinned to the tested
Qdrant version; upgrades need their own restore test. A fixed saved website
snapshot does not automatically refresh changing clinic facts.

## Preparing a future release

### Repeat an isolated installation test on this laptop

From the updated checkout, run:

```powershell
powershell.exe -NoProfile -File .\scripts\test_portable_cold_install.ps1
```

The [test script](../scripts/test_portable_cold_install.ps1) requires Git, Windows
PowerShell 5.1, Docker Desktop's `desktop-linux` context and internet access. It
starts a pinned official [Docker-in-Docker image](https://hub.docker.com/_/docker/)
as a temporary privileged test engine, without mounting the host Docker socket.
It verifies that the inner engine has zero images, containers and volumes, clones
public GitHub `main` into a new directory, then runs that clone's unchanged
installer. A Docker command adapter translates only test-directory mount paths
and forwards commands into the inner engine; the cloned installer and Compose
file are not patched. Public source/release revisions are recorded separately.

Both application image archives, the knowledge ZIP and database snapshot must
be downloaded into the new install root and match their manifest hashes. The
test verifies restored data, source/tokenizer resources, read-only API mounts and
five HTTP endpoints. It supplies an explicit synthetic OpenRouter key and sends
no questions, so this checks startup/data recovery without private credentials
or model calls. Provider authentication and live answers remain untested.

The owned test engine and its nested database are removed afterward. Existing
containers are checked for unchanged IDs/start times. Reports and downloaded
assets remain under ignored `artifacts/portable-cold-install-*/`; generated
installation secrets retain the installer's private ACLs. The public installer
may print port 8000, but its test API is inside the disposable engine and is not
published on the laptop. This test shares the host Windows/Docker Desktop/kernel;
it is stronger than reusing the existing image cache, but is not a second-machine
or pristine-Windows verification.

### Build and publish a release

Use the reviewed development installation. Complete offline checks and commit the
scoped changes first. Build the API with its actual source revision label:

```powershell
$revision = git rev-parse HEAD
docker build -f deploy/Dockerfile --build-arg VCS_REF=$revision --label "org.opencontainers.image.revision=$revision" -t telescope-rag-mvp:v0.3.0 .
& .\.tools\uv\bin\uv.exe run --locked python scripts/build_portable_release.py --version v0.3.0 --output artifacts/portable-v0.3.0 --reuse-data-release artifacts/portable-v0.2.0
```

Use `--reuse-data-release` only when the knowledge identity is unchanged. The
directory it points at must hold the previous release's `release.json` together
with the knowledge archive and the native snapshot that manifest names, so the
capture can verify their hashes before copying them forward. Omit it for an
approved data change to capture a new native snapshot. Capture refuses a
dirty checkout, checks source/image binding and scans source, snapshots and nested
image archives for known credentials and selected secret patterns. It then
rechecks every source file and the full live point/configuration fingerprint.
It never changes the collection or an active alias. Secret scanning is defense in
depth and does not prove absence of every possible secret format.

Before publishing, test an isolated installation, source validation, all restored
points, readiness, code-only reuse and rollback. Publish code/tag and the complete
asset set; keep generated files outside Git history. Each asset is below GitHub's
2 GiB limit. See [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
and [Qdrant snapshots](https://qdrant.tech/documentation/snapshots/) for format/hosting limits.

Verified on Windows PowerShell 5.1 and Docker Desktop Linux amd64: image save/load,
restore into a new volume, exact comparison of all 955 IDs/vectors/payloads and
configuration, 116 runtime files, source/tokenizer/plan loading, five HTTP endpoints,
read-only permissions, synthetic code-only reuse and rollback. The v0.2.0 suite
passed 2,445 offline tests; 62 focused installer tests passed again after the
final Docker bridge correction. A fresh public main clone then installed v0.2.0
in an initially empty isolated engine, downloading all four archives and checking
the default dashboard binding and authenticated collection reads. A separate
actual Windows launcher test checked custom-port dashboard access and rejected
read-key writes. The tests used isolated installations on the existing machine;
a different physical machine and other platforms remain unverified. No model call
ran during these recovery checks. Details are recorded in `PROJECT_STATUS.md`.
Restore equivalence does not establish new answer-quality or production acceptance.
