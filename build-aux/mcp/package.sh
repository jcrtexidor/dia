#!/usr/bin/env bash
# Package an already validated image. No host installation or publication.
set -euo pipefail
image=dia-mcp:ubuntu26
output=
version=0.98.0+mcp0.3.0-1
owner_uid=$(id -u)
owner_gid=$(id -g)
while (($#)); do
  case "$1" in
    --image) image=${2:?}; shift 2 ;;
    --output) output=${2:?}; shift 2 ;;
    --version) version=${2:?}; shift 2 ;;
    --uid) owner_uid=${2:?}; shift 2 ;;
    --gid) owner_gid=${2:?}; shift 2 ;;
    --help) printf '%s\n' 'package.sh --image IMAGE --output DIRECTORY [--version VERSION] [--uid UID --gid GID]'; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ -n "$output" && "$owner_uid" =~ ^[0-9]+$ && "$owner_gid" =~ ^[0-9]+$ ]] || {
  printf '%s\n' 'An output directory and numeric owner IDs are required' >&2; exit 2;
}
[[ "$version" =~ ^[0-9][0-9A-Za-z.+:~_-]*$ ]] || { printf '%s\n' 'Invalid package version' >&2; exit 2; }
mkdir -p -- "$output"
output=$(cd -- "$output" && pwd -P)
docker run --rm --init -i --network=none --user 0:0 \
  --mount "type=bind,src=$output,dst=/artifacts" \
  --entrypoint /bin/bash "$image" -s -- "$version" "$owner_uid" "$owner_gid" <<'CONTAINER'
set -euo pipefail
version=$1
owner_uid=$2
owner_gid=$3
work=$(mktemp -d /tmp/dia-package.XXXXXX)
publish=
trap 'rm -rf -- "$work"; if [[ -n "$publish" ]]; then rm -rf -- "$publish"; fi' EXIT
for existing in /artifacts/*.deb /artifacts/SHA256SUMS /artifacts/footprint.json; do
  if [[ -e "$existing" || -L "$existing" ]]; then
    printf 'Refusing to overwrite an existing candidate: %s\n' "$existing" >&2
    exit 1
  fi
done
payload=$work/payload
architecture=$(dpkg --print-architecture)
[[ "$architecture" == amd64 ]] || { printf '%s\n' 'This release is validated only for amd64' >&2; exit 1; }
/opt/dia-mcp-venv/bin/python - <<'PY'
import importlib.metadata as m
import sys
from pathlib import Path
assert m.version('dia-operations-mcp') == '0.3.0', 'Rebuild the validated 0.3.0 image before packaging'
assert sys.version_info[:2] == (3, 14), 'Expected the Ubuntu 26.04 Python 3.14 ABI'
assert Path('/opt/dia-mcp-venv/bin/dia-mcp-config').is_file(), 'Config entrypoint is missing'
PY
mkdir -p "$payload/opt" "$payload/DEBIAN" "$work/debian"
cp -a /opt/dia /opt/dia-mcp-venv "$payload/opt/"
# Virtualenv shebangs intentionally preserve their installed absolute prefix.
ln -sfn /usr/bin/python3.14 "$payload/opt/dia-mcp-venv/bin/python3"
mkdir -p "$payload/opt/dia/share/dia/mcp-python"
ln -s /opt/dia-mcp-venv/lib/python3.14/site-packages/dia_mcp \
  "$payload/opt/dia/share/dia/mcp-python/dia_mcp"
mkdir -p "$payload/usr/bin" "$payload/usr/share/applications" "$payload/usr/share/doc/dia-mcp-fork"
cat > "$payload/usr/bin/dia-fork" <<'GUI'
#!/bin/sh
unset PYTHONHOME VIRTUAL_ENV DIA_PYTHON_PATH
export PYTHONPATH=/opt/dia/share/dia/mcp-python
export LD_LIBRARY_PATH=/opt/dia/lib
export PYTHONDONTWRITEBYTECODE=1
exec /opt/dia/bin/dia "$@"
GUI
cat > "$payload/usr/bin/dia-mcp" <<'MCP'
#!/bin/sh
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV DIA_PYTHON_PATH
export LD_LIBRARY_PATH=/opt/dia/lib
export PYTHONDONTWRITEBYTECODE=1
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  exec xvfb-run -a /opt/dia-mcp-venv/bin/dia-mcp --dia-binary /opt/dia/bin/dia "$@"
fi
exec /opt/dia-mcp-venv/bin/dia-mcp --dia-binary /opt/dia/bin/dia "$@"
MCP
cat > "$payload/usr/bin/dia-mcp-config" <<'CONFIG'
#!/bin/sh
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV DIA_PYTHON_PATH
export LD_LIBRARY_PATH=/opt/dia/lib
export PYTHONDONTWRITEBYTECODE=1
exec /opt/dia-mcp-venv/bin/dia-mcp-config "$@"
CONFIG
chmod 755 "$payload/usr/bin/"*
cat > "$payload/usr/share/applications/dia-mcp-fork.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Dia Fork
Comment=Native diagram editor with optional local MCP integration
Exec=/usr/bin/dia-fork %F
Icon=/opt/dia/share/icons/hicolor/scalable/apps/org.gnome.Dia.svg
Terminal=false
Categories=Graphics;VectorGraphics;Engineering;
MimeType=application/x-dia-diagram;
DESKTOP
cat > "$payload/usr/share/applications/dia-mcp-settings.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Dia MCP Settings
Comment=Configure local Dia MCP access for your account
Exec=/usr/bin/dia-mcp-config --gui
Icon=/opt/dia/share/icons/hicolor/scalable/apps/org.gnome.Dia.svg
Terminal=false
Categories=Settings;
DESKTOP
# Public launchers use distinct IDs; do not shadow the distribution's desktop entry.
rm -f "$payload/opt/dia/share/applications/org.gnome.Dia.desktop"
cp /src/dia/COPYING "$payload/usr/share/doc/dia-mcp-fork/copyright"
for document in installation user-guide troubleshooting security release-validation; do
  cp "/src/dia/docs/$document.md" "$payload/usr/share/doc/dia-mcp-fork/"
done
cat > "$payload/usr/share/doc/dia-mcp-fork/README" <<'DOC'
Unofficial GNOME Dia fork with AI-assisted MCP additions, not an upstream release.
Fork source and documentation: https://github.com/jcrtexidor/dia
Run dia-fork for the editor. MCP access defaults off. Configure it per user using
Dia MCP Settings or dia-mcp-config --mode read-only. Restart Dia after changes.
Use read-write with an explicit files root only when editing is desired.
The MCP SDK is isolated in /opt/dia-mcp-venv. Source and license notices bundled
with Python distributions remain in their dist-info directories.
No service, global Python installation, or network listener is installed.
DOC
cat > "$work/debian/control" <<'CONTROL'
Source: dia-mcp-fork
Section: graphics
Priority: optional
Maintainer: Dia fork maintainers <noreply@localhost>

Package: dia-mcp-fork
Architecture: amd64
Description: Native Dia fork with local MCP integration
CONTROL
# Include dynamic plugins and the bundled wheels, not only the GUI executable.
mapfile -d '' elf_files < <(python3 - "$payload" <<'PY'
import sys
from pathlib import Path
for path in Path(sys.argv[1]).rglob('*'):
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as stream:
            if stream.read(4) == b'\x7fELF':
                sys.stdout.buffer.write(str(path).encode() + b'\0')
PY
)
args=()
for file in "${elf_files[@]}"; do args+=("-e$file"); done
# Private bundled libraries have no distro shlibs record; all external libraries
# are resolved from this image's dpkg metadata, then verified in a clean runtime.
shlibs=$(cd "$work" && dpkg-shlibdeps --ignore-missing-info -O \
  -l"$payload/opt/dia/lib" "${args[@]}")
depends=${shlibs#shlibs:Depends=}
[[ "$depends" != "$shlibs" && -n "$depends" ]] || { printf '%s\n' 'Dependency extraction failed' >&2; exit 1; }
installed_size=$(du -sk "$payload/opt" | cut -f1)
cat > "$payload/DEBIAN/control" <<CONTROL
Package: dia-mcp-fork
Version: $version
Architecture: $architecture
Section: graphics
Priority: optional
Maintainer: Dia fork maintainers <noreply@localhost>
Installed-Size: $installed_size
Depends: $depends, python3.14 (>= 3.14), python3.14 (<< 3.15), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, librsvg2-common, fonts-dejavu-core, shared-mime-info, xvfb, xauth
Description: Native Dia fork with local MCP editing and isolated Python adapter
 Includes the Dia GUI, native PyDia integration and a private MCP virtualenv.
 Per-user integration defaults off. No network service is installed.
CONTROL
# Standard desktop database updates are optional and never fetch dependencies.
cat > "$payload/DEBIAN/postinst" <<'MAINT'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications
fi
MAINT
cp "$payload/DEBIAN/postinst" "$payload/DEBIAN/postrm"
chmod 755 "$payload/DEBIAN/postinst" "$payload/DEBIAN/postrm"
artifact=dia-mcp-fork_${version}_${architecture}.deb
dpkg-deb --root-owner-group --build "$payload" "$work/$artifact"
python3 - "$payload" "$work/$artifact" "$work/footprint.json" "$version" <<'PY'
import hashlib,json,sys
from pathlib import Path
root, artifact, output = map(Path,sys.argv[1:4])
files=[p for p in root.rglob('*') if p.is_file() and not p.is_symlink()]
manifest={'package':'dia-mcp-fork','version':sys.argv[4],'architecture':'amd64',
          'artifact':artifact.name,'artifact_bytes':artifact.stat().st_size,
          'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
          'file_count':len(files),'payload_bytes':sum(p.stat().st_size for p in files),
          'prefixes':{prefix:sum(p.stat().st_size for p in files if p.is_relative_to(root/prefix))
                      for prefix in ('opt/dia','opt/dia-mcp-venv')},
          'versions':{'native':'0.98.0','adapter':'0.3.0','live':1,'snapshot':'1'}}
output.write_text(json.dumps(manifest,indent=2)+'\n')
PY
(cd "$work" && sha256sum "$artifact" > SHA256SUMS)
# Keep partial artifacts private until packaging has completed successfully.
publish=$(mktemp -d /artifacts/.dia-package.XXXXXX)
for file in "$artifact" footprint.json SHA256SUMS; do
  cp "$work/$file" "$publish/$file"
  chown "$owner_uid:$owner_gid" "$publish/$file"
  chmod 644 "$publish/$file"
  # Same-filesystem hard-link publication fails atomically if the name exists.
  ln -- "$publish/$file" "/artifacts/$file"
done
printf 'Packaged %s\n' "$artifact"
CONTAINER
