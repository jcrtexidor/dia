# M9 tool review — proposal only

Reviewed 2026-09-21 during the M8 certificate rebuild. This document authorizes
no implementation or relaxation of the M8/Wayland gate. Preserve all existing
tools, snapshot behavior, runtime identities, native history, receipts and file
policy. Semantic modules remain optional consumers of the generic model.

## Inventory method and shared contract

The actual FastMCP `list_tools()` output from `build_server` advertises **32
tools**. A local schema-only instantiation (no backend calls or GUI access)
reported **13,749 bytes** of compact JSON input schemas, summed per tool using
`json.dumps(inputSchema, separators=(",", ":")).encode()`. Descriptions and MCP
envelopes are excluded; this is neither token count nor network latency. All 32
currently have `outputSchema=None`, despite returning dictionaries. A caller
learns output structure and error recovery from descriptions, documentation and
results rather than advertised typed output contracts.

Sources: `mcp/src/dia_mcp/server.py`, `service.py`, `discovery.py`, `recipes.py`,
`live/{client,protocol,registry,operations,files}.py`, and `errors.py`.

Inventory notation:

- **D**: live document ID obtained from `live_get_active_document` or
  `live_list_documents`; these summaries already carry generation.
- **O**: live object IDs obtained from selection/object lists or creation results.
- **G**: recently observed document generation; live selection/object/connection
  reads also return it, so a separate `live_get_document` is not always required.
- **R**: receipt from `live_prepare_operation`; required for each new mutation.
- **S**: snapshot document/object IDs, separate from D/O and GUI state.
- **P**: offset pagination, default/max 100; follow `next_offset` and check totals.
- **W**: fresh worker inventory, not the current GUI's installed factories.
- **F**: live file root configured; path and explicit overwrite policy apply.

The common live budgets currently advertise 16,384 request bytes, 1,048,576
response bytes, 100-item pages, 32 property descriptors per object, 256 structural
items per object and 10,000 traversed objects (including group members; depth
bounded at 32). A broad object list may traverse the whole document even when
returning one page. Native analysis is capped at 256 objects. Property text is
bounded at 2,048 characters; flags and descriptor truncation remain evidence.
These are defaults, not universal promises: read the running GUI handshake.

All live operations can fail before domain work for backend availability,
protocol/capability mismatch, queue/deadline or size limits. Runtime IDs can become
stale after detach, rollback, close or session replacement. Mutations additionally
require writability, G/R validation and native acceptance. Errors are currently
JSON serialized inside MCP `ToolError`, with `code`, `message` and optional
`outcome`/`details`; clients must preserve those fields. Do not replace an
uncertain mutation with a new receipt. Query its existing receipt first; an
expired/unknown receipt is not permission to replay.

## All 32 tools

Each row records naming/discoverability, preparation, size behavior and the main
additional error/interpretation concern. “Schema B” is that tool's input-schema
size under the method above, not its response size.

| # | Tool | Discoverability and preparation | Size / schema B | Error or interpretation concern |
| ---: | --- | --- | --- | --- |
| 1 | `get_capabilities` | Easy entry point, but primarily snapshot capabilities; no prerequisite. | Returns full object/connection schemas; 69 B. | `generic_creation=false` is snapshot-scoped; do not mistake it for disabled generic live creation. |
| 2 | `list_sheets` | W, optional P; name lacks worker/live scope. | Up to 100 sheet summaries; 215 B. | Worker/plugin availability and snapshot installation may differ from GUI. |
| 3 | `list_object_types` | W; exact sheet name from #2 if filtering, otherwise P only. | Up to 100 entries plus sheet labels; 306 B. | `creatable_as=null` denies snapshot creation only. Registered type is not necessarily a usable ordinary factory (`Group`). |
| 4 | `live_handshake` | Explicit live entry; no ID. | Small capabilities/limits/receipt contract; 67 B. | Reports current write/file capabilities; success does not grant them. Each other live call already negotiates internally. |
| 5 | `live_list_documents` | No ID; P. | Up to 100 document summaries; 223 B. | Only GUI documents with displays; snapshot IDs cannot be used here. |
| 6 | `live_get_active_document` | Clear current-GUI lookup; no ID. | One document or null; 77 B. | Null is valid, not a transport failure; active document can change before the next call. |
| 7 | `live_get_document` | D. | One summary/G; 150 B. | Stale document/session; G is conservative observed invalidation, not a complete edit log. |
| 8 | `live_list_layers` | D, P. | Up to 100 layers; 301 B. | Active/visible flags do not mean all contained objects are selected or editable. |
| 9 | `live_get_selection` | D, P; central user-intent entry but separate from active lookup. | Up to 100 basic object summaries; 303 B. | Does not include detailed safe properties or attachments; selection can change between pages. |
| 10 | `live_list_objects` | D, P. | Up to 100 summaries; underlying traversal up to 10,000; 302 B. | Includes nested group members. Listed members are not automatically valid top-level mutation targets. |
| 11 | `live_get_object` | D/O; `properties=false` default. | One detailed object, bounded relations/sheets and optionally 32 descriptors; 279 B. | Unsupported/read-only properties are explicit. Truncated descriptors are not a full schema. |
| 12 | `live_get_connections` | D/O. | Per-object handles/points/fanout bounded at 256; 215 B. | Returns real attachments, not touching shapes; either structure or fanout may exceed budget. |
| 13 | `live_plan_objects` | Domain and node list; no live ID or GUI required. | 1..64 create commands; 238 B. | Inert recipe, limited verified domains/types. `nodes:list[dict]` leaves nested schema in prose; availability is not runtime-validated. |
| 14 | `live_prepare_operation` | Write capability; no D/G. | One receipt; 75 B. | Changes receipt state only; capacity/expiry apply. Reserving does not guarantee later execution. |
| 15 | `live_get_operation` | Existing R. | Receipt and possibly stored bounded result; 148 B. | States distinguish prepared/queued/executing/committed/rolled_back/failed/uncertain; expired or evicted IDs must not trigger blind replay. |
| 16 | `live_apply_commands` | D/G/R, O for existing references; layer/endpoint/property reads as needed. | 1..64 commands, up to 32 scalar properties each, request-byte cap dominates; 422 B. | `commands:list[dict]` has no advertised operation union. IDs must preexist the batch; native validation/rollback may invalidate O. |
| 17 | `live_history` | D/G/R, direction. | Small result; 365 B. | Direction is advertised as plain string, validated as undo/redo later. Shared GUI history can contain user edits. |
| 18 | `live_open_document` | R/F and trusted local `.dia` path; no G. | Small new-document result; 195 B. | File/native importer failures; imported files can reference resources. Not a generic create-empty-live-document tool. |
| 19 | `live_save_document` | D/G/R/F and current filename. | Small publication result; 376 B. | Existing destination requires `overwrite=true`; file publication outcome must be distinguished from editor outcome. |
| 20 | `live_save_document_as` | D/G/R/F plus path. | Small publication result; 426 B. | Native serialization, target validation and publication can fail; GUI name changes only after publication. |
| 21 | `live_export_document` | D/G/R/F plus path; default SVG. | Result metadata, not inline artifact; 485 B. | Format is schema-level string, runtime dia/svg/png. Explicit overwrite; preserve dirty state; inspect outcome after failures. |
| 22 | `live_get_dependencies` | D. | Bounded declared file-property report; 154 B. | Completeness and existence are not guaranteed; not a security scan or all-resource dependency proof. |
| 23 | `live_summarize_document` | D. | Counts/type histogram and document summary; 156 B. | Compact relative to object details, but histogram grows with distinct types; no local neighborhood or selected-property detail. |
| 24 | `live_analyze_document` | D; optional domain defaults auto. | At most 256 objects; topology/evidence may approach response budget; 215 B. | Full-document limit prevents local questions on larger diagrams. Domain is plain string; evidence/limitations must accompany conclusions. |
| 25 | `create_document` | Snapshot entry; no S. | Empty snapshot envelope; 127 B. | Name can be mistaken for GUI creation; max 32 snapshot documents. |
| 26 | `create_object` | Snapshot document S; typed shape enum, cm geometry. | Returns full snapshot/geometry; 3,039 B. | Allowlisted types, max 100 nodes. Native render failure prevents commit; caller pays for full snapshot response on each edit. |
| 27 | `connect_objects` | Snapshot document/source/target S; optional port/index choice. | Full snapshot/geometry; 1,055 B. | Max 200 edges; explicit index requires port=auto. UML source is superclass, target subclass; no generic live counterpart implied. |
| 28 | `update_object` | Snapshot document/object S; optional fields. | Full snapshot/geometry; 2,828 B. | UML properties replace the whole set; omitted/null differs from `{}` reset. Native rebuild before commit. |
| 29 | `move_object` | Snapshot document/object S plus x/y. | Full snapshot/geometry; 282 B. | Does not move a GUI object; attached geometry rebuilt in worker. |
| 30 | `inspect_document` | Snapshot document S. | Entire logical document and geometry, no pagination; 149 B. | Bound by 100 nodes/200 edges, not live pagination; missing snapshot ID is distinct from stale GUI ID. |
| 31 | `export_diagram` | Snapshot document S and filename. | Path/bytes/hash; 360 B. | Basename only; workspace policy and explicit overwrite. Not live export and not arbitrary paths. |
| 32 | `close_document` | Snapshot document S. | Small closed-ID response; 147 B. | Discards server session state; does not close the user's GUI document. Export first if persistence is needed. |

The two existing resources (`dia://live/documents` and
`dia://live/documents/{document_id}/summary`) and `explain_live_diagram` prompt
are not included in the 32-tool count. They help discovery but do not replace
selection detail or neighborhood reads. Current top-level server instructions
lead with the snapshot create/connect/export workflow; a future compact live
entry should make the live/snapshot choice explicit without renaming old tools.

## Five compact additions to consider after the gate

Names below are proposals, not currently registered tools. Each retains the
same live capability checks, native model, generic mutations and error outcomes.
An aggregate read should execute in one main-context dispatch if it promises a
single observation; wrapping several existing requests does not make them
atomic. If composition uses multiple observations instead, expose start/end G
and inconsistency rather than silently claiming a coherent snapshot.

| Proposed addition | Small input contract | Reviewable output and boundary |
| --- | --- | --- |
| `live_current_context` | Optional document ID; default actual active document. Bounded selection/layer summary options. | Session, selected/active document or null, G, counts, active layer, compact selection, limits/capabilities relevant to next steps. No properties or whole-document geometry by default. Empty GUI returns explicit no-document context. |
| `live_inspect_selection` | Optional D; bounded offset/limit, optional safe properties and connections. | Selected object details gathered at one observation, per-object property-policy flags, attachment evidence, G and explicit omitted/truncated totals. Reuses descriptor policy; unsupported codecs stay closed. It must not silently broaden selection to an entire group or layer. |
| `live_neighborhood` | D, bounded seed object IDs, depth (small explicit maximum), object/edge budget; optional safe properties. | Local native incidence graph, included IDs and attachment/connection-point provenance, boundary references, unknown/missing references and truncation. Depth counts native object attachments, including connector objects; it must not implicitly collapse connectors or infer visually touching nodes. Omitted fanout is not disconnection. |
| `live_plan_selection` | Optional D; explicit generic operation such as move delta, native layout mode or named scalar-property update; bounded selected IDs. | Inert exact generic commands, captured IDs/G, before/after parameter explanation, descriptor/top-level-target checks and pending native checks. No receipt reservation or application. A move delta is resolved against observed positions; selection/geometry changes require replanning. No mandatory domain inference or universal `label` guess. |
| `live_static_validate` | D/G and bounded generic command list (or the plan's exact list). | Structured checks/errors indexed by command and field; distinguishes syntactic validity, observed reference/descriptor checks and unperformed native/runtime checks. Checks operation union, budget, finite values, IDs/session/document, top-level target eligibility, known endpoints and scalar policy where available. It neither writes, reserves R, runs setters, opens files nor promises a future commit. |

Start aggregate reads with a small default (for example 16 objects), explicit
maximum (no larger than 64 for selection plans), and aggregate byte/property/
attachment budgets below the existing transport cap. Those are proposed product
budgets, not measured safe thresholds. Do not multiply 64 objects × 32 properties
× 2,048 characters and assume it fits a 1 MiB response. Return truthful omissions
and continuation information tied to G, or a structured budget error. A bounded
neighborhood must traverse only what it needs rather than requiring whole-
document semantic analysis to succeed first.

For static validation, absence of exported enum values/ranges or runtime factory
create support must produce “requires native validation,” not success-by-guess.
Snapshot `creatable_as` must not become a live allowlist. Preserve all generic
command capabilities; convenience plans may deliberately support fewer operations
without replacing the original API. File/native-plugin side effects remain
outside static validation's guarantees.

## Analytical workflow call counts

These are **MCP tool invocations**, derived from current contracts, not timings
or benchmarks. Assume a stable document, all responses fit the chosen budgets,
all requested objects fit one selection page, valid IDs/permissions, and no
retries. Do not add a separate G lookup when an already required live read returns
G. Explicit `live_handshake` is optional for the counts below: the client performs
capability negotiation automatically. Add one user-visible call if independently
asking to inspect the handshake.

| Workflow and assumptions | Existing calls | Proposed calls and conditions |
| --- | --- | --- |
| Current diagram counts, first selected summaries and first layer page; no D initially. | `get_active_document` + `summarize_document` + `get_selection` + `list_layers` = **4**. | `current_context` = **1**, only if requested summaries fit its stated budget. |
| Detailed selected objects with properties and native attachments; N selected, no D initially. | Active lookup + selection + N×`get_object(properties=true)` + N×`get_connections` = **2 + 2N**. For N=3: **8**. | `inspect_selection(properties=true,connections=true)` = **1** when N fits aggregate budgets; no claim for larger/truncated selections. |
| Move N selected top-level objects by one delta, or native layout of the selected IDs; no D initially, N≤64. | Active lookup + selection (positions/G) + prepare + apply = **4**. Agent computes commands locally. | `plan_selection` + prepare + unchanged generic apply = **3**. Add static validation if desired: **4**. Both retain a separate reviewed application step. |
| Inspect one-hop native incidence from a known seed in known D; K distinct neighbor objects; want seed/neighbor summaries and only the seed's full attachments. | Seed `get_object` + seed `get_connections` + K neighbor `get_object` = **K + 2**. For K=4: **6**. | `neighborhood(depth=1)` = **1**, with the same evidence and boundary semantics within budget. It is not a full graph or all-neighbor-property read unless requested. |
| Preview/validate a prepared generic command list without mutating. | **No equivalent validation tool**. Local syntax inspection is not a native test; prepare+apply cannot be counted as a read-only substitute. | `static_validate` = **1**; residual native checks remain explicit. |
| Resolve a lost mutation response when R is known. | `get_operation` = **1**. | **1**, unchanged; convenience tools must preserve this recovery path. |
| Enumerate 887 installed registered types unfiltered at 100/page. | `list_object_types` = **9** pages; each asks a fresh worker inventory. | **9**, unchanged by these five additions. This is worker metadata, not live factory verification. |

For N selected objects spanning P pages, the detailed-selection baseline is
**1 + P + 2N**, where P = max(1, ceil(N/100)) if checking even an empty selection.
For empty selection N=0 it is two calls. Changes between pages invalidate an
assumption of coherent selection; counts alone cannot establish consistency.
The proposed inspection must expose continuation/G before claiming a reduction
for inputs above its budget; no exact large-selection savings are asserted here.

There is a second, distinct count at the Unix-socket boundary: current
`LiveClient.request` opens a connection and performs a handshake plus action for
every ordinary live request. Therefore M ordinary live MCP calls entail **2M
request/response exchanges**; an explicit handshake call entails **one**.
`live_plan_objects` is local and performs zero live exchanges. Proposed aggregate
reads would achieve two live exchanges per one tool call only if implemented as
one negotiated native action; a Python wrapper issuing M old calls would still
perform 2M exchanges. None of these counts estimates latency, CPU cost or GUI
responsiveness.

## Acceptance targets for the later implementation

Keep old tool schemas/semantics compatible. Exercise no active document, empty
selection, mixed/custom types, zero-port objects, groups and non-top-level
members, stale selection/G, unsupported properties, partial neighborhoods and
byte-budget overflow. Verify each plan is inert, uses native command semantics
and preserves the existing receipt/application boundary. Static validation must
report unknown native checks honestly and never fetch unsupported property
values. Compare actual round trips/output sizes under stated fixtures separately
from this analytical review, and retain M8 lifetime/resource regressions.

## Implementation follow-up after the M8 gate

The inventory and analytical counts above preserve the **32-tool review
baseline**, not the current tool count. After the M8 gate and commit `5d0898ef5`,
the in-progress M9 server advertises **37 tools**, verified through FastMCP
`list_tools()`. The implemented names are `live_get_current_context`, `live_inspect_selection`,
`live_inspect_object_neighborhood`, `live_plan_selection`, and
`live_validate_commands`. This does not turn analytical call counts into
performance measurements. Unlike the optional-document proposal above, current
selection inspection and planning require D: from a cold start add a context
lookup. Current context already includes detailed selection, safe properties and native
connections for its first 8 objects. Consequently cold selected detail is **1 MCP
call** within that first page; subsequent selection pages use
`live_inspect_selection` with D. Plan + prepare + apply is **4 from a cold start /
3 with known D**. These are still contract-derived counts, not measured
latencies. Neighborhood and validation also require explicit D.

The pure `live/planning.py:plan_selection` helper now emits reviewable move,
native-layout and bulk named-scalar-property commands. It uses the actual
`position={x,y}` live summary contract, rejects selected group members as generic
top-level targets, and can apply the property policy to raw descriptors without
fetching values. Missing/truncated descriptor evidence remains a pending native
check. Plans report explicit targets, creation count, assumptions, unsupported
semantics and expected structural effects; they reserve no receipt and apply no
commands. Creation recipes now carry the same metadata.

Semantic analysis preserves earlier fields and adds separately labeled native
layer/group facts, attachment-derived structure and heuristic hints. Bounding-box
intersection and unattached connectable handles are each capped at 64 returned
items with total/truncation evidence. Overlap does not create graph edges;
unattached handles do not imply a two-ended connector or a missing connection.
Counts apply only to the supplied graph, including partial group membership.

Focused portable checks for planning, recipes and semantics: **57 passed**;
Ruff checks passed. Full M9 native/tool integration and measured workflow
evidence belong to the coordinating validation report rather than this baseline
review.
