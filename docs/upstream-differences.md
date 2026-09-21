# Intentional differences from upstream Dia

Audit: 2026-09-19. Compare to upstream base
`ad68cc378b7a187706bc2648c48b44d16fb80819`; initial fork HEAD `77fe10bc0`.
These are local-history findings, not a claim about the latest remote upstream.
The fork README/contribution policy keeps this AI-assisted work in
`jcrtexidor/dia`; it is not submitted to GNOME upstream.

## Modified native files

| File / hook | Behavior and rationale | Category / merge risk |
| --- | --- | --- |
| `plug-ins/python/diamodule.c`, `PyDia_import_data` | Interpret importer return before releasing it; propagate false/truth-testing errors, retain historical None-as-success. Required for trustworthy operations rollback. | Generally useful error propagation; localized conflict risk around importer callback. |
| `app/app_procs.c`, `do_convert` | Check native exporter boolean result and exit nonzero on failure. Prevents treating failed output as success. | Generally useful CLI correctness; localized conversion-flow conflict risk. |
| `objects/custom/custom_object.c`, `custom_update_data` / `custom_create` | Recompute connection routing directions from original shape geometry on every update, respecting flips, rather than setting them only at creation. | General custom-shape correctness supporting technical diagrams; medium risk in geometry/connection changes. |

M1 discovery changed no C. M2 introduces the following narrow native hooks;
there is no new object ABI layout or arbitrary remote execution. M3 adds the
separate native transaction bridge described below.

| M2 files / hook | Actual behavior | Merge risk |
| --- | --- | --- |
| `lib/object.{c,h}` | Lazy UUID lifetime tokens outside `DiaObject`; reset at init/copy/destruction | Localized object lifecycle helpers; no struct/serialized metadata change |
| `lib/diagramdata.c::data_emit` | Invalidate detached objects, group members and removed-layer contents before removal notifications | Localized membership notification path |
| `app/diagram.{c,h}` | GObject-owned document UUID/generation; reset before load/import; conservative counters at editor redraw/modified entry points | Localized editor lifecycle/invalidation helpers |
| `plug-ins/python/pydia-{diagram,layer,object}.c` | Read-only live state/IDs plus object position, children, group membership and bounded descriptor-only inspection | Small PyDia accessor changes; existing ownership is unchanged |
| `plug-ins/python/diamodule.c` | Actual application version and a trusted local shutdown callback registration | Python module initialization/method table |
| `app/dia-application.{c,h}`, `app/app_procs.c` | Confirmed shutdown signal, before diagrams are released | Small application lifecycle hook; canceling quit does not emit it |
| `plug-ins/python/mcp-live.py`, `meson.build` | Install opt-in startup shim for the separate live package | No MCP dependency/import when disabled |

The live listener/protocol/registry implementation lives in `mcp/src/dia_mcp/live/`.
M3–M7 now add bounded native command/file dispatch. Installed trusted
plugins still share Dia's process; this boundary is not a sandbox.

## MCP-specific additions

| Files | Role / divergence |
| --- | --- |
| `mcp/src/dia_mcp/models.py`, `service.py`, `errors.py` | Typed session snapshots, transactions, UUIDs, bounded creation contract, structured failures and workspace publication. Experimental API v1, not Dia's native ABI. |
| `mcp/src/dia_mcp/backend.py` | Restartable native CLI worker per render or discovery, dedicated Python startup, timeout and artifact/report validation. |
| `mcp/src/dia_mcp/native/{bridge,catalog,python-startup}.py` | Embedded stdlib-only importer, narrow factories, UML tuple adaptation, technical-symbol geometry and native attachments. Main area for adapting future PyDia changes. |
| `mcp/src/dia_mcp/{discovery.py,native/discovery.py}` (this increment) | Bounded metadata contract and generic factory/sheet enumeration. No duplicated native object catalog or factories instantiated by listing. |
| `mcp/src/dia_mcp/server.py` | FastMCP stdio adapter, tool schemas and annotations. Two discovery tools and nine opt-in live read tools alongside the original nine. |
| `mcp/tests`, `mcp/examples` | Unit/native/protocol regression tests and editable diagram examples. New tests cover runtime metadata, custom sheets and pagination. |
| `mcp/pyproject.toml`, `uv.lock`, `requirements.lock` | Independently pinned external SDK environment; no SDK dependency injected into native Dia. |

## Build, automation and documentation additions

`Taskfile.yml`, `.github/workflows/mcp.yml`, `build-aux/mcp/`, `.dockerignore` and
fork-specific `.gitignore` entries supply repeatable Ubuntu 26 builds/tests and
local stdio startup. The image pins its base and xpm-pixbuf revision without
changing upstream's source wrap. `README.md` links the fork additions while
retaining upstream authorship/policy. `docs/modernization/` contains the prior
API, source audit, GTK4 plan and validation; `docs/mcp-*.md`, the runtime inventory,
this document and `docs/progress.md` record the current audit and milestones.

Highest future merge risks: intrusive edits to Diagram/undo ownership, PyDia
wrappers and object-property descriptors. Prefer narrow application integration
wrappers there, with protocol/semantics in `mcp/`, instead of spreading MCP names
throughout upstream internals. Native type version numbers, plugin ABI and MCP
API version must remain distinct. Preserve the existing C regressions when
merging upstream equivalents of these fixes.

## M3–M7 additions

- `pydia-live.c/.h`: GTK-thread native transaction staging, typed property validation,
  native history and existing align/distribute helpers. No persistent alternate history.
- `pydia-live-files.c/.h`: native import/serialization and post-publication saved marker.
- `diamodule.c` and Python Meson source list: register/init those explicit APIs.
- `pydia-object.c`: descriptor load-only/widget flags for safe editability reporting.
- `lib/dia-io.c`: propagate final XML-writer close errors; see the internal
  [upstream candidate](upstream-save-close.md). No upstream submission is authorized.
- `live/{operations,files}.py` and protocol/registry: receipts, native mutation dispatch,
  generation fence, safe atomic file publication and context analysis.
- `native/uml.py`, `semantics.py`, `recipes.py`: extracted snapshot UML policy and
  evidence-based generic-command helpers; dependency locks and snapshot schemas intact.
- Server: 32 total tools, two resources (one templated) and one prompt.

Native undo stack internals, object property ABI and serializer/error semantics
are the main future merge risks. Tests exercise actual GTK history and files,
not only mocks of these interfaces.

## M8 reliability divergences

`pydia-diagram.c` releases the GObject reference acquired by its wrapper constructor;
`diamodule.c` balances temporary diagram/sheet wrappers after list append. Native
object-ID count is exposed for main-context diagnostics. `pydia-live.c` certifies
preflight rejection versus completed rollback with distinct Python exception types.
No object ABI layout or serialized file schema changed. See [M8 evidence](m8-reliability.md)
and the [internal upstream candidate](upstream-pydia-lifetime.md).
