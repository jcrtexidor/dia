# Dia integration: M8–M10 roadmap

Baseline: `54f4139b0`, reviewed 2026-09-21. M8–M10 completed sequentially. Code and acceptance tests are
 authoritative. No replacement of the native model, history, serialization,
GTK3/Meson or separate snapshot/live backends is planned.

| Milestone | Evidence-backed baseline / acceptance |
| --- | --- |
| M1 discovery | Worker sheets/types, custom installation discovery tests |
| M2 live reads | Main-context dispatch, runtime identity, GUI lifecycle tests |
| M3 transactions | Native changes, rollback and shared GUI/API undo/redo tests |
| M4 generic editing | Installed factories, safe scalar/text properties; heterogeneous and zero-port tests; compound setters not claimed |
| M5 files | Native save/open/export, explicit overwrite, groups/layers/custom/connection round trips; missing-plugin losslessness not claimed |
| M6 semantics | Optional UML codec, bounded evidence-based topology and creation recipes; simulation not claimed |
| M7 context/layout | Eight native layout modes, two resources and one prompt; measured 256-object reads; 199 regression tests and Wayland normal/scale-2 evidence |
| M8 reliability | Complete: 320 MCP tests, 9 native suites, 18 Wayland GUI tests; bounded measured resources, certified outcomes, property audit and connection matrix; see [M8 evidence](m8-reliability.md) |
| M9 agent ergonomics | Complete after M8: 405 MCP tests, 9 native suites and 22 Wayland tests; compact context, selection/neighborhood, static validation and reviewable plans; [M9 evidence](m9-validation.md) |
| M10 user readiness | Complete after M9: Ubuntu26 amd64 deb, private settings/GTK status, bootstrap/release gates, documentation and clean-user acceptance; 454 MCP tests, 9 native suites, 22 Wayland normal/scale2; [M10 evidence](m10-validation.md) |

## Sequential delivery gates

Each phase gets focused changes, targeted tests, complete regression validation,
Wayland verification where relevant, an evidence/limitations report and commits.
M9 user-facing expansion starts only after M8 passes. M10 packaging implementation
starts only after M9 passes. Existing requirements already met are verified rather
than reimplemented. The user-authorized fork workflow publishes validated commits;
release artifacts are built and checked locally, not automatically published.

M8 will keep runtime IDs ephemeral, receipts bounded, and unsupported property
codecs closed. Queued versus executing versus terminal outcomes must describe
actual GTK execution; an expired receipt must never authorize replay. Faults are
injected by trusted test harnesses, never remotely selectable production knobs.

M9 will compose the generic model. Plans are inert data; static validation is not
a promise that plugins or the filesystem cannot fail during execution. Evidence,
derived structure and heuristics remain distinguishable. No palette is required
to have a semantic module and no module is required for generic editing.

M10 will evaluate a relocatable user installation built by the existing Ubuntu
container versus system packages/sandboxes. The primary choice must be tested in
a fresh home, preserve native plugin/resource paths, and keep writes explicit.
No workstation configuration or client account is changed without authorization.
