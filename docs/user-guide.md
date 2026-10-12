# Using Dia with an MCP agent

Dia remains the editor. Open diagrams, choose layers, select objects and use GUI
Undo normally. The live backend inspects that window; snapshot tools create their
own isolated documents. Begin with [installation](installation.md) and read-only
mode. Selection identifies the subject of a request; it does not authorize changes.

## Inspect and explain

Ask the agent to call `live_get_current_context`. The result includes the active
document, generation, layer and up to eight detailed selected objects. No active
document returns null. Select objects in Dia and ask “Explain these.” Follow
`live_inspect_selection` pages only as needed and compare generations across pages.
For a suspicious connector, `live_inspect_object_neighborhood` shows actual
handles, points and attached neighbors. Visual touching is not a native connection.

`live_summarize_document` describes counts. `live_analyze_document` adds components,
isolated objects and explicitly labeled evidence/heuristics for bounded diagrams.
Overlaps or unattached handles can be intentional. Mixed and unfamiliar objects
remain usable generically; analysis does not certify electrical, network or other
engineering behavior.

## Review and apply an edit

Enable read/write locally in Settings and restart Dia first. For “Align these,”
select the objects, then have the agent:

1. Get current context and prepare a selection plan, e.g. `live_plan_selection`
   with `intent="layout"`, `options={"mode":"left"}`.
2. Review commands, affected IDs, assumptions and unsupported semantics. Optionally
   call `live_validate_commands` with the plan's document/generation/commands.
3. Reserve `live_prepare_operation`; retain its request ID for recovery.
4. Call `live_apply_commands` with that receipt and the **reviewed generation**.
5. Inspect the result. GUI Undo or `live_history(direction="undo")` reverses the
   transaction through the same native history.

A stale generation means something changed, including human interaction. Reinspect
and review again; do not silently replace the generation on the old plan. Static
validation does not execute changes. `valid=true` with deferred checks does not
promise that a plugin setter or factory will succeed.

For relative movement use `intent="move"`, `options={"dx":2,"dy":0}` in cm.
For bulk editing use `intent="set_properties"` and an explicit scalar properties
map. Inspect descriptors first: colors, fonts, arrays, fields, UML members and
other compound properties are not generic setters.

## Create and connect

Create/open a GUI document normally, then use its live ID. Discover installed
factories with the runtime catalog; worker discovery and the GUI can differ when
their profiles differ. A generic create command is:

```json
{"op":"create","type":"Flowchart - Box","x":2,"y":3,"properties":{"text":"Review"}}
```

Creation recipes in `live_plan_objects` can plan multiple flowchart/UML/database/
network symbols before applying. Runtime availability is still authoritative.
After creation, read returned IDs and inspect native handles/connection points.
Create connector objects, then connect with inspected `handle`, `target_id` and
`point` indices in a subsequent transaction. Do not assume every connector has two
handles. Newly created objects cannot be referenced by invented IDs in the same
batch. Disconnect attached handles before deleting connected objects.

To edit an existing object, use its observed ID, safe descriptors and generation;
move and set_properties commands stay within native transactions. Group-member
editing and moving selection to another layer are not implemented by the generic
command ABI. Tell the user that instead of approximating those operations.

## Save, reopen and export

Choose an existing allowed root in Settings before restarting read/write mode.
Prepare a receipt for each native file operation:

- `live_save_document_as`: choose a path inside the configured root.
- `live_save_document`: save the current filename only if it is inside the root.
- `live_export_document`: export a supported native format, e.g. SVG or PNG.
- `live_open_document`: open through native import; installed plugins/resources
  determine fidelity. Reinspect document IDs and the active window afterward.

Existing destinations require explicit `overwrite=true`. File publication,
saved marker and warnings are reported separately. External referenced images or
plugins are not bundled automatically. Preserve the document's dependencies.

For an isolated generated diagram, use the original snapshot create/edit/export
workflow. Snapshot IDs and history do not refer to the GUI document.

## Recover a failed or interrupted operation

Keep the prepared request ID and query `live_get_operation`. A committed receipt
can replay its recorded result for identical input without re-execution. Confirmed
rollback is different from failure before execution. An uncertain or missing
receipt requires inspecting current document/files first; never retry blindly
with a new ID. See [troubleshooting](troubleshooting.md) and the [tool reference](mcp-tools.md).
