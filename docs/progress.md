# MCP Development Progress

## Current objective

Deliver M2: an opt-in, bounded, read-only connection to the running Dia GUI,
while preserving the completed M1 discovery and snapshot editing/export backend.
Audit baseline `77fe10bc0`; implementation date 2026-09-19.

## Completed

- Repository, fork diff, native/PyDia model, plugin/sheet loading, current MCP
  communication, contracts, undo and concurrency audit.
- Current and proposed [architecture](mcp-architecture.md), complete
  [capability inventory](mcp-capabilities.md), all 887 runtime type names plus
  38 sheets in [JSON](mcp-runtime-inventory.json), [tool reference](mcp-tools.md),
  [development guide](mcp-development.md) and [upstream differences](upstream-differences.md).
- First improvement: `list_sheets` / `list_object_types`, fresh native discovery,
  pagination, palette labels and MCP creation markers; bounded response validation.
- Unit, native multi-domain/custom-sheet discovery and actual stdio coverage.
  Existing creation contract and native C files preserved.

## In progress

M2 implementation and targeted tests are passing. Final packaged build and a
repeat of the final revision on real Wayland are pending; M2 is not yet marked
complete.

- Foundation: native ephemeral IDs, detach/destruction/copy invalidation,
  pre-import document identity reset and conservative editor generation.
- Transport: protocol v1, strict bounded JSON lines, same-user private Unix
  socket, GLib I/O plus bounded idle dispatch, no receiver threads/locks.
- Read registry: no wrappers retained, current membership resolution, mixed/custom
  types, layers/selection, native connections and conservative properties.
- Normal shutdown: confirmed application exit notification with GIL-safe Python
  callback, closing clients/queue/socket before native document destruction.
- Integration: nine `live_*` tools through Operations/LiveClient; existing snapshot
  tools and M1 discovery preserved.

First checkpoint: 9/9 Meson suites and 136 MCP tests passed against a rebuilt
native development container. Initial Xvfb and real Wayland GUI tests passed.
The final tests additionally cover real File/Quit cleanup, wire rejection,
endpoint recovery, unsupported getters and interaction during continuous reads.

## Next

1. Finish M2 packaged/Wayland acceptance and record final evidence.
2. M3: native atomic commands, rollback and coherent GUI undo/redo.
3. M4: property introspection and safe generic editing across arbitrary factories.
4. M5: native open/Save/Save As with dependency reporting and data preservation.
5. M6: modular semantic helpers; M7: existing layout commands, summaries/resources/
   prompts, observability and measured performance work.

Each milestone has acceptance criteria in the architecture document. Do not start
a broad rewrite or implement all domain tools before these foundations.

## Architectural decisions

Keep GTK3/Meson, locks, transactional snapshots, validated native exports, stdio
SDK separation and current C fixes. Reuse PyDia discovery after plugin loading.
M2 uses GLib nonblocking I/O and idle dispatch, not receiver threads. Lazy native
UUID tokens avoid wrapper retention and object ABI changes. Detach/undo invalidates
identity deliberately. Conservative generations detect editor invalidations, not
exact edit counts; M3 must strengthen transactional preconditions. Runtime sheet
membership reuses M1 sources but is cached per GUI session, while worker discovery
stays fresh. Normal Dia shutdown does not finalize Python; an explicit confirmed
shutdown notification replaces reliance on Python atexit.

## Supported diagram domains

Native: all 38 runtime palettes, including UML, flowchart, database/ER, network,
electrical/electronic/logic, pneumatic/hydraulic, engineering/civil, telecom,
process/control, requirements and custom shapes; mixed diagrams are valid.
MCP editing: 13 nodes across Flowchart/UML/Electric/Pneum, four connectors.
Other registered types are discoverable, not yet generically editable. Electrical
symbols do not imply engineering simulation/validation.

## Generic Dia capabilities

Session create/inspect/close, allowlisted create/update/move/connect, native
Dia/SVG/PNG export, runtime sheet/type enumeration, and M2 live document/layer/
selection/object/connection reads with a conservative property subset. No live
write commands, delete/disconnect/group/layout or native undo through MCP. Registry types outside sheets and duplicate palette labels are kept.

## Known issues

- Live GUI reads are implemented; native transactional mutations remain M3.
- Live object membership resolution remains O(N); large native membership tuples
  are allocated before the traversal limit. Arbitrary native getters cannot be
  preempted. No constant-time lookup or untrusted-plugin isolation is claimed.
- PyDia setters/moves do not supply a remote-safe native transaction/history layer.
- Creation schema is fixed; the generic `properties` parameter is UML-only, and
  connector labels/UML terminal policy leak domain assumptions into core service.
- No file-open/import or preservation of unmodeled native data; do not rebuild
  user diagrams with the restricted snapshot contract.
- Native missing sheet entries can be pruned before discovery. Property schema,
  entry creation data, icons and native export/version tools remain missing.
- A runtime capture describes the worker installation, not the host GUI profile.

## Technical debt

Full snapshot reconstruction and full inspection response on each edit; no batch
operations or targeted object reads. Limited structured logging and error detail.
Public package metadata is 0.2.0 but `__init__.__version__` still says 0.1.0.
Domain tuple conversions are native-specific; no automatic complete JSON property
codec exists. Live wrappers remain callback-local; concurrent reads and native lifecycle are tested.

## Tests

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
the native CLI worker on Wayland; interactive live selection/history remains
unimplemented and untested. Dependencies and project locks unchanged.

## Upstream compatibility risks

Three preexisting native divergences: importer failure propagation, CLI export
failure status and custom-shape connection directions after flips. M2 adds localized lifecycle, UUID, generation, shutdown and PyDia read hooks;
see upstream differences. Native transactional undo/property wrappers remain the
likely sensitive future merge areas. Work stays in the fork under its documented contribution policy.
