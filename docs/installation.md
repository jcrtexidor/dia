# Install Dia with local MCP on Ubuntu 26

The primary package is **dia-mcp-fork**, for Ubuntu 26.04 amd64 and Python 3.14.
It contains the GTK3 Dia fork, native plugins/resources, the external MCP adapter
and its locked Python dependencies. It coexists with distribution Dia: use **Dia
Fork** in Applications or `dia-fork`, not an unrelated `dia` executable.

Build artifacts are local candidates, not an automatically published or signed
release. Obtain the `.deb` and `SHA256SUMS` from the same trusted build, then:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./dia-mcp-fork_0.98.0+mcp0.3.0-1_amd64.deb
```

APT installs declared Ubuntu runtime dependencies. Package installation does not
run pip, contact an AI service, configure an MCP client or enable live access.
A checksum checks integrity against its trusted manifest; it is not a signature.

## First run

1. Open **Dia Fork**. It works as a normal editor; MCP is off by default.
2. Open **Dia MCP Settings** from Applications (`dia-mcp-config --gui`). Select
   read-only and save. Restart Dia Fork for the new mode to take effect.
3. Open or create a diagram in Dia. The settings status lists actual running
   endpoints; startup stderr also prints the exact socket path.
4. Configure a local stdio-capable MCP client with the command below, using that
   exact endpoint. Start with `live_get_current_context`.

Equivalent explicit terminal configuration:

```sh
dia-mcp-config --mode read-only
dia-fork
dia-mcp-config --status
```

To enable edits, select read/write in Settings. For MCP native Open/Save/export,
choose an existing trusted directory as the allowed files root. Read-only permits
inspection, not native file open or mutation. Writes and file access require the
explicit mode/root and a restart; saving settings does not reconfigure running
processes. See [security](security.md).

## Generic MCP client configuration

A local MCP client must launch this executable with stdin/stdout connected:

```text
command: /usr/bin/dia-mcp
arguments:
  --workspace
  /absolute/path/to/snapshot-output
  --live-socket
  /run/user/1000/dia-mcp/live-ACTUAL_PID.sock
```

Replace the UID, PID and workspace with your actual paths. Client configuration
file syntax differs; the executable and argument array are the portable contract,
not a universal JSON schema. No URL, API token or network listener is involved.
The workspace belongs to isolated snapshot exports; it is separate from the GUI's
allowed native files root. Omit `--live-socket` for snapshot-only use. The packaged
launcher supplies native library paths and a headless display when needed; users
do not need PYTHONPATH or the repository.

Only clients able to launch **local stdio MCP** can use this setup directly.
Hosted/web-only environments that require a remote HTTP endpoint cannot directly
reach this local Unix socket. No network bridge is installed or implied. MCP
registration and AI-account authentication remain client-specific and are not
changed by the package. After a Dia restart, read its new endpoint and reconnect;
the adapter never guesses among running Dia instances.

## Why this package format

| Option | Decision |
| --- | --- |
| Ubuntu `.deb` | Primary: preserves `/opt/dia` resource/plugin paths and the Python 3.14 venv, declares GTK/GI/native dependencies and installs distinct launchers |
| Source/container | Supported development alternative; see [development](mcp-development.md). Containers need explicit display/runtime sharing for GUI access |
| Python wheel alone | External adapter only; does not provide the fork's native lifetime, command or file APIs |
| AppImage | Not produced: Python embedding, image loaders and native resource paths require additional relocation/runtime work |
| Flatpak | Not produced: private runtime/socket exposure to external MCP clients needs a deliberate sandbox/portal design |

The `.deb` preserves `/opt/dia` and `/opt/dia-mcp-venv`; it is not relocatable.
Python ABI, GTK plugin discovery, loaders and installed native resources are tested
in a fresh Ubuntu runtime. Custom user sheets/plugins remain in Dia's normal
locations (`~/.dia`); they are trusted native inputs, not packaged or sandboxed by
MCP. Keep required plugins installed when reopening their documents.

## Building a candidate locally

From a clean checkout with Docker available:

```sh
./build-aux/mcp/bootstrap.sh
# With Task and uv available for full contributor/release checks:
task mcp:release-check
```

`task mcp:package` packages an already validated development image. The full
release check additionally tests a fresh Ubuntu installation and creates local
validation/checksum evidence under `artifacts/release`. It does not publish.
See [release validation](release-validation.md) for versioning and limits.
