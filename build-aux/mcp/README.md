# Ubuntu 26.04 container for Dia MCP

Run from the repository root:

```sh
docker build --progress=plain -f build-aux/mcp/Dockerfile -t dia-mcp:ubuntu26 .
docker run --rm --init dia-mcp:ubuntu26 dia --version
docker run --rm --init dia-mcp:ubuntu26 xvfb-run -a meson test -C /opt/dia-build --print-errorlogs
```

Start the MCP stdio server with a mounted workspace and the caller's user ID:

```sh
mkdir -p artifacts
docker run --rm --init -i --user "$(id -u):$(id -g)" \
  -v "$PWD/artifacts:/workspace" dia-mcp:ubuntu26
```

Keep stdin open with `-i`; do not allocate a terminal (`-t`) for the JSON-RPC
stdio transport. The default command starts `dia-mcp --workspace /workspace`
under Xvfb. All diagram files stay in the mounted workspace.

The build also runs the MCP tests, including native Dia integration and the
stdio protocol. To repeat them against the installed package:

```sh
docker run --rm --init --user "$(id -u):$(id -g)" \
  -e DIA_MCP_NATIVE=1 dia-mcp:ubuntu26 \
  xvfb-run -a python -m pytest -q -p no:cacheprovider /src/dia/mcp/tests
```

The image builds the actual Dia source with GTK 3 and Python embedding, runs
the upstream Meson suite under Xvfb, and installs Dia as `/opt/dia/bin/dia`.
Libraries and native plug-ins are installed under `/opt/dia/lib`; Python
startup and plug-in scripts are installed under `/opt/dia/share/dia`.
No host packages or host Python environment are changed.

Use `--init` for container runs. `xvfb-run` relies on signal handling while
waiting for Xvfb to become ready; when run directly as PID 1 it can remain
blocked before starting Dia or Python. Docker's init process also forwards
termination signals and reaps child processes.

The separate virtual environment `/opt/dia-mcp-venv` contains `mcp==1.30.0`
and `pytest==9.1.1`. Runtime SDK dependencies come from
`mcp/requirements.lock`, verified by pip with `--require-hashes`. The local MCP
package is installed from `./mcp` with `--no-deps`. The environment can see
Ubuntu's PyGObject packages through
`--system-site-packages`. Dia itself embeds Ubuntu's Python, not this virtual
environment.

`xpm-pixbuf` is pinned to commit
`d290a0c846687b22d2a8c5aaec83a6689f30e1c3` in the copied container source.
The Ubuntu image is pinned by digest. Apt dependencies are not snapshot-pinned,
so a future build can resolve newer Ubuntu security updates. Override
`BUILD_JOBS` to change build parallelism (default: 4).

In a managed environment where `~/.docker` is read-only, use a writable,
temporary Docker CLI configuration without copying stored credentials:

```sh
mkdir -p /tmp/dia-mcp-dockerconfig
DOCKER_CONFIG=/tmp/dia-mcp-dockerconfig docker build --progress=plain \
  -f build-aux/mcp/Dockerfile -t dia-mcp:ubuntu26 .
```

## Validation record

On 2026-09-18, the upstream source compiled successfully in Ubuntu 26.04
(`amd64`) without compatibility patches. Meson compiled 583 targets in
approximately 60 seconds and reported **9 passed, 0 failed**:

- Desktop and AppStream metadata validation.
- Colour selector, colour, graphene, SVG, bounding-box and object tests.
- XML validation of a Dia-exported shape.

The resolved build environment included GCC 15.2, GTK 3.24.52, Python 3.14.4,
libxml2 2.15.2 and Meson 1.10.1. The log is available during this work session at
`/tmp/dia-mcp-ubuntu26-build.log`; installed image test logs live in
`/opt/dia-build/meson-logs/testlog.txt`.

The first attempted build stopped before compilation because Docker Buildx
could not write its activity metadata below `~/.docker` in the managed
environment. The temporary `DOCKER_CONFIG` command above resolved that
environment restriction. There were no native build or Meson test failures.

An installed-runtime smoke check also verified that `dia` and `gi` import in
embedded Python 3.14.4 with `sys.prefix == "/usr"`, that FastMCP imports from
the separate virtual environment, and that native SVG export produces a
parseable 31,530-byte SVG from `samples/render-test.dia`. That upstream sample
references two unavailable PNG files (`dia_logo.png`, `dia_gnome_icon.png`), so
the smoke check reports those image warnings. They do not fail the export.

## User package and repeatable release gate

The image is also the input for `package.sh`; it preserves native resource/plugin
paths and the separate venv in a local Ubuntu `.deb`. `package-runtime.Dockerfile`
installs that candidate into a fresh Ubuntu base; `package-smoke.py` checks it as
a non-root user without a checkout. Use root `task mcp:release-check` to include
portable, build, installed, Wayland, package, documentation/version and checksum
checks. Details: [installation](../../docs/installation.md) and
[release validation](../../docs/release-validation.md). No release is published.
