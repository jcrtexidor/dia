# M3–M7: native editing, files and context

Implementation date: 2026-09-19. Continues the completed M2 baseline `7093ae39a`.
The scope is the staged roadmap in [architecture](mcp-architecture.md). Existing
snapshot schemas, dependency locks, GTK3 and worker startup remain intact.

## Delivered phases

| Phase | Implementation | Acceptance evidence |
| --- | --- | --- |
| M3 | Synchronous native change staging, one native transaction point per successful batch; rollback preserves prior undo/redo; same GTK thread and current document generation required | Real GUI menu and MCP history undo/redo; partial move/property and create failures preserve state and redo; competing clients at one generation produce one commit |
| M4 | Installed native factories, descriptor-first safe scalar/text properties, move/delete/connect/disconnect; 1–64 commands; layer-aware creation | UML, flowchart, ER, database, network, circuit, unfamiliar custom and zero-port shapes; attached geometry follows property edits and undo |
| M5 | Native open, Save, Save As, Dia/SVG/PNG export; explicit overwrite, bounded local-root paths, atomic publication and dependency report | Native round trip of custom types, groups, layers and connections; exports preserve dirty state; failed publication preserves original bytes and GUI filename |
| M6 | UML codec/validation extracted into `native/uml.py`; topology analysis with evidence; flowchart/UML/database/network recipes produce ordinary generic commands | Snapshot regressions, recipe tests, mixed/native topology tests; no speculative ports or simulation |
| M7 | Eight existing native align/distribute modes; document summaries, analysis, MCP resources/prompt, operation correlation and timing | Reversible layout geometry, actual MCP stdio reads/writes/resources/prompt, bounded performance sample and compositor tests |

## Enable and operate

Read access still requires `DIA_MCP_LIVE=1` in the normal GUI environment. Write
access additionally requires `DIA_MCP_WRITE=1`. Native files additionally require
`DIA_MCP_FILES_ROOT=/absolute/trusted/directory`; this is configured locally, never
accepted from remote requests. Start the external adapter with `--live-socket`.
The external MCP SDK is not imported into Dia's embedded interpreter.

Use `live_get_document` to obtain the current conservative `generation`, then
`live_prepare_operation` to reserve a `request_id`. Supply both to
`live_apply_commands`, `live_history` or document writes. Open needs a receipt but
has no existing document precondition. GUI updates and requests are serialized on
the GTK main context; a mismatched generation rejects the entire transaction.
Generation counts observed invalidations, not exact edits, so harmless redraws
can also require a fresh read. Trusted plugins that bypass editor notifications
are outside this concurrency guarantee.

Example `commands` for one transaction:

```json
[
  {"op":"create","type":"Database - Table","x":2,"y":3,"properties":{"name":"Orders"}},
  {"op":"create","type":"Flowchart - Box","x":12,"y":3,"properties":{"text":"Review"}}
]
```

Other commands: `move(object_id,x,y)`, `set_properties(object_id,properties)`,
`delete(object_id)`, `connect(object_id,handle,target_id,point)`,
`disconnect(object_id,handle)`, and `layout(object_ids,mode)`. Layout modes:
`left`, `center`, `right`, `top`, `middle`, `bottom`,
`distribute_horizontal`, `distribute_vertical`.

Creation returns opaque IDs. References in a batch must already exist before the
batch; inspect new handles/connection points and use the returned IDs in a later
transaction. `live_plan_objects` produces a reviewable creation plan for supported
semantic recipes without changing any document.

## Native transaction and retry semantics

`pydia-live.c` stages **real DiaChange objects** on a temporary native UndoStack
only during the synchronous call. Failure reverts those changes and discards that
stack. Success transfers them into the document's original native stack and adds
one transaction point. There is no second persistent history. An unfinished GUI
transaction rejects the command. The normal menu and MCP undo/redo share history,
including the user's own edits; clients must not assume history is MCP-exclusive.

Receipts retain only plain JSON data, never PyDia wrappers. They are bounded to
256 reservations and 30 minutes. Repeating the same request ID and input returns
the stored outcome; different input conflicts. Expired/evicted/foreign IDs never
execute. After timeout or disconnect, query `live_get_operation` or retry the
**identical** input with the same ID. Never prepare a replacement ID and blindly
repeat a mutation. An unknown/uncertain receipt requires inspecting document and
files. No automatic mutation retries are performed by the client.

An expired or disconnected queued request does not mutate. Once native execution
starts it cannot be preempted; the server records the result even when the client
has stopped waiting. A post-execution deadline does not replace a committed
mutation's receipt with a timeout. Unexpected postcommit failures remain
`uncertain` and cannot execute again. Rollback may invalidate runtime object IDs
and advance the conservative generation; reread state after failures.

## Files and preservation

Open loads a separate native document, never reconstructs the restricted snapshot
model. Save and export use installed native serializers. Save As changes filename
and native saved marker only after successful publication. `.dia` export is a
copy and keeps the original document's filename/dirty marker. Reopening a saved
file creates new document/object IDs. This provides a recovery-copy workflow;
normal Dia autosave/recovery UI remains available.

Paths are confined to the configured root and reject symlink components. Writes
pin the destination directory with a descriptor, serialize to a private file,
fsync and atomically publish; no-clobber publication uses a hard link. An existing
file requires `overwrite=true`, including Save. Open validates components but
uses the logical path for relative resources: concurrent adversarial directory
renames are outside its guarantee. Native plugins/importers may access resources
referenced by trusted diagrams; this is not a plugin sandbox.

Preservation applies to installed types and properties unknown to the MCP schema.
Missing native plugins/types are subject to Dia's own importer behavior. A
complete unknown-plugin losslessness guarantee is not claimed. Dependency reports
list declared `file` properties only, with `complete=false` and `exists=null`;
they neither open arbitrary external resources nor infer self-containment.

A native serializer close-result defect was corrected locally; see the internal
[upstream candidate note](upstream-save-close.md). No upstream issue or patch was
submitted; the checkout's upstream policy prohibits AI-generated contributions.

## Bounded scope and observability

- Safe properties: bool, int, enum, real, length, fontsize, string and text;
  descriptor flags and native ranges are checked before setting. Unsupported
  compound/array/image values are rejected. The full original native model is
  still preserved when saving.
- Group members are read recursively but are not mutation targets. Deletion
  requires an unparented object with no attached handles/points; disconnect first.
  Arbitrary installed factories are supported through their default creation data;
  sheet-specific creation variants remain unexposed.
- Discovery tools query the worker installation; inspect a live object's sheet
  entries and property descriptors for its GUI profile. A sheet is not an exclusive
  semantic domain. Analysis uses actual handle attachments, reports mixed/unknown
  domains and unsupported semantics; it does not infer PKs, flows or simulation.
- Analysis is bounded to 256 objects; page/object traversal retains M2's bounds.
  Membership resolution is O(N). Native layer wrapper tuples can be allocated
  before traversal checks; arbitrary native callbacks cannot be preempted.
- Mutation results include request ID, resulting generation and elapsed milliseconds.
  Analysis includes elapsed time. Logs do not contain request payloads or documents.
  Performance tests measure transport-inclusive page reads; no unsafe pointer cache
  or claimed constant-time lookup was added.

## Validation record

Final installed-image and compositor results are recorded here after verification.
The first complete build passed all 9 Meson suites and 165 MCP tests. Subsequent
focused native tests verified transactions, native files and MCP context surfaces.
The initial Xvfb page-read sample (256 objects, page 100, 20 requests) measured
1.247 ms median and 2.451 ms p95. These measurements describe this local test,
not a latency guarantee or a comparison with a prior optimized implementation.

Final verification:

- `task mcp:check`: Ruff lint/format clean; **147 passed**, 52 native deselected.
- `task mcp:build`: **9/9 Meson suites**, **199 MCP tests**, `pip check` clean.
- `task mcp:test`: **199 passed**, installed package, UID/GID 1000:1000,
  network disabled and Xvfb; 34.64 seconds in this run.
- Installed real Wayland GUI suite: **10 passed** in 7.10 seconds.
- Installed Wayland `GDK_SCALE=2`: M2's two tests passed first; the eight remaining
  M3–M7 tests passed in an isolated runtime directory (4.29 seconds). The initial
  combined attempt reused a previous container's PID-named stale socket and the
  fixture's existence-only readiness check raced startup. Only the pending tests
  were rerun. Give each compositor run a fresh private runtime directory.
- 51 implementation/test/build/lock files match the installed image exactly.
- Final image `dia-mcp:ubuntu26`:
  `sha256:92465cb32fd10af263110b3b146ab3c3186b82af391556550cdc501b4e03e804`.
- `git diff --check` and changed documentation's relative links pass.

Transport-inclusive page reads (256 native objects, page size 100, 20 samples):

| Environment | Median | p95 |
| --- | ---: | ---: |
| Initial focused Xvfb run | 1.247 ms | 2.451 ms |
| Final installed Wayland | 1.223 ms | 2.169 ms |
| Final installed Wayland, scale 2 | 1.097 ms | 1.220 ms |

Native test logs retain the known nonfatal `dia_text_set_cursor` assertion during
some automated GUI actions, Glycin's container sandbox warning, and missing-icon
warnings for deliberately minimal custom test shapes. No new upstream defect is
claimed from these diagnostics. Native reads, edits, history, exports, round trips
and confirmed quit assertions passed. The serializer-close finding has source
confirmation and native regression coverage, but not a fault-injected upstream
reproduction; its internal note distinguishes those levels of evidence.
