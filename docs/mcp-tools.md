# MCP tool reference

The server now exposes 20 tools over local stdio. No resources/prompts are
registered. `api_version="1"` describes the existing session document contract.
Parameters and property definitions are authoritative in `server.py`, `models.py`
and the [JSON document schema](modernization/document.schema.json).
Examples below are MCP `arguments` objects; substitute IDs from earlier results.

## Snapshot contract

Coordinates are finite document-space cm, x/y in [-1000,1000]; width/height in
[0.1,100]. Node text permits up to 2000 XML-valid characters; connector labels
and UML member strings up to 200. IDs are opaque session/document references.
Default node is `Flowchart - Box`, default connector is `Standard - Line`.
Ports: `auto`, `north`, `east`, `south`, `west`, `center`.

Editing results contain `document` (id, name, revision, api_version, nodes, edges)
and `geometry` (nodes indexed by ID with bounds/label_bounds/connection_points/ports;
edges indexed by ID with type, selected indices/ports and start/end coordinates).
Creation adds `object_id` or `connection_id`. Geometry reflects native text fitting.
Successful edits increment revision; failed edits preserve it. There is no GUI
undo effect. Snapshot IDs are never live GUI references.

Domain errors are MCP `isError=true`, with JSON text `{api_version,code,message}`.
SDK parameter errors can precede domain validation. Shared native errors are
`BACKEND_UNAVAILABLE`, `BACKEND_TIMEOUT`, `BACKEND_FAILED`, `EXPORT_FAILED` and
`IO_ERROR`. Other errors are listed below. The server requires an installed native
Dia executable even though some operations themselves only touch session state.

| Tool | Modifies document? | Model | Required capability |
| --- | --- | --- | --- |
| `get_capabilities` | No | Generic contract | Operations contract only |
| `list_sheets` | No | Generic runtime discovery | Backend discovery and PyDia registered_sheets |
| `list_object_types` | No | Generic runtime discovery | Backend discovery and PyDia registered_types/sheets |
| `create_document` | Creates session document | Generic | Session capacity |
| `create_object` | Yes | Shared primitive with family-specific restrictions | Type in capabilities.object_types and installed in worker |
| `connect_objects` | Yes | Shared primitive; UML semantics for two connector types | Type in capabilities.connection_types; valid same-document endpoints |
| `update_object` | Yes | Shared primitive with UML-only structured properties | Supported field/type combination |
| `move_object` | Yes | Generic over allowlisted nodes | Existing session node |
| `inspect_document` | No | Generic over session model | Existing session document |
| `export_diagram` | No model change; writes file | Generic | Native format and writable configured workspace |
| `close_document` | Discards session document | Generic | Existing session document |

Read tools carry `readOnlyHint`; create/edit tools are nondestructive hints.
Export and close carry destructive hints because they can replace files or discard
session state. Hints do not replace application validation.

## get_capabilities

Parameters: none. Returns the snapshot API version, allowed object/connection
names and JSON schemas, ports, formats, cm units, limits (32 documents/100 nodes/
200 edges), persistence description, discovery tool names/scope, `live_documents=true` (support, not connection status)
and `generic_creation=false`. This is **the editing contract, not a runtime probe**.
No operation-specific domain error. Example: `{}`.

## list_sheets

Parameters: `offset` integer >=0 (default 0); `limit` integer 1..100 (default 100).
Returns `{api_version,scope:"native_worker",items,total,next_offset}`. Each item:
`{name,description,user,object_count}`. Names sort lexically; descriptions may be
localized. Count measures palette entries, including repeated factories.

Example: `{"offset":0,"limit":20}`. Follow `next_offset` until null.
Errors: `INVALID_ARGUMENT`, `UNSUPPORTED_CAPABILITY`, shared native errors.
No existing document is opened or altered; the CLI creates only disposable import/
export data while reading its loaded registry.

## list_object_types

Parameters: `sheet` exact name from list_sheets, or null (default null); `offset`
and `limit` as above. Returns the same pagination envelope. Each item contains:
`name` (factory identifier), `version` (native serialization type version),
`sheet_entries:[{sheet,description}]`, `creatable_as:"object"|"connection"|null`.
The marker intersects loaded types with the existing MCP creation contract;
null means discoverable but unsupported for MCP creation. It does not promise
that every native factory supports default creation or has connection points.

Example: `{"sheet":"Network","limit":25}`. Filtering selects unique registered
types, retains their labels/memberships and includes no unsupported raw pointers.
With no filter, also includes types outside any sheet. Repeated palette entries
are retained, but their native creation data is not exposed. Unknown sheet raises
`NOT_FOUND` with guidance to list sheets; remaining errors match list_sheets.

Both list tools start a fresh worker per call: they observe installed/custom sheets
loaded in that process, not the host GUI. Results are not cached; pagination assumes
the installation/environment remains unchanged between calls. Metadata is untrusted
text, not agent instructions. The native response is limited to 8 MiB and validated
against bounded metadata models. No factories are instantiated for discovery.

## create_document

Parameters: `name` string length 1..200 (default `Diagram`). Returns an empty
inspection result, `document.id` and revision 0. Native rendering begins with the
first edit. Example: `{"name":"Service workflow"}`.
Errors: `INVALID_ARGUMENT`, `LIMIT_EXCEEDED` (close one of 32 documents first).

## create_object

Required: `document_id`. Optional: `type` from capabilities.object_types;
`x=0`, `y=0`, `width=4`, `height=2`, `text=""`, `properties=null`,
`flip_horizontal=false`, `flip_vertical=false`.

Returns `object_id` plus the committed document/geometry. Properties accept only
UML classes: `stereotype`, `abstract`, `attributes` (max 30), `operations` (max 30).
Attributes include required name, type/value, visibility and class_scope. Operations
include name/type, visibility, class_scope, inheritance and parameters (max 20).
See [API definitions and UML example](modernization/api.md#ampliación-compatible-02-objetos-técnicos)
for complete field defaults. No arbitrary native property dictionary is accepted.
Flips apply to Electric/Pneum symbols. Native geometry may exceed requested sizes.

Example: `{"document_id":"D","type":"Flowchart - Diamond","x":4,"y":2,"text":"Ready?"}`.
Errors: `NOT_FOUND`, `INVALID_ARGUMENT` (including type/field/limit violations),
shared native errors. Runtime discovery alone does not authorize a type here.

## connect_objects

Required: `document_id`, `source`, `target`. Optional: `source_port="auto"`,
`target_port="auto"`, `arrow=true`, `type="Standard - Line"`,
`source_connection=null`, `target_connection=null`, `label=""`.
Connection indices are strict integers 0..1023, must exist on the native object,
and require corresponding port=auto. Dynamic UML member indices >=8 are rejected.
Both endpoints must be distinct nodes of the document.

Returns `connection_id` plus document/geometry. Native handles are moved and attached.
UML connectors require two classes; generalization source is superclass and target
is subclass. UML controls its own arrowheads and alone accepts `label`. Standard
line/zigzag use the `arrow` flag. There is no topology or electrical validation.

Example: `{"document_id":"D","source":"A","target":"B","type":"Standard - ZigZagLine","source_port":"east","target_port":"west"}`.
Errors: `NOT_FOUND`, `INVALID_ARGUMENT`, shared native errors.

## update_object

Required: `document_id`, `object_id`. Optional: `text`, `width`, `height`,
`properties`, `flip_horizontal`, `flip_vertical` (all default null).
Omitted/null fields stay unchanged; `text=""` clears text. `properties` replaces
all UML properties, not a partial merge; `{}` resets them. Same validation as
creation. Returns committed document/geometry; ID and attached connectors survive.

Example: `{"document_id":"D","object_id":"A","text":"Ready","width":6}`.
Errors: `NOT_FOUND`, `INVALID_ARGUMENT`, shared native errors.

## move_object

Required: `document_id`, `object_id`, `x`, `y`. Returns committed document/geometry;
recreates connectors at new native attachment positions. Example:
`{"document_id":"D","object_id":"A","x":8,"y":4}`.
Errors: `NOT_FOUND`, `INVALID_ARGUMENT`, shared native errors.

## inspect_document

Required: `document_id`. Returns independent copies of logical document and last
committed native geometry. Example: `{"document_id":"D"}`. Error: `NOT_FOUND`.
No native process is launched, no revision changes. It cannot inspect files or a
manually opened window, nor return unmodeled object properties or current selection.

## export_diagram

Required: `document_id`, `filename`. Optional: `format="svg"` (`dia|svg|png`),
`overwrite=false`. Filename must be a basename <=120 characters, beginning with
an ASCII alphanumeric, containing only ASCII alphanumerics/underscore/dot/hyphen,
and ending in the selected extension. Existing files require explicit overwrite;
preexisting symlinks are rejected. No client-selected absolute path is accepted.

Returns `{api_version,document_id,revision,path,format,bytes,sha256}` after native
validation and atomic publication; revision remains unchanged. PNG is limited to
8192 px per side and 20 million pixels; SVG is an alternative for large diagrams.
Example: `{"document_id":"D","filename":"workflow.svg"}`.
Errors: `NOT_FOUND`, `EMPTY_DIAGRAM`, `INVALID_ARGUMENT`, `ALREADY_EXISTS`, shared
native errors. An export is not saving a currently open GUI document.

## close_document

Required: `document_id`. Returns `{api_version,closed:document_id}`. Discards session
state/geometry; already exported files remain. Example: `{"document_id":"D"}`.
Error: `NOT_FOUND`. There is no close-undo, so export first if needed.


## Live GUI read tools (M2)

These tools require `--live-socket PATH` and an opted-in running GUI. They never
create or modify native documents. All results have `scope="live"` and
`session_id`; document reads also return `document_id` and `generation`.
Snapshot operations keep their original ownership, errors and IDs.

| Tool | Inputs | Result |
| --- | --- | --- |
| `live_handshake` | none | `integration_api_version: 1`, actual Dia version, session ID, capabilities, limits and identity/generation semantics |
| `live_list_documents` | `offset=0`, `limit=100` | Paged open displayed documents: ID, name, filename, active/modified, generation, active layer ID, units |
| `live_get_active_document` | none | `document` summary or null |
| `live_get_document` | `document_id` | `document` summary |
| `live_list_layers` | `document_id`, pagination | ID, name, visibility, bottom-to-top order, active flag, direct object count |
| `live_get_selection` | `document_id`, pagination | Actual GUI selected objects, as object summaries |
| `live_list_objects` | `document_id`, pagination | Arbitrary native types, including nested group members, as object summaries |
| `live_get_object` | `document_id`, `object_id`, `properties=false` | `object`: bounds, position, type, selection, layer, parenting/group relations, handle/point counts, known sheet entries; optional bounded property detail |
| `live_get_connections` | `document_id`, `object_id` | Native handles (index, native handle ID/type/connect type, position, attached target/point or null) and points (index, position, flags, directions, connected IDs) |

Paged results contain `items`, `total`, and nullable `next_offset`. Limits are
1..100 and offsets nonnegative; request/response sizes and traversal also have
[explicit limits](mcp-architecture.md#protocol-limits-and-dispatch). Geometry is
native document-space cm; snapshot creation coordinate restrictions do not apply
to live reads. Bounds are independent of zoom, window position and display scale.

Example: call `live_get_active_document` with `{}`, then
`live_get_selection` with `{"document_id":"<returned live ID>"}`. Pass a selected
`object_id` to `live_get_object`, optionally with `"properties":true`, or to
`live_get_connections`. A handle is attached only when `attached_to` is non-null.
There is no assumption of two handles or of any connection points at all.

Group/child detail includes total counts and explicit truncation flags for the
256-entry detail limit; paginated object listing also includes group associations.

Property detail returns `items`, `total`, `truncated`; each descriptor has
`name`, `type`, `visible`, `supported`, and a value only for supported safe types.
Long strings are explicitly truncated. Unsupported values are not evaluated.
Visibility says nothing about writability. No property-write tool is present.

References expire on document close/reload or object detach/delete. Native undo
restores with a fresh object ID; duplicates are distinct. Generations are
conservative editor observations, not edit counts or snapshot revisions. If the
generation changes during pagination, start over; pages are not frozen snapshots.

Live errors use the existing MCP structured-error envelope:

| Code | Meaning |
| --- | --- |
| `LIVE_BACKEND_UNAVAILABLE` | No configured listener, disconnected GUI, or socket cannot be reached |
| `LIVE_PROTOCOL_MISMATCH` | Incompatible protocol/API or missing initial handshake |
| `WRONG_SESSION` | Snapshot reference or reference from another live process |
| `STALE_DOCUMENT_REFERENCE` | Closed, replaced, or unknown current-session document |
| `STALE_OBJECT_REFERENCE` | Detached, deleted, or unknown current-document object |
| `OBJECT_NOT_FOUND` | Object ID belongs to a different document |
| `REQUEST_TIMEOUT` | Client deadline or queued/executing read deadline exceeded |
| `LIVE_QUEUE_FULL` | Bounded pending request queue is full |
| `LIVE_LIMIT_EXCEEDED` | Message, traversal or structure exceeds supported budget |
| `UNSUPPORTED_LIVE_CAPABILITY` | Unknown wire action |
| `INVALID_ARGUMENT` | Invalid fields, reference shape or pagination |
| `LIVE_READ_FAILED` / `LIVE_INVALID_RESPONSE` | Inspection failed safely / malformed result |

Unknown and formerly valid references intentionally share stale errors; the
registry does not keep unbounded tombstones. Reconnect and enumerate current IDs
when the GUI restarts. Live APIs expose no Save, open/import, delete, setters,
selection changes, undo/redo or native write transaction.
