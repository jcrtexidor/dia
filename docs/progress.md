# MCP Development Progress

## Active roadmap

[M8–M10](m8-m10-roadmap.md) is the next sequential roadmap, starting with M8
reliability. M8 is complete: [reliability report](m8-reliability.md), 320 MCP
tests, 9 native suites and 18 real Wayland GUI tests. M9 is also complete: [workflow report](m9-validation.md), 405 MCP tests and
22 Wayland tests. M10 installation and user readiness are next.
M1–M7 below remain the tested baseline, not work to reimplement.

## Current completion

M1–M7 are implemented in the fork. The latest increment completes native
transactions, generic editing, native files, modular semantic helpers and native
layout/context surfaces. See [M3–M7 acceptance, usage and limits](m3-m7-validation.md).
M2's original evidence remains in [m2-validation.md](m2-validation.md).

- M3: atomic batches with native undo/redo and rollback, generation preconditions,
  bounded one-use receipts and explicit ambiguous-outcome recovery.
- M4: generic native factories and safe scalar/text descriptors/properties,
  move/delete/connect/disconnect, including unfamiliar and zero-port custom types.
- M5: native open/Save/Save As/export and conservative dependency reporting;
  unknown-to-MCP native model data is preserved by native serializers.
- M6: extracted UML codec/validation, native topology/domain analysis and creation
  recipes that compose ordinary commands for flowchart/UML/database/network.
- M7: eight native align/distribute modes, summaries, resources, prompt, operation
  timing/correlation and measured bounded-read performance.

GTK3/Meson, snapshot APIs and dependency locks remain in place. Writes are a
separate GUI opt-in (`DIA_MCP_WRITE=1`); files also require `DIA_MCP_FILES_ROOT`.
The external SDK remains separate from the embedded stdlib-only adapter.

## Explicit extension boundaries

Compound property codecs, group-member editing, automatic connector routing,
sheet-specific factory variants and engineering simulation are not advertised.
Disconnect before deleting attached objects. Native plugins/types must be
installed for lossless native round trips. Dependency completeness is not proven.
Membership remains O(N), getters cannot be preempted, and the live interface is
not a sandbox for hostile native plugins. Snapshot reconstruction costs are
unchanged. Runtime catalogs describe their respective GUI/worker installation.

## Latest validation

M9: 341 portable / 405 installed MCP tests, 9/9 native suites, 22 real
Wayland tests. See [M9 workflows](m9-validation.md).

M8: 260 portable / 320 installed MCP tests, 9/9 native suites, 18 real
Wayland tests. See [M8 reliability](m8-reliability.md) for evidence and limits.

### Previous M3–M7 validation

147 portable tests; 199 tests against the installed native image; 9/9 Meson
suites. Real Wayland: all 10 live tests passed at normal scale and all passed at
scale 2 (two completed first, eight pending tests rerun with a fresh runtime).
The [acceptance report](m3-m7-validation.md) records image digest, metrics and
limits. All implementation/test/build/lock files were checked against the image.

## Validation history

## M2 final validation

- `task mcp:check`: Ruff lint/format pass, 100 passed, 44 native deselected.
- `task mcp:build`: 9/9 Meson suites, 144 MCP tests, `pip check` passed.
- `task mcp:test`: 144 passed as UID/GID 1000:1000, network disabled, Xvfb.
- Installed live tests on real Wayland: 2 passed; repeated with `GDK_SCALE=2`:
  2 passed. Actual `GdkWaylandDisplay`, concurrent reads plus GTK interaction,
  native Delete/Undo/Redo, default-document replacement and File/Quit cleanup.
- 46 implementation/test/build/lock files match the validated image exactly.
- Final image: `sha256:347896bf8accacec7b9f6490634c0703a3ed07c1af733dcd2cac3315bd33c029`.
- No dependency-lock, snapshot schema or GTK version changes.

Nonfatal native text-cursor diagnostics during automated GUI actions are recorded
for review in the validation report; they are not claimed as a proven upstream
bug. The M3–M7 completion below supersedes the historical M2 scope.

## Historical M1 tests

Initial `task mcp:check`: 62 passed, 41 native deselected. After discovery:
78 passed, 42 native deselected; Ruff lint/format checks pass (21 Python files).
Changed-Python native discovery and real MCP stdio: 2 passed, including an unfamiliar
custom sheet and refresh. Regression coverage includes malformed/oversized worker
reports and preservation of the existing missing-response error.

Final `task mcp:build` (with a writable temporary `DOCKER_CONFIG`): 9/9 Meson suites,
120/120 MCP tests, and `pip check` successful. `task mcp:test`: 120/120 tests passed
in the installed image, as UID/GID 1000:1000, with no network and Xvfb. Final image:
`sha256:c000d409a98018181edc415f5222750f0cfac074fa4ba310cc90e092d58b57d4`.
`git diff --check`, documentation links and inventory totals/unique type names
were also checked. No C files, dependency locks or document schema changed.

The first complete build found one error-message compatibility regression (114
passed/1 failed); preserving the established missing-response message fixed it.
The final results above include that regression. The initial Buildx attempt could
not write to the sandbox's read-only `~/.docker`; only its temporary config path
was changed, without changing workstation settings or copying credentials.

## Ubuntu 26 compatibility

Observed host: Ubuntu 26.04.1 LTS, Wayland session. Native audit container:
Dia 0.98.0, GTK 3.24.52, GLib 2.88.0, libxml2 2.15.2. Initial integration checks
use Xvfb. A separate run without Xvfb, with `GDK_BACKEND=wayland` and the host
compositor socket, observed `GdkWaylandDisplay` inside Dia and passed runtime
discovery, two-node creation, connection and SVG export (1450 bytes). This verifies
the M1 CLI worker on Wayland. M2 now additionally verifies the running GUI,
selection, native history actions and shutdown on this real compositor as recorded
in the historical M2 report. M3–M7 real-GUI validation is recorded in the current
acceptance report. Dependencies and project locks remain unchanged.

## Upstream compatibility risks

Three preexisting native divergences: importer failure propagation, CLI export
failure status and custom-shape connection directions after flips. M2 adds localized lifecycle, UUID, generation, shutdown and PyDia read hooks;
see upstream differences. M3–M7 adds native transaction/file wrappers and
serializer-close error propagation; those are sensitive future merge areas. Work stays in the fork under its documented contribution policy.
