# Developing Dia MCP on Ubuntu 26

This fork builds native Dia with Meson and runs MCP in an external Python venv.
Keep `mcp/uv.lock`, `mcp/requirements.lock`, the pinned container base and existing
native dependencies. No GTK4 migration or alternate build system is required.
The supported development commands are in the root `Taskfile.yml`.

## Setup and build

The current workstation is Ubuntu 26.04.1 LTS, with a Wayland session. The
container uses Ubuntu 26.04, native GTK3 and Python embedding. `build-aux/mcp/Dockerfile`
is the exact dependency recipe: compiler toolchain, Meson/Ninja/pkg-config,
GTK3/GLib, Cairo, Graphene, libxml2, Python development/embedding, PyGObject,
gettext, image loaders, fonts, Xvfb and xauth. It pins xpm-pixbuf in the build copy.
The public server requires Python >=3.12 and MCP 1.30.0; pytest and Ruff versions
are pinned. `BUILDING.md` covers native builds outside Docker.

```sh
# From the repository root, with Docker, Task and uv available:
task mcp:check        # locked venv, Ruff, non-native tests
task mcp:build        # compile/install fork; Meson and MCP tests in Ubuntu 26
task mcp:test         # test installed package/native Dia and real MCP stdio
```

If the environment restricts the default uv cache, use
`UV_CACHE_DIR=/tmp/dia-uv-cache task mcp:check`. Do not reinstall or upgrade
dependencies to work around a cache path. Native compilation is intentionally
inside the existing image workflow, not against a different host Dia package.

If Docker Buildx cannot write its activity file under a read-only `~/.docker`,
create a dedicated temporary directory and run
`DOCKER_CONFIG=/tmp/dia-mcp-docker-config task mcp:build`. This audit used that
workaround for the public build; no credentials or global settings were copied.

## Start MCP and standalone Dia

`task mcp:serve` starts `dia-mcp --workspace /workspace` through Xvfb in the image,
with `artifacts` mounted as the output workspace, no network and the caller's UID.
Connect an MCP client with command `task` and arguments
`["--dir","/absolute/path/to/dia","mcp:serve"]`. The server speaks stdio;
stdout is protocol-only. A native installation can instead run:

```sh
uv run --directory mcp --locked dia-mcp --workspace "$PWD/artifacts" \
  --dia-binary /absolute/path/to/installed/dia --timeout 30
```

The timeout must be >0 and <=300 seconds. A display supported by the build may be
needed even for CLI operations; use Xvfb in headless CI. The embedded interpreter
is Dia's system Python, not the MCP venv; `import dia` in an ordinary shell Python
is not the integration path.

Standalone Dia remains a normal desktop application. `task mcp:serve` still starts
isolated workers by default. M2 adds a separate opt-in live read path; snapshot
edits do not update a GUI document. Live mutation requires a separate local opt-in.

## Enable native editing and files

Follow the normal live startup below, adding `DIA_MCP_WRITE=1` for editing and
`DIA_MCP_FILES_ROOT=/absolute/trusted/directory` for native open/save/export.
Read the [current command/receipt workflow](m3-m7-validation.md) before using
mutations. A timeout is not proof that a native operation did not commit; query
the prepared receipt. Run all `test_live*_native.py` files under Xvfb and real
Wayland to validate M2–M7 together.

## Enable live inspection

Build/install the fork (`task mcp:build` for the supported image) including its new
PyDia lifetime hooks and normal `mcp-live.py` plugin. The embedded system Python
must be able to import `dia_mcp.live` and PyGObject; it does not need FastMCP.
For a native development install, from the checkout:

```sh
DIA_MCP_LIVE=1 PYTHONPATH="$PWD/mcp/src" /absolute/path/to/installed/dia
```

Keep the normal Dia Python startup. Do **not** set `DIA_PYTHON_PATH` to the snapshot
worker's `native/` directory. Normal user plugins and sheets still load normally.
Without `DIA_MCP_LIVE=1`, the new startup plugin imports no MCP code and creates
no endpoint. Older Dia builds without the new hooks fail clearly at startup.

Stderr prints the endpoint `$XDG_RUNTIME_DIR/dia-mcp/live-<pid>.sock` after GTK
startup. The runtime must exist, be owned by the user and private (0700). M2
creates its own 0700 subdirectory and 0600 Unix socket, verifies peer UID and
never listens on TCP. Keep the printed PID-specific path; do not guess the active
process when several Dia instances are open.

Start the external stdio server, using that printed path:

```sh
uv run --directory mcp --locked dia-mcp --workspace "$PWD/artifacts" \
  --dia-binary /absolute/path/to/installed/dia \
  --live-socket "$XDG_RUNTIME_DIR/dia-mcp/live-<actual-pid>.sock"
```

Call `live_handshake`, `live_list_documents`, then `live_get_selection` for a live
document ID. All original snapshot tools remain available. If either process
restarts, reconnect; after a GUI restart enumerate fresh IDs. The current client
opens a bounded handshake/read connection per operation.

A containerized GUI additionally needs access to the compositor socket under its
own private runtime directory, matching the host UID, and an explicit shared
socket directory if MCP runs outside that container. Do not mount arbitrary host
runtime contents or use privileged/network modes. The live test below can run
with the GUI and external MCP client together inside the validation container.

The embedding `Limits` object configures queue/client/message/page/property/
traversal limits. Defaults are documented in the architecture; no request may
change them. MCP `--timeout` controls the client (maximum live timeout 30 seconds),
not the GUI listener. Debug with `live_handshake` and the Dia stderr startup line;
never log full document contents or native wrapper reprs. A `.sock.lock` inode is
intentionally retained after shutdown; do not remove an active listener's lock.
Stale endpoint recovery verifies type/ownership and takes the lock first.

## Inspect the installed runtime

Call `get_capabilities` for the MCP editing contract; `list_sheets` for installed
palettes; `list_object_types` for factories and labels. Continue pagination until
`next_offset` is null. `creatable_as=null` means MCP cannot create that native type
yet. The API intentionally does not derive its allowlist from this checked-in
[audit snapshot](mcp-runtime-inventory.json).

To regenerate a full native-worker inventory (developer operation, not a new MCP
tool), run this from the root after building the image:

```sh
mkdir -p artifacts
docker run --rm --init --network=none --user "$(id -u):$(id -g)" \
  dia-mcp:ubuntu26 xvfb-run -a python -c \
  'from dia_mcp.backend import NativeBackend; print(NativeBackend().discover().model_dump_json(indent=2))' \
  > artifacts/runtime-catalog.json
```

Record date, source revision, image ID (`docker image inspect`), and `dia --version`
when promoting a capture to documentation. `dia --list-filters` reports normal
startup filters; set `DIA_PYTHON_PATH` to the installed package's `native` directory
to inspect the dedicated MCP startup's filters. Normal Python exporters can differ.

The audit's metadata capture queried the existing compiled image while loading
this increment's Python adapter from a read-only bind mount. Full build/test below
checks the packaged result as well. It does not claim that 887 types exist in
every install, language, custom profile or GUI session.

## Debug workflow

Start with the smallest failing request and preserve its prior document/revision.
Use the same executable, image, startup path and display as the failing client.
Structured errors distinguish invalid input, unavailable backend, timeout, native
import failure and export/publication failure. Worker stderr tails appear in
backend errors; do not print debug data to MCP stdout or log whole user documents.
There is no dedicated per-request verbose tracing flag yet.

For rapid Python-only development before a full rebuild:

```sh
docker run --rm --init --network=none --user "$(id -u):$(id -g)" \
  -e DIA_MCP_NATIVE=1 -e PYTHONPATH=/checkout/mcp/src \
  -v "$PWD:/checkout:ro" dia-mcp:ubuntu26 \
  xvfb-run -a python -m pytest -q -p no:cacheprovider /checkout/mcp/tests
```

This tests changed Python against the image's compiled native core; it does not
validate newly changed C. Rebuild for native changes or final package verification.
Inspect `docs/progress.md` for current actual results; old validation documents
are dated evidence, not the result of the latest checkout.

## Add an operation or capability

1. Define a transport-independent operation and structured result/error. Put schema
   validation in the contract and service, PyDia adaptation in `native/`, process
   lifecycle in `backend.py`, and transport registration in `server.py`.
2. Identify whether the operation needs an open GUI or native history. The existing
   snapshot backend does not provide those; follow M2/M3 in the architecture before
   adding GUI mutations. Never pass native wrappers to a worker thread.
3. Use actual loaded factories/sheets, not a copy of all names. Discovery is performed
   in an importer callback after plugin and sheet loading. Keep catalog reads free
   from object construction; defaults/property inspection should be a separate,
   bounded operation for a selected type.
4. Add an observable unit test and a native test for geometry, properties or behavior
   that a fake backend cannot establish. New tools need a real stdio client test.
5. Update the tool reference, architecture/capabilities and progress. Regenerate the
   document schema only if the document contract changes. This discovery increment
   does not change it or dependencies.

Do not widen the current creation enum to all discovered names until generic
property/handle/connection support can represent them. Some objects lack connection
points or create handles; sheet variants may require hidden creation data. The
current bridge's fallback assumes technical symbols and is not a generic setter.

## Custom sheets and semantic tools

Install trusted custom `.shape` and `.sheet` files using Dia's established user
paths or explicit `DIA_SHAPE_PATH`/`DIA_SHEET_PATH`. Those environment variables
replace system fallback directories; include installed directories to extend the
catalog. `test_native_discovery.py` demonstrates a temporary custom shape/sheet,
read-only discovery, and freshness after removal. No hard-coded registration is
needed in MCP for listing it. Missing factory references may be pruned by Dia,
with diagnostics on stderr; metadata alone does not report every broken source.

For semantic tools, prefer a small module for a proven domain; compose generic
commands and leave transport unaware of native tuple layouts. Preserve current UML
direction and typed member behavior when extracting it. Test at least flowchart,
UML, ER/database, network and an additional technical family as capabilities become
editable. A custom unknown type must eventually pass creation/property/move/delete
tests too; the current custom fixture establishes discovery only.

## Wayland acceptance

Xvfb tests verify GTK3 under X11 on Ubuntu 26, not a Wayland compositor. Host
`XDG_SESSION_TYPE=wayland` alone is not evidence that the worker used Wayland.
For an installed fork in a real Wayland session, set `GDK_BACKEND=wayland`, leave
`WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR` pointing to that compositor, and run a discovery,
create/connect/export cycle without Xvfb. Do not hard-code those user's paths into
the product. A container needs access to the specific compositor socket with the
same UID and an explicit runtime directory; no privileged mode is necessary.

This audit also ran the native worker against the host Wayland socket, explicitly
observed `GdkWaylandDisplay` inside Dia, and passed discovery/create/connect/SVG
export without Xvfb. That validates the CLI worker on this desktop stack, not the
future interactive live integration.

M2 automated live tests are in `test_live_native.py`, using the normal installed
startup plugin, a real GTK GUI and a **separate** MCP stdio process. The fixture
uses trusted local test code to manipulate Dia and activate native GTK actions;
none of its control commands exist in the production live protocol.

```sh
# Headless native acceptance against installed fork/package:
DIA_MCP_NATIVE=1 xvfb-run -a python -m pytest -q mcp/tests/test_live_native.py

# Repeat in the actual Ubuntu 26 Wayland session, without Xvfb:
DIA_MCP_NATIVE=1 GDK_BACKEND=wayland python -m pytest -q mcp/tests/test_live_native.py
```

Run these inside the supported image or the matching native environment; when
using source Python, set `PYTHONPATH` to the absolute `mcp/src` directory. For an
installed package the fixture passes its actual package location to the embedded
interpreter. Wayland mode requires the actual compositor socket, not merely the
session environment label. The test asserts `GdkWaylandDisplay`.

Coverage includes GUI document creation/opening, layers, mixed built-in and custom
objects, native attachment versus proximity, selection, property/move changes,
duplication, removal/restore, real GTK Delete/Undo/Redo, groups, default-document
replacement, concurrent reads with an active GTK timer, stdio MCP, reconnect and
confirmed File/Quit socket cleanup. Separate tests reject incompatible versions,
missing handshakes and unsupported actions, and disconnect clients with pending
reads. Unit tests cover bounds, timeout/cancellation, wrong session, generation,
unsafe property getters, endpoint permissions/locking and stale socket recovery.
No MCP tool mutates the fixture: writes happen exclusively on the trusted GUI side.

For an interactive smoke check, select objects with the mouse while querying
`live_get_selection`; drag them while querying `live_get_object`; close/reopen
and confirm the previous IDs fail. M2 reads only document-space geometry, so no
window-coordinate conversion or display scaling is involved. Native editing,
rollback and undo through MCP are tested separately by the M3–M7 native suites.
