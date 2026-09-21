# M8 reliability and protocol hardening

Baseline `54f4139b0`; implementation 2026-09-21. This phase tightens the existing
contract; it does not add new property setters or replace native transactions.

## Lifecycle invariants

1. No persistent Python registry value owns a DiaObject/PyDia wrapper. Object
   resolution scans current native membership inside one GTK dispatch. Unknown,
   detached and foreign-session references fail before native mutation.
2. Native runtime UUIDs are keyed by object lifetime, removed at destroy/detach,
   reset before copy reuse, and never persisted to `.dia`. Undo restoration has
   a new ID; an old ID cannot silently identify a different object.
3. Document IDs combine process session and native document lifetime. Close removes
   reachability; next registry dispatch prunes the document generation record.
   Reload replacement resets native document identity before import.
4. Native object-identity entry count is diagnostic-only and inspected on the GTK
   context in endurance tests. It must return to the live-object baseline after
   create/delete cycles. No tombstones are retained.
5. Generation cache is bounded by currently visible documents. Sheet metadata is
   bounded by the object traversal budget and explicitly reports truncation.
   Native membership tuples may still be allocated before Python traversal checks.
6. Receipts contain plain JSON data, never native wrappers. At most 256 records
   are retained; queued/executing entries cannot expire or be evicted. The idle
   timer reclaims expired terminal/prepared receipts even without another request.
   There is no unbounded expired-ID ledger.
7. Quiescent listener has exactly accept+expiry GLib sources, no clients or queued
   requests. Stop removes sources/clients/queue and its owned socket. Lock inode
   is intentionally retained to prevent a split-lock ownership race.
8. Native plugins may enter nested GTK loops. A per-listener execution guard
   defers further IPC dispatch until the outer call finishes; queued requests keep
   their deadlines. It does not lock normal human GUI interaction.

## Receipt contract

`state` is the precise lifecycle field; legacy `status=succeeded/failed/uncertain`
remains for existing clients. Records and errors also carry `outcome`.

| State | Real implementation meaning | Recovery |
| --- | --- | --- |
| prepared | Reserved, no request has entered dispatch queue | Submit once before expiry |
| queued | Validated request bound to receipt; no native call yet | Query later; duplicate pending submission returns OPERATION_IN_PROGRESS |
| executing | GTK dispatcher entered operation; native call cannot be preempted | Wait/query; no automatic retries |
| committed | Native mutation/history or file publication completed and result constructed | Identical replay returns cached result |
| rolled_back | Native command bridge raised after reverting its temporary native changes | Reinspect IDs/generation; identical replay repeats the error |
| failed | Known not-started/prepublication failure, including cancelled queued work | Reinspect/fix input, prepare a new request |
| uncertain | Unexpected failure or published file with uncertain native saved marker | Inspect document, filesystem and details; never blindly repeat |
| expired | Not retained as a state/tombstone; lookup returns UNKNOWN_OPERATION, also used for eviction/foreign IDs | Inspect state; unknown never authorizes replay (outcome uncertain) |

Queued disconnect, queue deadline and shutdown cancel only unexecuted work. A
client timeout after execution starts cannot undo a commit. The dispatcher never
relabels a completed mutation as timed out. A receipt may be transiently executing
without being externally observable because GTK work is synchronous.

File publication and saved-marker facts are independent. Confirmed publication
with later cleanup/directory-sync errors returns success plus warnings. Failure
inside the native saved-marker update is `uncertain`, explicitly `published=true`.
See [fault evidence](m8-file-faults.md). Expiry or GUI restart loses receipt history;
no distributed transaction/replay service is implied.

## Compatibility and optional functionality

Protocol version remains 1. Version mismatches (missing, older, newer, invalid)
fail before dispatch. The external client checks the requested capability against
the GUI handshake; missing capability returns UNSUPPORTED_LIVE_CAPABILITY before
sending the action. Unknown optional capabilities are ignored. Existing read-only
v1 peers remain useful; a newer adapter does not assume they support newer tools.
A GUI restart has a new session and usually a new PID-specific endpoint. The
adapter never guesses which running GUI should receive a stale write.

Factory disappearance, missing exporter, unsupported property, stale object,
no active document and insufficient semantic evidence stay explicit failures or
empty/unsupported results. Custom shapes are loaded by normal Dia startup;
hot-unload is not a supported live catalog operation and is not simulated.

## Validation and measurements

Evidence is split among [endurance](m8-endurance.md), [file faults](m8-file-faults.md)
and [property-codec audit](property-codecs.md). Existing native transaction tests
cover failed second property/create/connection operations, rollback geometry,
modified state and redo preservation. New tests cover deadlines around execution,
queued cancellation, receipt pinning/expiry/conflicts, unknown postcommit errors,
protocol negotiation, real multi-client traffic, GUI interleaving and restarts.

Short measured endurance runs are evidence for the exercised workload, not proof
of leak-free unlimited uptime. RSS includes native allocator/font/render caches;
FD/source/registry/receipt/identity counts provide more specific invariants.
Native validation and rollback certificates are distinct exception classes. Only
`LiveRollbackError`, emitted after native reversal completes, permits a rolled-back
claim. `LiveValidationError` proves no transaction began. An unclassified native
exception remains uncertain, including a test-injected failure after native commit.
Native property callbacks have a void ABI; descriptor/transaction rejection is
covered, but arbitrary crashing third-party setters cannot be recovered in-process.

## Final milestone evidence

- 260 portable tests; complete build: 9/9 Meson suites and 320 MCP tests.
  Build image: `sha256:bf3fbb4ac265f91cea6496b1e48e17e8c53786e8eefb42000231e0e4230105a1`.
- Installed image as UID 1000, network disabled: 320 passed (44.93 s).
- Installed real Wayland: 18 live tests, including endurance/restarts/fault boundaries.
- The native diagnostic exposed an actual retained-document defect (168 identities
  instead of 8). After correcting PyDia wrapper ownership, the same count is 8 → 8.
- Native divergences: balanced diagram/sheet wrapper references; a bounded identity
  count diagnostic; certified native validation/rollback exception types. The first
  is a pinned-upstream candidate documented in [the internal note](upstream-pydia-lifetime.md).
- Principal merge risk: Python binding ownership and native change-stack internals.
  GTK, native model/history/serialization and dependency versions are unchanged.
- Property audit: 887 registered factories attempted, 886 constructed, nonconstructible
  Group inspected separately; 35 observed property kinds, no new generic setter types.
- Remaining limitation: measured runs are not multi-hour soaks; native callbacks
  cannot be preempted or isolated, and the existing nonfatal text-cursor warning persists.
- Next milestone: M9, compact context/selection workflows and reviewable static plans.

