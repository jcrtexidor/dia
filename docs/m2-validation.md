# M2 acceptance evidence — 2026-09-19

M2 is implemented and accepted for opt-in **read-only** inspection. This record
covers the actual packaged code, not a proposed boundary. M3 native writes,
rollback, Save/Save As and semantic expansion are not implemented.

## Implemented components and changed files

| Component | Files |
| --- | --- |
| Native object lifetime tokens | `lib/object.c`, `lib/object.h`, `lib/diagramdata.c` |
| Document identity and conservative generation | `app/diagram.c`, `app/diagram.h` |
| Confirmed application shutdown notification | `app/dia-application.c`, `app/dia-application.h`, `app/app_procs.c` |
| Read-only PyDia accessors, descriptor-only metadata and GIL-safe shutdown registration | `plug-ins/python/pydia-object.c`, `pydia-layer.c`, `pydia-diagram.c`, `diamodule.c` |
| Opt-in normal startup plugin | `plug-ins/python/mcp-live.py`, `plug-ins/python/meson.build` |
| Versioned protocol, bounded GLib listener, callback-local registry, external client | `mcp/src/dia_mcp/live/` |
| Operations and nine live MCP adapters | `mcp/src/dia_mcp/service.py`, `server.py` |
| Contract/safety, real GUI and real stdio tests | `mcp/tests/test_live.py`, `test_live_native.py`, `live_fixture.py`, `test_protocol.py` |
| Architecture, usage, capabilities, progress and native differences | `docs/mcp-architecture.md`, `mcp-tools.md`, `mcp-development.md`, `mcp-capabilities.md`, `progress.md`, `upstream-differences.md`, this report, root and MCP READMEs |

The protocol is JSON-lines version 1 with a mandatory handshake exposing actual
Dia version, integration API version, session ID, capabilities and limits.
GLib I/O callbacks validate and queue; separate main-context idle callbacks perform
all native reads. No native wrappers survive a request. IDs are opaque runtime
UUIDs scoped by process/document; close/reload/detach invalidates references.
Native undo restoration has a new ID. Generations are conservative observed
editor invalidations, not exact edit counts or transactional write guarantees.

The socket is opt-in, local Unix-only, mode 0600 inside private user directories,
with peer-UID checks, endpoint locking and bounded input/output/queue/client counts.
There are no remote code, shell, pointer, environment or plugin-loading commands.
This inherits installed Dia plugins' trust and is not an OS sandbox.

The preserved snapshot path still uses isolated native workers for creation,
editing and export. Snapshot and live ownership/IDs remain distinct.

## Executed results

| Check | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/dia-uv-cache task mcp:check` | Ruff lint/format pass; 100 passed, 44 native deselected |
| `DOCKER_CONFIG=/tmp/dia-m2-docker-config task mcp:build` | Full native build/install; 9/9 Meson suites; 144/144 MCP tests; `pip check` passed |
| `task mcp:test` | Installed package, UID/GID 1000:1000, network disabled, Xvfb: 144 passed in 32.04 s |
| Installed `test_live_native.py`, actual compositor, `GDK_BACKEND=wayland`, no Xvfb | 2 passed in 2.86 s; asserts actual `GdkWaylandDisplay` |
| Same installed Wayland tests with `GDK_SCALE=2` | 2 passed in 2.71 s |
| Source/image comparison | 46 Python/native/build/lock files identical; no implementation/test mismatch |
| `git diff --check` | Passed |

Validated image:
`sha256:347896bf8accacec7b9f6490634c0703a3ed07c1af733dcd2cac3315bd33c029`.
Host: Ubuntu 26.04.1 LTS, real Wayland compositor. The container GUI used that
compositor socket as UID 1000, with a private runtime and no network or privileged
mode. Source checkout was not substituted for the installed package in these
final acceptance runs. Documentation-only completion records were updated after
this image was tested; implementation and tests match the image.

The automated GUI fixture creates/opens documents using Dia, selects objects,
changes properties/positions, duplicates, groups, deletes, restores through real
GTK Delete/Undo/Redo actions, changes active layers and closes/reopens documents.
A separate MCP stdio process exercises all nine live tools. Cross-document
object references are rejected explicitly. Concurrent pools perform 80
reads and then continuous reads while the GTK test driver changes selection;
a GTK heartbeat advances and the interaction completes within two seconds.
No production live endpoint exposes the fixture's mutation commands.

Domains exercised: UML, flowchart, ER, database, Cisco/network, electrical, a
custom unfamiliar shape/sheet, Standard line and group objects. Tests establish
actual native point/handle attachment versus an unattached handle. Geometry is
read directly from document-space native values, not screen coordinates.

Protocol tests cover incompatible versions, handshake enforcement, unsupported
actions, disconnect/reconnect, bounded schemas/pages/messages, timeout and queue
cancellation, cross-session errors, generation updates, unsupported property
getters, private directory/symlink rejection, active endpoint locking and owned
stale-socket recovery. File/Quit verifies the native shutdown notification and
socket removal. Snapshot, M1 and existing error-contract regressions all pass.

## Revalidated assumptions and M3 prerequisites

- Raw PyDia object wrappers are unsafe to retain. M2 resolves current ownership
  from fresh wrappers within each callback; native lifetime UUIDs carry identity.
- Import can reuse the default document. Reset identity before import, including
  failed imports, rather than relying only on add/close events.
- Python `atexit` is insufficient for normal Dia shutdown; Dia does not finalize
  the embedded interpreter. A confirmed application notification is required.
  The Python callback acquires the GIL, including when GTK is entered via PyGObject.
- Ordinary PyDia property lookup already fetches a native value before `.value`
  is accessed. M2 adds descriptor-only metadata so unsupported values are never
  requested. Merely avoiding `.value` was insufficient.
- Recursive nested Python visitors can retain wrapper-containing results through
  a closure cycle. M2 uses iterative traversal and tests immediate release with
  cyclic GC disabled.
- A receiver thread is unnecessary: GLib nonblocking I/O and separate idle dispatch
  satisfy the boundary without cross-thread synchronization.
- Native undo does not promise persistent remote object identity. Detached and
  restored objects deliberately receive fresh references.
- No suitable complete monotonic native revision was found. M3 needs comprehensive
  mutation/precondition coverage, coherent native transaction points, rollback,
  redraw and documented identity behavior before enabling writes.

Scaling limits remain: O(N) membership resolution, PyDia membership tuple
allocation before traversal limits, and non-preemptible trusted native getters.
Pages are not frozen across GUI edits; compare generations and restart as needed.
Property inspection intentionally excludes aggregate/image/file-backed values.
Sheet metadata is cached for the running GUI session. These are explicit M2
limits, not implemented M3/M4 features.

## Native diagnostic — internal review draft, not an upstream submission

The fixture's automated native selection/history sequence emits nonfatal
`dia_text_set_cursor: assertion 'DIA_IS_RENDERER (renderer)' failed` messages under
Xvfb and Wayland. Reads, native actions, heartbeat, exit and all assertions still
pass. This observation has **not** been isolated on an unmodified upstream build;
it must not be represented as a confirmed upstream regression or as a normal
mouse-driven reproduction.

Reproduction for review: run the installed
`test_live_gui_lifecycle_domains_concurrency` with pytest `-s`, as described in
[mcp-development.md](mcp-development.md#wayland-acceptance). The candidate path is
`app/textedit.c` calling `dia_text_set_cursor` during automated selection/focus.
A focused follow-up should separate fixture initialization timing from native
focus/renderer lifecycle, and reproduce without M2 before assigning upstream
causality. No unrelated text-editor fix is included in M2.

The custom fixture intentionally omits an icon and also logs its missing-icon
warning; Glycin reports its existing container sandbox warning. Neither is a
claim that the live boundary provides sandboxing.

`README.md` and `docs/modernization/contributing.md` explicitly prohibit sending
AI-generated code, issues or support requests to GNOME. This internal diagnostic
is retained in the fork for the user's review; nothing was submitted upstream.
