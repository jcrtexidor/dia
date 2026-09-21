"""Release guard regressions without Docker, network or installation privileges."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "build-aux/mcp/validate-release.py"
spec = importlib.util.spec_from_file_location("release_validation", MODULE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def candidate(tmp_path):
    root, output = tmp_path / "source", tmp_path / "artifacts"
    root.mkdir()
    output.mkdir()

    def write(relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    write("meson.build", "project('dia', version: '0.98.0')\n")
    write("mcp/pyproject.toml", '[project]\nversion = "0.3.0"\n')
    write("mcp/src/dia_mcp/__init__.py", '__version__ = "0.3.0"\n')
    write(
        "mcp/uv.lock",
        '[[package]]\nname = "dia-operations-mcp"\n'
        'version = "0.3.0"\nsource = { editable = "." }\n',
    )
    write("mcp/src/dia_mcp/live/protocol.py", "VERSION = 1\n")
    write("mcp/src/dia_mcp/models.py", 'api_version: Literal["1"] = "1"\n')
    for document in release.DOCS:
        write(document, "# Release guide\n[Install](installation.md#local)\n")
    filename = "dia-mcp-fork_0.98.0+mcp0.3.0-1_amd64.deb"
    package = output / filename
    package.write_bytes(b"synthetic package bytes for checksum guard")
    (output / "SHA256SUMS").write_text(f"{release.digest(package)}  {filename}\n")
    (output / "install-smoke.json").write_text(
        json.dumps({"status": "passed", "versions": release.VERSIONS})
    )
    checks = []
    for name in sorted(release.CHECKS):
        (output / f"{name}.log").write_text("Verification completed\n")
        checks.append({"name": name, "status": "passed", "log": f"{name}.log"})
    manifest = {
        "schema_version": 1,
        "versions": copy.deepcopy(release.VERSIONS),
        "documentation": list(release.DOCS),
        "image": {"reference": "dia:test", "id": "sha256:" + "a" * 64},
        "checks": checks,
        "artifacts": [
            {"name": filename, "bytes": package.stat().st_size, "sha256": release.digest(package)}
        ],
    }
    return root, output, manifest


def test_complete_candidate_is_local_only(candidate):
    result = release.validate(*candidate)
    assert result["status"] == "validated" and result["published"] is False
    assert result["skipped_checks"] == []


def test_only_wayland_can_be_explicitly_skipped(candidate):
    root, output, manifest = candidate
    record = next(record for record in manifest["checks"] if record["name"] == "wayland")
    record.update(status="skipped", reason="No real compositor socket")
    assert release.validate(root, output, manifest)["skipped_checks"] == ["wayland"]
    record.pop("reason")
    with pytest.raises(release.InvalidRelease, match="Wayland"):
        release.validate(root, output, manifest)
    record.update(name="install", reason="Skip native install")
    with pytest.raises(release.InvalidRelease):
        release.validate(root, output, manifest)


@pytest.mark.parametrize(
    "boundary",
    [
        "failed",
        "missing",
        "empty_log",
        "checksum",
        "size",
        "version",
        "smoke",
        "digest",
        "path",
        "symlink",
    ],
)
def test_release_rejects_unverified_or_changed_artifacts(candidate, boundary):
    root, output, manifest = candidate
    artifact = manifest["artifacts"][0]
    package = output / artifact["name"]
    if boundary == "failed":
        manifest["checks"][0]["status"] = "failed"
    elif boundary == "missing":
        manifest["checks"].pop()
    elif boundary == "empty_log":
        (output / manifest["checks"][0]["log"]).write_text("")
    elif boundary == "checksum":
        package.write_bytes(b"X" * artifact["bytes"])
    elif boundary == "size":
        artifact["bytes"] += 1
    elif boundary == "version":
        manifest["versions"]["adapter"] = "0.2.0"
    elif boundary == "smoke":
        (output / "install-smoke.json").write_text('{"status":"failed"}')
    elif boundary == "digest":
        manifest["image"]["id"] = "mutable:latest"
    elif boundary == "path":
        manifest["checks"][0]["log"] = "../outside.log"
    elif boundary == "symlink":
        payload = output.parent / "package.deb"
        package.rename(payload)
        package.symlink_to(payload)
    with pytest.raises(release.InvalidRelease):
        release.validate(root, output, manifest)


def test_checksum_sidecar_cannot_reference_outside_directory(candidate):
    root, output, manifest = candidate
    with (output / "SHA256SUMS").open("a") as stream:
        stream.write("a" * 64 + "  ../secret\n")
    with pytest.raises(release.InvalidRelease, match="Malformed"):
        release.validate(root, output, manifest)


def test_documentation_scope_local_links_and_examples(candidate):
    root, output, manifest = candidate
    # Historical upstream docs are intentionally outside the integration gate.
    (root / "old-upstream.md").write_text("[Old](absent.md)")
    guide = root / release.DOCS[0]
    guide.write_text("""# Install
[Guide](user-guide.md)
[Website](https://example.invalid/not-fetched)
```sh
[example](not-a-link.md)
```
`[inline](not-a-link.md)`
""")
    release.validate(root, output, manifest)
    guide.write_text("[Broken](missing.md)")
    with pytest.raises(release.InvalidRelease, match="Broken local link"):
        release.validate(root, output, manifest)
    guide.write_text("[Escape](../../private.md)")
    with pytest.raises(release.InvalidRelease, match="escapes"):
        release.validate(root, output, manifest)


def test_source_version_files_must_agree(candidate):
    root, output, manifest = candidate
    (root / "mcp/src/dia_mcp/__init__.py").write_text('__version__ = "0.2.0"\n')
    with pytest.raises(release.InvalidRelease, match="versions disagree"):
        release.validate(root, output, manifest)


def test_lockfile_adapter_version_must_match(candidate):
    root, output, manifest = candidate
    lock = root / "mcp/uv.lock"
    lock.write_text(lock.read_text().replace('"0.3.0"', '"0.2.0"'))
    with pytest.raises(release.InvalidRelease, match="uv.lock"):
        release.validate(root, output, manifest)
