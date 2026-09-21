# M9 agent workflows and evidence

M8 was closed at `5d0898ef5` before this feature increment. No native C changes,
new property codecs or dependency updates are part of M9.

## Delivered contract

Five additive read-only tools compose the existing native model: current context,
detailed selection, attached neighborhood, selection plans and static command
validation. Existing 32 tools remain, for a total of 37. Selection is explicit
human pointing, not authorization to edit. All resulting mutations still require
write opt-in, a prepared receipt, current generation and native transaction.

Current context includes the first eight detailed selected objects; subsequent
selection/neighborhood pages return at most eight. Large native attachment data
can still hit the 1 MiB response bound. Document traversal remains bounded at
10,000 objects. Full graph analysis remains limited to 256 objects. Plans target
at most 64 selected objects; the 16 KiB request budget also applies when submitting
commands (large property plans may need smaller, separately reviewed batches).

Plans expose commands, existing targets, intended creations, assumptions,
unsupported semantics and expected structural effects. Supported selection
intents are native layout, relative move and bulk named scalar properties. Layer
reassignment and compound UML/database edits are explicitly unsupported by the
current generic ABI. Existing creation recipes cover the four evidenced domains;
no palette-specific module is required for generic operations.

Static validation reads IDs, membership, descriptors, ports, native catalog and
eligibility. It does not instantiate factories or execute/rollback probes. Native
callbacks, enum/range data not exposed by descriptors, and intermediate batch
states are deferred. `valid` means no known static rejection; `complete` describes
available validation coverage, not a promise of successful application. Issues
and alternatives are bounded and report truncation. Stale generation errors offer
current-generation recovery guidance without silently updating a reviewed plan.

Structural analysis preserves the previous graph fields and adds native layer/
group facts, derived components, and bounded overlap/unattached-handle heuristics.
Native type prefixes are marked heuristic domain classification. Only the already
evidenced UML relationship rule emits a supported relationship. Unknown/custom
objects remain part of the generic graph. No direction, key/cardinality, network
reachability, circuit correctness or engineering simulation is inferred.

Semantic analysis and creation recipes are lazy optional imports. A subprocess
blocks both modules and still imports/builds generic tools, negotiates generic
capabilities and plans generic movement. Missing semantic capability does not
prevent generic live operations. Resources add active context and capabilities;
one reusable selection prompt complements the previous diagram explanation.

## Validation evidence

Targeted native tests cover 12 selected objects across pages (including a custom
type), attached neighbors, mixed classification/evidence, move/layout/property
plans, unchanged generation/modified/geometry/history during validation, plan
apply plus GUI undo/redo, retained earlier history, bounded property/point errors,
stale generation and actual MCP stdio tools/resources/prompt annotations.

A fixture initially attached a handle without updating geometry. The new history
test normalizes that connection with an ordinary native transaction before taking
its baseline; it then verifies the prior transaction survives the plan workflow.
No production workaround was added for the fixture.

Portable tests add schema bounds/invalid native UTF-8 and NUL names, missing-domain
imports, inert planning, evidence caps, descriptor-only validation and alternatives.
Full regression and platform results are recorded at the milestone gate below.

## Scope and maintenance

Implementation: `live/{protocol,registry,planning,validation}.py`, `server.py`,
`semantics.py`, `recipes.py`; tests: workflow contract, native workflows, planning,
validation, semantics/recipes and existing stdio inventory. No native divergence
was added. Compatibility is additive protocol-v1 capabilities, with original
snapshot API, GTK3, Meson, native history and file behavior retained.

[Tool audit and call-count comparisons](m9-tool-review.md) distinguish analytical
round-trip counts from latency. No M9 latency improvement is claimed from those
counts. Next milestone: M10 installation/configuration and clean-user validation.

## Milestone build/platform results

- Portable contract: 341 passed, 64 native tests deselected; Ruff lint/format clean.
- Full Ubuntu 26 build: 9/9 Meson suites, 405 MCP tests, dependency check clean.
- Real Wayland installed GUI: 22 tests passed (20.49 s).
- Image: `sha256:7c93868cd58c221fb1dc9ced4ba9af655fd1d0683423b2c67c73406db3d9445a`.
- Installed image as UID 1000, network disabled: 405 passed (48.68 s).
