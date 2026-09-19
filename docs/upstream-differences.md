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

No new public C automation ABI, live socket, history wrapper or arbitrary code
execution hook exists. Runtime discovery in this increment reuses upstream
`dia.registered_types` and `dia.registered_sheets`; it changes no native files.
Native model, object catalog, standard sheets/shapes, rendering and GUI remain
upstream-shaped. Keep those working components untouched during this increment.

## MCP-specific additions

| Files | Role / divergence |
| --- | --- |
| `mcp/src/dia_mcp/models.py`, `service.py`, `errors.py` | Typed session snapshots, transactions, UUIDs, bounded creation contract, structured failures and workspace publication. Experimental API v1, not Dia's native ABI. |
| `mcp/src/dia_mcp/backend.py` | Restartable native CLI worker per render or discovery, dedicated Python startup, timeout and artifact/report validation. |
| `mcp/src/dia_mcp/native/{bridge,catalog,python-startup}.py` | Embedded stdlib-only importer, narrow factories, UML tuple adaptation, technical-symbol geometry and native attachments. Main area for adapting future PyDia changes. |
| `mcp/src/dia_mcp/{discovery.py,native/discovery.py}` (this increment) | Bounded metadata contract and generic factory/sheet enumeration. No duplicated native object catalog or factories instantiated by listing. |
| `mcp/src/dia_mcp/server.py` | FastMCP stdio adapter, tool schemas and annotations. Two read-only discovery tools added to the original nine. |
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
