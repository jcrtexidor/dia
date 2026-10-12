#!/usr/bin/env bash
# Local release checks and artifacts only. Never pushes images or publishes packages.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
image=dia-mcp:ubuntu26
output="$root/artifacts/release"
while (($#)); do
  case "$1" in
    --image|--output)
      [[ $# -ge 2 ]] || { echo "Missing $1 value" >&2; exit 2; }
      if [[ $1 == --image ]]; then image=$2; else output=$2; fi
      shift 2 ;;
    -h|--help)
      echo 'Usage: bash build-aux/mcp/release.sh [--image TAG] [--output EMPTY_DIRECTORY]'
      echo 'Requires Docker daemon, task, uv and Python >=3.12; installs nothing on the host.'
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
for executable in docker task uv python3; do
  command -v "$executable" >/dev/null || { echo "Required host command missing: $executable" >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python >=3.12 required"'
docker info >/dev/null
mkdir -p -- "$output"
output=$(cd -- "$output" && pwd)
[[ -z $(find "$output" -mindepth 1 -maxdepth 1 -print -quit) ]] || {
  echo 'Output directory is not empty; choose a new directory to preserve previous evidence.' >&2
  exit 1
}
temporary=$(mktemp -d /tmp/dia-release.XXXXXXXX)
runtime_image="dia-mcp-release-smoke:$(basename "$temporary" | tr '[:upper:]' '[:lower:]')"
cleanup() {
  docker image rm "$runtime_image" >/dev/null 2>&1 || true
  rm -rf -- "$temporary"
}
trap cleanup EXIT
checks="$output/checks.json"
printf '[]\n' > "$checks"
record() {
  python3 - "$checks" "$1" "$2" "$3" "${4:-}" <<'PY'
import json
import sys
from pathlib import Path
path, name, status, log, reason = sys.argv[1:]
records = json.loads(Path(path).read_text())
record = {"name": name, "status": status, "log": log}
if reason:
    record["reason"] = reason
records.append(record)
Path(path).write_text(json.dumps(records, indent=2) + "\n")
PY
}
run_check() {
  local name=$1
  shift
  if "$@" 2>&1 | tee "$output/$name.log"; then
    record "$name" passed "$name.log"
  else
    record "$name" failed "$name.log"
    cp -- "$checks" "$output/failed-checks.json"
    echo "Release stopped at $name; logs preserved in $output" >&2
    exit 1
  fi
}
cd -- "$root"
run_check portable task mcp:check
run_check image_build task mcp:build "MCP_IMAGE=$image"
run_check native task mcp:test "MCP_IMAGE=$image"
wayland_socket=${WAYLAND_DISPLAY:-}
if [[ -n $wayland_socket && $wayland_socket != /* ]]; then
  wayland_socket="${XDG_RUNTIME_DIR:-/nonexistent}/$wayland_socket"
fi
if [[ -n $wayland_socket && -S $wayland_socket ]]; then
  run_check wayland docker run --rm --init --network=none --user "$(id -u):$(id -g)" \
    -e DIA_MCP_NATIVE=1 -e GDK_BACKEND=wayland -e WAYLAND_DISPLAY=/tmp/dia-wayland.sock \
    -v "$wayland_socket:/tmp/dia-wayland.sock:ro" "$image" bash -c '
      runtime=$(mktemp -d /tmp/dia-wayland.XXXXXXXX)
      trap '\''rm -rf -- "$runtime"'\'' EXIT
      export XDG_RUNTIME_DIR="$runtime"
      python -m pytest -q -p no:cacheprovider /src/dia/mcp/tests/test_live*_native.py
    '
else
  reason='No accessible WAYLAND_DISPLAY socket; real compositor validation was not run.'
  printf 'SKIPPED: %s\n' "$reason" | tee "$output/wayland.log"
  record wayland skipped wayland.log "$reason"
fi
bash "$root/build-aux/mcp/package.sh" --image "$image" --output "$output" \
  --version '0.98.0+mcp0.3.0-1' 2>&1 | tee "$output/package.log"
shopt -s nullglob
packages=("$output"/*.deb)
[[ ${#packages[@]} -eq 1 ]] || { echo 'Expected exactly one .deb artifact.' >&2; exit 1; }
mkdir "$temporary/runtime"
cp -- "${packages[0]}" "$temporary/runtime/package.deb"
cp -- "$root/build-aux/mcp/package-smoke.py" "$temporary/runtime/package-smoke.py"
install_check() {
  docker build --progress=plain -f "$root/build-aux/mcp/package-runtime.Dockerfile" \
    --build-arg "SMOKE_UID=$(id -u)" --build-arg "SMOKE_GID=$(id -g)" \
    -t "$runtime_image" "$temporary/runtime" || return
  docker run --rm --init --network=none --user "$(id -u):$(id -g)" \
    -v "$output:/results" "$runtime_image"
}
run_check install install_check
image_id=$(docker image inspect --format '{{.Id}}' "$image")
python3 "$root/build-aux/mcp/validate-release.py" --create --root "$root" --output "$output" \
  --checks "$checks" --image "$image" --image-id "$image_id" | tee "$output/validation.json"
printf '\nValidated local artifacts: %s\nNo package or image was published.\n' "$output"
