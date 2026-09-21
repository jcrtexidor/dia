# Troubleshooting local Dia MCP

Use `dia-mcp-config --status` for saved/effective configuration and observed running
endpoints, then `live_handshake` for the chosen GUI's actual capabilities. Keep MCP
stdout protocol-only. Settings changes require restarting Dia, not merely the MCP
adapter. Do not delete an active socket or lock file to work around a failure.

| Symptom/code | Check and recovery |
| --- | --- |
| LIVE_BACKEND_UNAVAILABLE | Use Dia Fork, enable read-only or read/write, restart, and select its actual PID-specific endpoint. A distribution Dia lacks these APIs. Installed launchers supply embedded package/native paths |
| No endpoint / invalid configuration | Check stderr and `dia-mcp-config --status`; correct malformed settings, ownership or permissions. Failure is closed, not automatic write enablement |
| Settings save error | Existing sessions are unchanged. A rejected update can leave the previous configuration active. `settings_published=true` means replacement completed but a later persistence check failed; inspect `--status` before restarting |
| Stale socket after crash | Restart Dia normally. Listener recovery verifies ownership/type and exclusive lock before replacing a stale socket. Do not unlink an active `.lock` inode |
| LIVE_PROTOCOL_MISMATCH | Install a compatible adapter/integration pair. Both must support live protocol 1. Reconnect; restarting the adapter cannot change the GUI protocol |
| UNSUPPORTED_LIVE_CAPABILITY | Read the actual handshake. Use older supported tools or update/restart the GUI; unknown optional capabilities are harmless |
| document=null / no active document | Open a native diagram in the GUI. Snapshot document IDs are not live IDs |
| WRONG_SESSION / STALE_*_REFERENCE | Enumerate fresh context/IDs after close, detach, reload, rollback or Dia restart. Never reconstruct IDs from saved files |
| LIVE_WRITE_DISABLED | Explicitly select read/write in Settings and restart. A read-only MCP connection cannot grant itself write access |
| LIVE_FILES_DISABLED / INVALID_PATH | Configure an existing absolute trusted files root, restart read/write mode, and use a path inside it. No parent traversal or symlink paths; model editing and native file access are distinct |
| Permission denied | Run GUI/client as the same user. Runtime directory must be owned by that user and private (0700); socket is 0600. Check destination directory write permission rather than running Dia as root |
| Wayland/display error | Launch from a graphical session with valid WAYLAND_DISPLAY/XDG_RUNTIME_DIR. Packaged snapshot launcher uses Xvfb when no display is available. Container GUI tests require the explicitly mounted compositor socket and matching UID |
| Missing custom shape/plugin/type | Install the same trusted native shape/plugin in Dia's normal profile and restart. Catalogs describe what each process actually loaded; the adapter cannot recover absent native codecs |
| Unsupported property | Inspect descriptor classification. Use supported scalar/text properties or the GUI. Compound/resource-backed types remain deliberately unsupported; a palette does not imply a codec |
| INVALID_CONNECTION_POINT / INVALID_HANDLE | Inspect the actual object's connections or statically validate the batch. Dynamic ports may change after property edits; re-read them rather than guessing indices |
| GENERATION_CONFLICT | Human or another client changed the document. Reinspect context, review a new plan and prepare a new operation; do not replace only the generation |
| LIVE_LIMIT_EXCEEDED | Page compact reads, reduce the inspected graph or submit smaller reviewed batches. Requests are 16 KiB, responses 1 MiB; full analysis is limited to 256 objects |
| REQUEST_TIMEOUT / lost response during write | Query the prepared receipt. A client timeout cannot cancel synchronous native execution or prove rollback |
| UNKNOWN_OPERATION / uncertain receipt | Receipt history may have expired, been evicted or belonged to another GUI session. Inspect document, history and filesystem before deciding what remains; never blindly repeat |
| FILE_POSTCOMMIT_UNCERTAIN | Publication may have completed while the native saved marker is unknown. Inspect reported `published`/`saved` facts and the file, then reconcile deliberately |
| Native callback hangs/crashes | Trusted plugins execute in Dia's process and cannot be preempted safely. Preserve recovery files and restart; no automatic replay of mutations |

## Migration and compatibility

The adapter version, native Dia version, live protocol and snapshot API are distinct
(see [release policy](release-validation.md)). A newer adapter checks required
capabilities before sending an action to an older GUI. A newer GUI may advertise
optional features an older adapter ignores. A protocol mismatch fails before
native dispatch. Installing an update does not update a running GUI's code.

If a custom sheet disappears but its object factory remains, sheet descriptions
may be missing while native objects still work. If the factory/plugin disappears,
native import may warn, fail or lose unsupported content according to that codec.
MCP does not promise lossless import of unavailable types. Keep the original file,
restore matching trusted dependencies and inspect the native result before saving
over it. Dependency reports are conservative, not completeness proofs.

Runtime IDs and receipts are never persisted into `.dia` files. A GUI restart
requires fresh IDs/endpoint; an MCP-only restart can reconnect to the same running
GUI and query its retained receipts. Receipts are bounded to 256/30 minutes, with
queued/executing work pinned; expiry does not authorize re-execution.
