#!/usr/bin/env python3
"""Validate a local release manifest; stdlib only and never publishes artifacts."""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

DOCS = (
    "docs/installation.md",
    "docs/user-guide.md",
    "docs/mcp-tools.md",
    "docs/mcp-development.md",
    "docs/mcp-architecture.md",
    "docs/troubleshooting.md",
    "docs/security.md",
    "docs/release-validation.md",
    "docs/user-acceptance.md",
)
CHECKS = {"portable", "image_build", "native", "wayland", "install"}
VERSIONS = {
    "native": "0.98.0",
    "adapter": "0.3.0",
    "live": 1,
    "snapshot": "1",
    "package": "0.98.0+mcp0.3.0-1",
}


class InvalidRelease(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidRelease(message)


def constant(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise InvalidRelease(f"Missing {name} in {path}")


def source_versions(root):
    adapter = tomllib.loads((root / "mcp/pyproject.toml").read_text())["project"][
        "version"
    ]
    require(
        adapter == constant(root / "mcp/src/dia_mcp/__init__.py", "__version__"),
        "Adapter versions disagree",
    )
    lock = tomllib.loads((root / "mcp/uv.lock").read_text())
    local = [
        package
        for package in lock.get("package", [])
        if package.get("name") == "dia-operations-mcp"
    ]
    require(
        len(local) == 1
        and local[0].get("version") == adapter
        and local[0].get("source") == {"editable": "."},
        "uv.lock local adapter version/source disagree",
    )
    match = re.search(
        r"version:\s*['\"]([^'\"]+)['\"]", (root / "meson.build").read_text()
    )
    require(match is not None, "Missing native Meson version")
    model = (root / "mcp/src/dia_mcp/models.py").read_text()
    snapshot = re.search(r'api_version:\s*Literal\["([^"]+)"\]', model)
    require(snapshot is not None, "Missing snapshot protocol version")
    live = constant(root / "mcp/src/dia_mcp/live/protocol.py", "VERSION")
    versions = {
        "native": match[1],
        "adapter": adapter,
        "live": live,
        "snapshot": snapshot[1],
        "package": f"{match[1]}+mcp{adapter}-1",
    }
    require(
        versions == VERSIONS and type(live) is int,
        f"Unexpected release versions: {versions}",
    )
    return versions


def documentation(root):
    """Check local targets only in the explicit integration documentation list.

    Remote HTTP URLs and fragment IDs are not fetched or claimed verified.
    Inline code and fenced examples are excluded from Markdown link parsing.
    """
    for relative in DOCS:
        document = root / relative
        require(document.is_file(), f"Missing release documentation: {relative}")
        text = document.read_text()
        text = re.sub(r"(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$", "", text)
        text = re.sub(r"`[^`\n]*`", "", text)
        targets = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)", text)
        targets += re.findall(r"(?m)^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", text)
        for target in targets:
            target = target.strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target_path = unquote(parsed.path)
            resolved = (document.parent / target_path).resolve()
            require(
                resolved.is_relative_to(root.resolve()),
                f"Documentation link escapes repository: {relative}: {target}",
            )
            require(resolved.exists(), f"Broken local link: {relative}: {target}")
    return list(DOCS)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_file(directory, name):
    require(
        isinstance(name, str)
        and bool(name)
        and Path(name).name == name
        and name not in {".", ".."},
        f"Unsafe artifact name: {name!r}",
    )
    path = directory / name
    require(
        not path.is_symlink() and path.is_file(), f"Missing/unsafe release file: {name}"
    )
    return path


def check_records(records, directory):
    require(
        isinstance(records, list) and all(isinstance(r, dict) for r in records),
        "checks must be a list of records",
    )
    require(
        len(records) == len(CHECKS) and {r.get("name") for r in records} == CHECKS,
        "Exactly portable/image_build/native/wayland/install checks are required",
    )
    for record in records:
        name, status = record["name"], record.get("status")
        require(status in {"passed", "skipped"}, f"Release check did not pass: {name}")
        if status == "skipped":
            require(
                name == "wayland" and bool(record.get("reason")),
                "Only Wayland may be skipped, with an explicit reason",
            )
        else:
            require(
                local_file(directory, record.get("log")).stat().st_size > 0,
                f"Empty validation log: {name}",
            )


def validate(root, directory, manifest):
    require(isinstance(manifest, dict), "Manifest must be an object")
    require(
        type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
        "Unsupported manifest schema",
    )
    require(
        manifest.get("versions") == source_versions(root),
        "Manifest/source version mismatch",
    )
    require(
        manifest.get("documentation") == documentation(root),
        "Documentation inventory mismatch",
    )
    check_records(manifest.get("checks"), directory)
    require(
        type(manifest["versions"]["live"]) is int,
        "Live protocol version must be an integer",
    )
    image = manifest.get("image", {})
    require(isinstance(image, dict), "Image metadata must be an object")
    require(
        isinstance(image.get("reference"), str) and bool(image["reference"]),
        "Missing build image reference",
    )
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", image.get("id", "")) is not None,
        "Missing immutable build image digest",
    )
    artifacts = manifest.get("artifacts")
    require(
        isinstance(artifacts, list) and len(artifacts) == 1,
        "Exactly one .deb artifact is required",
    )
    artifact = artifacts[0]
    require(isinstance(artifact, dict), "Artifact metadata must be an object")
    expected = f"dia-mcp-fork_{manifest['versions']['package']}_amd64.deb"
    require(
        artifact.get("name") == expected,
        "Unexpected package name, version or architecture",
    )
    package = local_file(directory, artifact["name"])
    require(
        type(artifact.get("bytes")) is int
        and artifact["bytes"] > 0
        and artifact["bytes"] == package.stat().st_size,
        "Package size mismatch",
    )
    require(artifact.get("sha256") == digest(package), "Package SHA256 mismatch")
    sums = local_file(directory, "SHA256SUMS").read_text().splitlines()
    require(
        f"{artifact['sha256']}  {artifact['name']}" in sums,
        "SHA256SUMS does not contain the verified package",
    )
    for line in sums:
        require(
            re.fullmatch(r"[0-9a-f]{64}  [^/\\]+", line) is not None,
            "Malformed SHA256SUMS entry",
        )
        expected_hash, filename = line.split("  ", 1)
        require(
            digest(local_file(directory, filename)) == expected_hash,
            f"Checksum manifest mismatch: {filename}",
        )
    smoke = json.loads(local_file(directory, "install-smoke.json").read_text())
    require(isinstance(smoke, dict), "Fresh install smoke must be an object")
    require(smoke.get("status") == "passed", "Fresh install smoke did not pass")
    require(
        smoke.get("versions") == manifest["versions"], "Fresh install version mismatch"
    )
    return {
        "status": "validated",
        "published": False,
        "skipped_checks": [
            r["name"] for r in manifest["checks"] if r["status"] == "skipped"
        ],
        "artifacts": artifacts,
    }


def create(root, directory, checks, image, image_id):
    versions = source_versions(root)
    packages = list(directory.glob("*.deb"))
    require(len(packages) == 1, "Release directory must contain exactly one .deb")
    package = local_file(directory, packages[0].name)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "versions": versions,
        "documentation": documentation(root),
        "source": {
            "revision": revision.stdout.strip() or None,
            "dirty": bool(dirty.stdout) if dirty.returncode == 0 else None,
        },
        "image": {"reference": image, "id": image_id},
        "checks": checks,
        "artifacts": [
            {
                "name": package.name,
                "bytes": package.stat().st_size,
                "sha256": digest(package),
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--image")
    parser.add_argument("--image-id")
    args = parser.parse_args()
    manifest_path = args.output / "release-manifest.json"
    try:
        if args.create:
            require(
                args.checks is not None and args.image and args.image_id,
                "--create requires --checks, --image and --image-id",
            )
            manifest = create(
                args.root,
                args.output,
                json.loads(args.checks.read_text()),
                args.image,
                args.image_id,
            )
        else:
            manifest = json.loads(manifest_path.read_text())
        result = validate(args.root, args.output, manifest)
        if args.create:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    except (InvalidRelease, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
