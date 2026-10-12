# M8: native file failure boundaries

The live file adapter distinguishes publication of bytes from updating the native
editor's filename and saved undo marker. It does not report rollback after an
atomic publication has succeeded. This changes failure reporting, not the native
serialization format or the configured-root policy.

## Observable outcomes

| Boundary | Filesystem and editor facts | Receipt outcome |
| --- | --- | --- |
| Validation, serializer, staged-file sync, or publication fails | Destination unchanged by this operation; filename and saved marker untouched. Temporary cleanup failures are reported separately. | `not_started`, receipt state `failed` |
| Publication succeeds; native commit raises | Destination contains the new bytes. Native filename/dirty/save-marker state might have changed partially or completely. | `uncertain`, receipt state `uncertain` |
| Publication and native commit succeed | Destination and editor saved state confirmed. | `committed` |
| Publication succeeds for export | Destination confirmed; editor filename and dirty state preserved. | `committed`, result `saved: false` |
| Cleanup fails after confirmed commit/export | Confirmed publication is retained; private temporary names may remain. | `committed`, `cleanup_complete: false`, explicit cleanup warnings |
| Directory sync fails after confirmed commit/export | Publication is visible, but crash durability of the directory entry is not confirmed. | `committed`, `directory_synced: false`, explicit warning |
| Directory descriptor release fails after confirmed commit/export | Publication and saved state remain confirmed. | `committed`, explicit directory-close warning |

`not_started` means that publication and the editor saved-state commit did not
start; serialization may have run and private staging artifacts can exist. It
does not mean the operation performed no filesystem work.

Every result carries `published`, `saved`, `directory_synced`,
`cleanup_complete`, `warnings`, and `phase`, plus destination `path` and `format`
once resolved. A post-publication native commit error has code
`FILE_POSTCOMMIT_UNCERTAIN`, outcome `uncertain`, and these facts in `details`.
Its `saved: null` deliberately does not infer editor state from an exception.
Cleanup and directory sync still run after such an error and their independent
results remain in the details.

Receipts retain the exact error details or success result. Repeating an identical
request ID returns the recorded outcome without serializing, publishing, or
committing again. A caller must inspect an uncertain editor state before planning
another operation; a fresh ID is not a safe automatic retry mechanism.

## Fault injection and verification

`mcp/tests/test_live_faults.py` uses real temporary files and injected boundary
failures around the adapter. Its native test double models the editor filename
and dirty flag, including exceptions both before and after commit updates.
Assertions compare actual destination bytes, actual editor state, leftover stage
names, error details, receipt state, and replay call counts.

Covered faults include serializer failure, staged-file fsync failure, atomic
link/replace refusal, native commit failure before/after state changes, cleanup
failure, directory fsync failure, directory-close failure, and combined faults.
Cleanup errors cannot mask the original pre-publication error. Post-publication
cleanup or durability warnings cannot turn a confirmed save into a claim that
nothing changed.

The portable tests complement the existing native round-trip test. They do not
simulate power loss, kernel/filesystem bugs, or hostile directory renames.
Atomic link/replace failure semantics rely on the local Linux filesystem contract;
network filesystems with ambiguous error reporting are outside this guarantee.
No native bridge changes are required for this reporting fix. The bridge already
separates serialization from the native saved-state commit.

Run the focused suite from the repository root:

```sh
mcp/.venv/bin/python -m pytest -q mcp/tests/test_live_files.py mcp/tests/test_live_faults.py
mcp/.venv/bin/ruff check mcp/src/dia_mcp/live/files.py mcp/tests/test_live_files.py mcp/tests/test_live_faults.py
```
