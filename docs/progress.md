# MCP Development Progress

## Current objective

Audit Dia as an extensible multi-domain application, record the smallest path to
live integration, and deliver the first bounded implementation: native runtime
sheet/type discovery. Baseline `77fe10bc0`; audit date 2026-09-19.

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

M2 implementation in progress. Foundation: lazy runtime object tokens without an
object ABI change, invalidation on detach/destruction/copy, document identity
reset before import, conservative editor generation, and PyDia read accessors.
No wrappers are retained between live requests. Initial running-GUI validation
covers native Delete/Undo/Redo, mixed/custom types and concurrent reads.
Foundation validation: 9/9 Meson suites and 136 MCP tests pass against the rebuilt
native development container; the final packaged build and Wayland acceptance
are still pending. M2 is not yet marked complete.

## Next

1. M2: live read-only boundary, handshake, main-thread dispatch, stable registry,
   selections/layers and lifecycle invalidation.
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
No native API or IPC is added for this increment. Treat the proposed live boundary
as future work; no running GUI is reachable from today's tools. Separate installed
factory discovery from supported editing. Keep metadata uncached for correct
freshness with the current short-lived workers.

## Supported diagram domains

Native: all 38 runtime palettes, including UML, flowchart, database/ER, network,
electrical/electronic/logic, pneumatic/hydraulic, engineering/civil, telecom,
process/control, requirements and custom shapes; mixed diagrams are valid.
MCP editing: 13 nodes across Flowchart/UML/Electric/Pneum, four connectors.
Other registered types are discoverable, not yet generically editable. Electrical
symbols do not imply engineering simulation/validation.

## Generic Dia capabilities

Session create/inspect/close, allowlisted create/update/move/connect, native
Dia/SVG/PNG export, runtime sheet/type enumeration. No current GUI selection,
layer commands, generic properties, delete/disconnect/group/layout or native undo
through MCP. Registry types outside sheets and duplicate palette labels are kept.

## Known issues

- Main goal of manipulating an open GUI document is not implemented.
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
codec exists. Future live wrapper ownership and concurrency require explicit tests.

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

Only three preexisting native divergences: importer failure propagation, CLI export
failure status and custom-shape connection directions after flips. This increment
adds no C changes. Future registry/undo/property wrappers are the likely sensitive
merge areas. Work stays in the fork under its documented contribution policy.
