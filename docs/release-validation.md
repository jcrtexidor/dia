# Release validation and version policy

The Ubuntu `.deb` is the primary end-user artifact. Releases are built and tested
locally; automation does not tag, upload or publish a release.

| Component | Current version | Compatibility meaning |
| --- | --- | --- |
| Native Dia fork | 0.98.0 | Native editor/plugin/model version; fork commits identify integration changes |
| Python adapter | 0.3.0 | MCP package and user-facing workflow/configuration release |
| Live protocol | 1 | JSON/Unix transport contract; required capabilities negotiate additive features |
| Snapshot API | 1 | Isolated document/operations contract |
| Ubuntu package | 0.98.0+mcp0.3.0-1 | Native + adapter version and packaging revision; Ubuntu 26.04 amd64/Python 3.14 |

They do not increment together mechanically. Additive tools/capabilities can retain
protocol 1; incompatible wire semantics require a protocol change. Native plugin
ABI, embedded Python ABI and distribution package dependencies are separate.
Adapter metadata, `__version__` and the local project entry in `uv.lock` agree;
M10 updates only that project version, not locked third-party dependencies.

## Commands and gates

```sh
./build-aux/mcp/bootstrap.sh    # Docker-only development bootstrap
# Full validation, with Task and uv installed for portable checks:
task mcp:release-check
```

The repeatable flow checks portable Python formatting/contracts, builds with the
pinned Ubuntu base and xpm revision, runs Meson/MCP suites, tests the installed
image as an unprivileged user, exercises real Wayland when a compositor is
available, creates the `.deb`, installs it into a fresh Ubuntu runtime and runs
clean-user smoke checks. Documentation local targets, version consistency and
artifact checksums are validated before the final manifest. The full command can
take several minutes; retained logs identify the failed stage for targeted repair.

A missing Wayland environment must be recorded as **SKIPPED**, never passed.
Validation in such CI is useful but does not replace recorded Wayland evidence
for a GUI release. A failed mandatory gate prevents a successful final manifest.
The fresh runtime receives the package and smoke harness, not the checkout,
compiler tree or builder prefix beyond the installed payload. Test actions use a
fresh non-root home and no runtime network.

`task mcp:package` alone packages an existing image; it does not establish release
readiness. Verify the candidate through the complete flow before distributing it.
Artifacts and SHA256 manifests stay under `artifacts/release` (ignored by Git).
The venv is bundled at its fixed prefix, including the existing test tooling in
this first packaging iteration; installation itself requires no Python downloads.
System APT repositories are not immutable snapshots: record the validation image
and installed dependencies instead of claiming bit-for-bit reproducible rebuilds.

## Candidate acceptance

See [clean-user checklist](user-acceptance.md) for functional acceptance and
[installation](installation.md) for supported platform/packaging alternatives.
Final M10 validation records are linked from [progress](progress.md). The package
has not been tested on another Ubuntu release, architecture or Python ABI.
