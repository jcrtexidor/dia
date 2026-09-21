# M10 installation and user readiness

M9 was closed at `75afcab2a` before packaging/configuration implementation.
The native editor remains Dia 0.98.0/GTK3; the adapter is now 0.3.0, live protocol
1 and snapshot API 1. Only the local project version changed in `uv.lock`;
third-party dependency versions/hashes are unchanged.

## Delivered and tested surfaces

- Primary Ubuntu 26.04 amd64 `.deb`: native editor/plugins/resources plus external
  Python 3.14 venv, separate desktop entries and fixed-prefix launchers. It does
  not replace `/usr/bin/dia`, install a service or enable access automatically.
- Private per-user JSON settings (0700 directory/0600 file), atomic publication,
  explicit off/read-only/read-write modes and optional existing trusted root.
  Unsafe/malformed settings fail closed. Legacy environment overrides remain
  explicit and are visible in status; changing settings requires a GUI restart.
- `dia-mcp-config` CLI and separate GTK3 settings window with folder chooser,
  saved/effective mode, observed endpoints and restart indication. Embedded Python
  receives only the integration package; the MCP SDK stays external.
- One-command Docker development bootstrap and repeatable local release checks:
  portable, native/build, installed, Wayland, clean Ubuntu package installation,
  documentation targets, version consistency and artifact checksums. No publishing.
- Consolidated installation, user guide, tool reference, development/architecture,
  troubleshooting, security, migration/version policy and acceptance checklist.

Implementation is localized to `config.py`, `config_ui.py`, the live startup hook,
small handshake/error-message additions, package metadata, Task targets and
`build-aux/mcp/{bootstrap,package,release}.sh`, runtime Dockerfile, smoke harness
and release validator. New tests are `test_config.py` and `test_release_validation.py`.
No new native C divergence or generic property codec was introduced in M10.

## Clean-user acceptance and friction

The autonomous smoke harness installs the candidate into a fresh pinned Ubuntu
base with declared APT dependencies, no checkout/compiler tree and a fresh
non-root home. Runtime tests run without network and without live environment
flags. It verifies installed ELF dependencies, default-off GUI, persisted read-only
and read/write/root configuration, multi-domain objects, selection/context,
reviewed alignment/static validation, native GUI Undo/Redo, actual connections,
Save As, SVG/PNG, multiple documents, GUI restart/reopen, rejection of old-session
IDs, real stdio tools/resources/prompts, headless snapshot startup and persisted
disable. The fresh runtime is separate from the compiler/development image.

GTK selection/history are driven by an explicit temporary test plugin. This is
functional automation, not a claim that a human manually performed the entire
[acceptance checklist](user-acceptance.md). The settings window was rendered and
visually inspected at 680×600: controls, folder chooser and footer are visible.
Its real GTK callbacks saved read-only mode with 0600 permissions and opened/
cancelled the chooser. A supplemental native startup test verified that changing
settings leaves the existing process unchanged and requires restart.

Packaging fixes two measured first-run failures: embedded Python initially could
not import the integration without development PYTHONPATH, and the old desktop
entry could launch distribution Dia. Separate launchers resolve both. Remaining
friction: clients must reconnect to the new PID endpoint after GUI restart;
settings restart is explicit; the fixed-prefix package is Ubuntu/Python-ABI specific.

Final review found that a configurator error could incorrectly label preserved
settings as off. Two failing regressions reproduced a rejected update over prior
write mode and an injected directory-sync failure after atomic publication. The
correction reports publication independently and never claims running sessions
changed. All 33 configuration tests then passed; the final candidate was rebuilt
and revalidated. The first complete candidate's evidence is retained separately
under `artifacts/release-initial`, not used as the final deliverable.

## Limits and maintenance risk

The package is unsigned, locally built and not published. Checksums are integrity
records, not signatures. APT dependencies are not snapshot-pinned; no bit-for-bit
rebuild claim is made. AppImage/Flatpak are evaluated but not produced. The private
venv currently retains the existing test tooling; footprint is recorded rather
than hidden. No other architecture, Ubuntu release or Python ABI is supported by
this validation. Source/container workflows remain available.

Normal native/plugin warnings remain documented in earlier reports; arbitrary
plugin crashes cannot be recovered in-process. Compound properties, group-member
editing, layer reassignment and engineering simulation remain outside the generic
ABI. Native callbacks and deferred static checks remain authoritative.

Upstream compatibility risk for this phase is low and localized to the optional
Python startup hook; packaging and settings do not change GTK preferences or the
native model/history/serialization. M8's ownership/transaction internals remain
the more sensitive merge areas. No upstream submission was made.

## Final release evidence

Final local release command completed successfully on 2026-09-21:

| Gate | Observed result |
| --- | --- |
| Portable checks | Ruff clean; 390 tests passed, 64 native tests deselected |
| Native build | 9/9 Meson suites; 454 MCP tests; dependency check clean |
| Installed image, UID 1000, no network | 454 tests passed (50.19 s) |
| Installed real Wayland | 22 GUI tests passed (23.82 s) |
| Real Wayland scale 2 | 22 GUI tests passed (24.85 s) |
| Clean Ubuntu package installation | All ten smoke checks passed as UID 1000, no checkout/compiler/runtime network |
| Source/image comparison | 145 implementation/test/build/lock files identical |
| Documentation/version/checksum | Nine integration documents' local targets, component versions and package hash validated; no skipped gates |

Image: `sha256:7e40d2d44e67e1b2fdd013ae9f012f7bd0665fbcbafe5d2d84a0dbbe0fea0bef`.
Artifact: `dia-mcp-fork_0.98.0+mcp0.3.0-1_amd64.deb`, 22,900,016 bytes.
SHA256: `c500ed7eeb216d9821eaadfe8b547dd16b160faa3ccaadfabd4e9510d9db5862`.
The package contains 5,318 regular files / 96,096,244 payload bytes (symlinks
excluded from these footprint totals). Runtime dependencies are separately
installed by APT and are not included in that package-payload figure.

Durable local evidence is under `artifacts/release`: `release-manifest.json`,
`validation.json`, `checks.json`, logs, `footprint.json`, `install-smoke.json`,
`SHA256SUMS` and the candidate. `supplemental/` retains the settings screenshot,
GTK callback/startup results, scale-2 log, source comparison and the two original
failing configuration regressions. The candidate was not published as a release.
M8, M9 and M10 are complete within the documented capability/platform limits.
