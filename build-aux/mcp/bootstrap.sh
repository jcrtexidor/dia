#!/usr/bin/env bash
# Build the isolated developer environment; never installs host packages.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
image=dia-mcp:ubuntu26
while (($#)); do
  case "$1" in
    --image) [[ $# -ge 2 ]] || { echo 'Missing --image value' >&2; exit 2; }; image=$2; shift 2 ;;
    -h|--help) echo 'Usage: bash build-aux/mcp/bootstrap.sh [--image TAG]'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
command -v docker >/dev/null || { echo 'Docker CLI and an accessible daemon are required.' >&2; exit 1; }
docker info >/dev/null
docker build --progress=plain -f "$root/build-aux/mcp/Dockerfile" -t "$image" "$root"
printf '\nBuilt native Dia, its dependencies, and the MCP environment.\nDeveloper shell:\n'
printf '  docker run --rm --init -it --user %q -e HOME=/tmp -e PYTHONPATH=/workspace/mcp/src -v %q -w /workspace %q bash\n' \
  "$(id -u):$(id -g)" "$root:/workspace" "$image"
printf '\nInside the shell: python -m pytest -q -m "not native" /workspace/mcp/tests\n'
printf 'Native installed checks: DIA_MCP_NATIVE=1 xvfb-run -a python -m pytest -q -p no:cacheprovider /src/dia/mcp/tests\n'
printf 'Host Task workflow additionally requires task and uv: task mcp:check; task mcp:test\n'
