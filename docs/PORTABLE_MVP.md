# Portable local MVP

This distribution restores the existing reviewed knowledge and stored vectors.
It does not crawl, parse, chunk or re-embed the corpus. It requires Windows,
Docker Desktop with Linux amd64 containers, internet for OpenRouter, and your own
valid OpenRouter key/credit. No host Python installation is required by the installer.
Other operating systems and ARM machines have not been validated.

## Install and run

Clone the repository or download its matching source release, start Docker Desktop,
then run PowerShell in the project directory:

```powershell
.\install-mvp.ps1 -Version v0.1.0
```

The installer downloads assets from the matching GitHub Release, checks hashes,
loads the two images, restores a new database volume and checks every stored point,
vector and payload against the release fingerprint. It validates the source files,
admission/digests, tokenizer, hours and official link supplement before serving.
It uses the project's `.env` key when present, otherwise asks for a hidden key.
Existing `.env` and development database/containers are preserved.

Open [the chatbot](http://127.0.0.1:8000/) or [API docs](http://127.0.0.1:8000/docs).
If that port is busy, add `-Port 8001`. Each new question may spend OpenRouter credit;
installation and health checks make no model calls. Corpus vectors are restored,
but new queries still need query embeddings and Luna generation.

```powershell
.\install-mvp.ps1 -Action Status
.\install-mvp.ps1 -Action Stop
.\install-mvp.ps1 -Action Start
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
distribution and no database port is exposed to the host. The existing
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

Use the reviewed development installation. Complete offline checks and commit the
scoped changes first. Build the API with its actual source revision label:

```powershell
$revision = git rev-parse HEAD
docker build -f deploy/Dockerfile --label "org.opencontainers.image.revision=$revision" -t telescope-rag-mvp:v0.1.1 .
& .\.tools\uv\bin\uv.exe run --locked python scripts/build_portable_release.py --version v0.1.1 --output artifacts/portable-v0.1.1 --reuse-data-release artifacts/portable-v0.1.0
```

Use `--reuse-data-release` only when the knowledge identity is unchanged. Omit it
for an approved data change to capture a new native snapshot. Capture refuses a
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
read-only permissions, synthetic code-only reuse and rollback. All 2,293 offline
tests pass. The test used an isolated installation on the existing machine;
a different physical machine and other platforms remain unverified. No model call
ran during these recovery checks. Details are recorded in `PROJECT_STATUS.md`.
Restore equivalence does not establish new answer-quality or production acceptance.
