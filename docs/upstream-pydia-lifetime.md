# Internal candidate finding: PyDia wrapper reference leaks

This is an AI-assisted internal fork investigation, not an upstream submission.
No upstream issue, comment, or patch has been sent. The reference imbalance is
confirmed in the locally available upstream source; its runtime impact has been
reproduced in this fork's M8 build, not in a separately built upstream checkout.

## Policy review and original source

The original project and reporting destination are identified in `README.md` and
`HACKING.md` as [GNOME Dia on GitLab](https://gitlab.gnome.org/GNOME/dia).
The local README's “Use of Generative AI” section prohibits generated contributions,
including code, documentation, and issues. HACKING directs contributors to that
policy. The [upstream README mirror](https://raw.githubusercontent.com/GNOME/dia/master/README.md)
returned the same restriction when consulted on 2026-09-21; the browsing result
was cached and is not proof of the latest GitLab state. Its narrow translation
exception does not cover this investigation or a report generated from it.

Consequently this note and the generated fix must remain internal to the authorized
fork. User approval alone does not remove the upstream restriction. Any human
follow-up must independently comply with that policy, without hiding AI assistance.
An attempted GitLab issue search for `PyDiaDiagram_Dealloc` was inaccessible, so
duplicate status and whether remote upstream has already fixed this are unverified.

`git merge-base HEAD upstream/master` resolved to
`ad68cc378b7a187706bc2648c48b44d16fb80819`. Read-only `git show` of that locally
available upstream revision confirms the following predate the live MCP changes:

- `plug-ins/python/pydia-diagram.c:42-59`: `PyDiaDiagram_New` obtains a native
  reference with `g_object_ref(dia)`, while `PyDiaDiagram_Dealloc` only frees the
  Python wrapper, without releasing that native reference.
- `plug-ins/python/diamodule.c:99-109`: `PyDia_Diagrams` appends a freshly allocated
  wrapper without releasing the constructor's Python reference. `PyList_Append`
  retains its own reference, so releasing the returned list does not reclaim the
  extra wrapper reference.
- `plug-ins/python/diamodule.c:219-232`: `PyDia_RegisteredSheets` has the same
  constructor-plus-append imbalance. This leaks Python sheet wrappers; those
  wrappers hold a borrowed sheet pointer, so it is not evidence of an additional
  native sheet ownership reference.

These are local source observations from a pinned upstream revision, not a claim
that current remote upstream has been reproduced or audited comprehensively.

## M8 runtime evidence before the correction

`/tmp/dia-m8-build.log:2712-2716` captured the assertion failure in
`test_live_repeated_file_lifecycle_and_gui_stale_mutation`:

```text
assert final["native_identity_entries"] == baseline["native_identity_entries"]
E assert 168 == 8
mcp/tests/test_live_endurance_native.py:159: AssertionError
```

The test performed 20 open/save-as/close cycles on an eight-object native diagram,
verified each closed document's stale reference rejection, and pruned the live
registry's closed generation entries. Nevertheless the native identity entry
count rose from 8 to 168: 160 retained object identities, matching 20 × 8.
This is a lifetime counter, not an RSS or byte measurement. The build reported
312 passing tests and this one failure. The temporary build log may later be
removed; the relevant assertion and test name are preserved here.

The leaked Python/native references explain why a closed diagram's object data
could stay alive even after live registry wrappers are released. The two diagram
reference fixes are complementary: releasing temporary Python references alone
still leaves the native reference unbalanced, while adding a native unref in the
destructor cannot reclaim wrappers whose Python constructor reference leaked.

## Ownership check for the proposed correction

Independent inspection of the existing display lifecycle supports releasing only
the reference owned by the Python wrapper in its destructor:

1. `dia_diagram_new` returns the initial `g_object_new` reference. The
   `open_diagrams` list stores the pointer without adding another reference.
2. `new_display` and `copy_display` add one native reference for each display.
   When the first display is added, the application's `GListStore` also retains
   the diagram.
3. Closing the last display calls `diagram_remove_ddisplay`. It removes the
   application's list-store reference and calls `diagram_destroy`, which releases
   the initial diagram reference.
4. `ddisplay_really_destroy`, at `app/display.c:1354-1356`, then separately clears
   the display's reference. The display reference keeps the diagram alive while
   the preceding removal and destruction calls execute.
5. Each `PyDiaDiagram_New` reference is independent of these references. Its
   destructor must release exactly that reference. A retained wrapper can keep a
   closed diagram alive; releasing the last wrapper can then finalize it safely.

Therefore the native live-file open bridge must **not** add an extra unref of the
initial reference after `new_display`: the final display-removal path already
releases it. Such an extra unref could make the existing display teardown release
an object too early. No bridge ownership change is required for this fix.

For multiple displays, only the final removal destroys the initial reference;
each individual display still releases its own reference. A wrapper can be
released while displays remain open without consuming any display-owned reference.

## Validation boundary

The correction passed the rebuilt native suites and installed Wayland endurance
test: the same 20-cycle case returns from 8 identities to 8. See
[milestone evidence](m8-reliability.md) and [measurements](m8-endurance.md).
No runtime reproduction on an unmodified upstream build or completed remote
duplicate-issue search is claimed.
