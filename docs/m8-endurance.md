# M8 native endurance and lifecycle evidence

Initial measurements (before lifetime correction), 2026-09-21, using `dia-mcp:ubuntu26`, image
`sha256:92465cb32fd10af263110b3b146ab3c3186b82af391556550cdc501b4e03e804`,
with the M8 Python checkout mounted read-only. The image contains the previously
validated native implementation; the newly added identity-table diagnostic must
be verified again after the final native rebuild. This report does not claim a
multi-hour soak or absence of every native allocator leak.

## Reproduction

```sh
docker run --rm --init --network=none \
  -e DIA_MCP_NATIVE=1 -e PYTHONPATH=/checkout/mcp/src \
  -v "$PWD:/checkout:ro" dia-mcp:ubuntu26 \
  xvfb-run -a python -m pytest -q -s -p no:cacheprovider \
  /checkout/mcp/tests/test_live_endurance_native.py \
  /checkout/mcp/tests/test_live_connections_native.py
```

Initial result: **7 passed in 9.88 seconds**. The additional queued-document-close
case passed separately: **1 passed, 5 deselected in 1.11 seconds**. The warm measured read/mutation workload
itself took 2.012 seconds. Fixture readiness now requires a completed live
handshake, rather than socket-file existence, including after process restarts.

## Workloads and resource observations

The read workload opens real Unix connections from eight concurrent clients for
1,000 `get_object` requests (every fifth includes property values). Then 100
cycles each create a box, move it, undo, redo and delete it: 500 receipt-bearing
mutations. A separate GUI performs 20 native open/save-as/close round trips.
Trusted GUI-side fixture observations read `/proc/self/status`, `/proc/self/fd`
and actual listener/cache state; they are not exposed as production protocol
fault controls or remotely accessible inspection tools.

| Stage | GUI RSS KiB | GUI file descriptors | Receipts |
| --- | ---: | ---: | ---: |
| Warm eight-object document | 124,976 | 21 | 0 |
| After 1,000 concurrent reads | 126,680 | 21 | 0 |
| After 100 mutation/history cycles | 129,168 | 21 | 256 |
| File workload baseline | 125,088 | 21 | 2 |
| After 20 open/save-as/close cycles | 138,448 | 21 | 42 |

Every settled sample had zero client connections, zero queued requests, exactly
two listener sources (accept and expiry), and zero native Python wrappers in
registry generation, sheet and receipt caches. Receipts stayed within capacity
256; generation entries never exceeded the number of visible documents. Native
undo intentionally retains a bounded tail of deleted objects. The RSS regression
ceilings allow native history and font/cache allocations; RSS is not an exact
live-object count and these figures do not establish a long-term plateau.

The tests record optional `dia.live_identity_count()` observations when the
rebuilt native module exposes them. They require no identity growth from reads,
reclamation beyond the bounded native undo tail, and exact identity return to
baseline after the file lifecycle workload. Those assertions were **not run**
in the image above (the metric was `null`); final rebuilt-image evidence must
close this explicit gap.

## Lifecycle and fault boundaries

- An actual queued create request is held by a trusted test-only idle callback.
  Listener shutdown releases its client, queue and every source; removes the
  socket; records the receipt as `failed` / `not_started`; and leaves native
  object count unchanged. The peer observes EOF and later connections fail.
- Closing a document while an actual create mutation is queued, then resuming
  dispatch, yields `STALE_DOCUMENT_REFERENCE` with a terminal `failed` /
  `not_started` receipt. No replacement document or object is created and the
  closed ID remains invalid.
- GUI movement and removal between inspection and apply reject the old
  generation. Re-resolving the removed object at a fresh generation rejects its
  stale object ID. Neither path writes to the removed object.
- Two clients issue undo with separate receipts and the same generation. Exactly
  one native undo runs; the other returns `GENERATION_CONFLICT`.
- Two successive real stdio MCP subprocesses attach to the same running Dia and
  observe unchanged live document/session IDs. While the second MCP remains
  open, Dia exits and a replacement GUI starts. The old explicit endpoint fails;
  the new GUI rejects old IDs as `WRONG_SESSION`; a new explicitly configured MCP
  process connects to the replacement. No endpoint is selected automatically.

## Heterogeneous attachment matrix

Each row verifies actual handle attachment and target fanout, endpoint position,
native undo/redo, and explicit disconnection.

| Connector | Target |
| --- | --- |
| Standard Line | UML Class |
| Standard PolyLine | Flowchart Box |
| Standard ZigZagLine | ER Entity |
| Standard BezierLine | Database Table |
| UML Association | Cisco PC |
| Database Reference | Circuit Horizontal Resistor |
| Standard Line | Installed custom shape |

Additional checks grow a UML class's dynamic port list by four ports and connect
to a new member port. Zero-port shapes, nonconnectable box handles and invalid
indices reject the command without disturbing a prior valid connection. Group
member connections remain inspectable but mutation is explicitly unsupported.
This is evidence for these concrete families, not a promise covering every
installed object plugin or any simulation semantics.

The group fixture logs a native `dia_text_set_cursor` renderer assertion while
all assertions pass. This is reported as an observed GUI warning, not silently
classified as fixed; no production C change was made in this test increment.

## Final installed Wayland evidence after lifetime correction

Image `sha256:4dac786e510e8c5a24869fbac8cb33747d0d6db8bb4be8cb2893b3fa43ba9c2f`,
Ubuntu 26, real Wayland compositor, UID/GID 1000:1000, network disabled, installed
code/tests (no source override): all 18 live tests passed in 17.54 seconds.

- 1,000 reads / eight clients plus 100 cycles (500 mutations): native identity
  entries stayed **8** at every sample; FDs stayed **21**; quiescent sources **2**;
  clients/queue/cached native wrappers **0**. Receipts plateaued at **256**.
- RSS warm 77,908 KiB, after reads 79,480 KiB, final 81,416 KiB; measured workload
  time 1.667 seconds. This is a short sustained-operation test, not an overnight soak.
- 20 native file round trips: identities **8 → 8**, FDs **21 → 21**; generations
  remained bounded by two visible documents; RSS **79,032 → 91,976 KiB**. Allocator,
  font/render and undo retention are not claimed to be zero; the regression ceiling
  is 64 MiB and native ownership counters are checked separately.
- Before the lifetime fix the same identity assertion was **8 → 168** and failed.
  The correction is therefore backed by a before/after lifetime test, not RSS inference.
- Actual queued document close, queued shutdown, GUI delete/move races, competing
  history, MCP/Dia restarts and heterogeneous attachments all passed.

## UID 1000 Xvfb restart-fixture path correction

The installed UID 1000 full regression run completed 315 tests successfully but
failed the nested replacement-GUI fixture before handshake: its Unix socket path
exceeded the platform's 108-byte address storage. This was a fixture path-length
failure, not a live document or receipt failure. The replacement fixture directory
is now `r` instead of `replacement-gui`.

Only the failing restart test was repeated against the installed native image,
with UID/GID 1000:1000, Xvfb, network disabled and the corrected checkout mounted
read-only for Python/test code. Result: **1 passed, 5 deselected in 2.37 seconds**.
The 315 previously passing tests were not rerun for this path-only correction.
