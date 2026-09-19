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

Standalone Dia remains a normal desktop application. **There is no current command
that attaches MCP to its open window.** `task mcp:serve` starts isolated workers,
not a live plugin or GUI listener. Opening an exported `.dia` in the GUI works,
but further MCP edits do not update that open document.

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

For the future live backend, also open the GUI and test manual selection, remote
inspection, one atomic edit, undo/redo from the GUI, document close while requests
are queued, redraw and continued manual interaction. That live acceptance cannot
be satisfied by today's snapshot worker. Record separately: host session, actual
GTK backend, native stack versions, subprocess tests and interactive behavior.
