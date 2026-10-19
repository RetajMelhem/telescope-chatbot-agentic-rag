# v0.2.0 local MVP

Install the versioned release from its matching source copy:

```powershell
.\install-mvp.cmd -Version v0.2.0
```

The launcher also selects v0.2.0 when double-clicked without arguments. A Git
checkout alone does not change an installed image; the installer loads the
versioned release assets. The original v0.1.0 release remains unchanged.

This release includes the complete staff/eye-doctor roster and English clinical
specialty retrieval prompt fixes, plus request-correlated, content-free failure
logs. The same reviewed 107-document / 955-chunk knowledge, existing vectors,
model settings, two-call budget and no-retry policy are retained.

The requested Qdrant dashboard is published at
[127.0.0.1:6333/dashboard/](http://127.0.0.1:6333/dashboard/) on the Windows computer.
Authentication remains enabled: use the read-only key from the installation's
`secrets/read.key`, not the admin key. Use `-QdrantPort 6335` when needed; the
selected port persists through Start, upgrades and rollback. The API and Qdrant
REST ports bind only to localhost, and Qdrant gRPC is not published. See the
[portable guide](PORTABLE_MVP.md) for key paths and custom installation roots.

Seven exact historical problem questions passed the existing candidate HTTP rerun.
The offline 50-answer update combines 43 original answers with those seven replies;
it is not a new full-50 test of this release. The three historical 502 causes remain
unconfirmed, and no permanent absence of provider/validation failures is claimed.
Reviews are provisional AI source judgments. See
[targeted fixes](NATURAL_EVALUATION_FIXES.md) and
[saved-answer remeasurement](NATURAL_EVALUATION_50.md#offline-remeasurement-of-saved-responses).

Release packaging and installation checks do not submit model requests. Knowledge
and vectors are verified and reused rather than crawled or re-embedded. Keys,
private installation state, audit outputs and model weights are excluded from the
source and release assets. Publication and final installation verification are
recorded in [project status](../PROJECT_STATUS.md).

The [release is published](https://github.com/RetajMelhem/telescope-chatbot-agentic-rag/releases/tag/v0.2.0)
with six verified assets. A fresh public main clone restored all 955 points in an
initially empty isolated engine and passed source, API/UI, dashboard binding and
authenticated collection checks. Actual Windows launcher upgrade, rollback and
restart tests retained the selected dashboard port and the same data volume.
No model requests ran. Source tag: `e161c06`; API image:
`sha256:36d81610c934d6c4c2efe3b37649ae0f45be615788fe358873d3b7ec1d396853`.
