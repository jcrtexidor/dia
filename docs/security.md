# Local trust and explicit access

Dia MCP is a local integration for the same desktop user. It is not a sandbox,
remote server, multi-user authorization system or engineering validation engine.
The external MCP SDK runs separately from Dia's embedded stdlib-only live adapter.
The native model, plugins, history and serializers remain inside Dia.

## Modes

| Mode | Behavior |
| --- | --- |
| Off (default) | No live endpoint; normal standalone Dia and isolated snapshot workflows remain available |
| Read-only | Bounded live inspection, analysis, inert plans and static validation; no native mutation or file operation |
| Read/write | Explicitly permits native transactions/history; native Open/Save/export additionally require a configured trusted root |

Use **Dia MCP Settings** or `dia-mcp-config` locally. The MCP tool surface cannot
change this configuration. Settings are user-owned private JSON; malformed/unsafe
configuration fails closed. Changing settings requires restarting Dia. Status
separates desired configuration from observed running endpoints; selecting objects
or connecting a client does not itself grant edit permission.

Legacy development environment variables remain supported: `DIA_MCP_LIVE`,
`DIA_MCP_WRITE`, `DIA_MCP_FILES_ROOT`. They can override saved settings and must be
considered when diagnosing effective mode. `DIA_MCP_LIVE=0` disables integration.
Do not set broad global write variables as a substitute for deliberate configuration.
No install step enables MCP or writes AI-client account settings.

## Socket and command boundary

The private XDG runtime directory is owned by the user (0700); the Unix socket is
0600 and verifies peer UID. There is no TCP listener. Requests are versioned,
allowlisted and bounded; no tool evaluates Python, shells or arbitrary native
functions. I/O only queues validated input; GTK native access occurs on the main
context, with reentry guarded while a live call executes. The normal GUI remains
available to the human and is not locked by MCP.

Any process already running as this user can potentially access their files and
socket. Peer UID is a local boundary, not authentication between mutually hostile
applications sharing the account. Only connect clients/agents you trust with the
selected mode. An AI client's consent and data-handling rules are separate from
this native integration.

## Files and plugins

The allowed files root bounds MCP native open/save/export destinations. Paths with
parent traversal or symlink components are rejected. Staged native serialization
and atomic publication protect existing files unless overwrite was explicitly
requested. Published bytes and GUI saved-marker state are tracked separately.

This is **not** an arbitrary-plugin filesystem sandbox. Native importers may read
resources referenced by a diagram. Trusted plugins/custom shapes execute native
or embedded code and may have their own access patterns. Hostile concurrent
renaming of trusted root directories during native import is outside the guarantee.
Do not load untrusted plugins/documents assuming the root makes them safe.

Snapshot output uses the separate configured workspace. No arbitrary destination
access, automatic network access, credential collection, cloud upload or automatic
release publishing is added by the integration.

## Failure and authority

Generation checks reject stale writes from other clients or human edits. A receipt
reserves the operation identity before mutation; identical retained retries return
the recorded outcome. Only a native rollback certificate permits a rollback claim.
A timeout or unknown/expired receipt is not proof that nothing happened.

Bounded static validation and optional semantic helpers cannot prove arbitrary
native callbacks will succeed. Diagrams and topology do not certify electrical
safety, routing, hydraulic/mechanical behavior or regulatory compliance. The human
retains control of GUI editing, Undo, files and the decision to enable writes.
