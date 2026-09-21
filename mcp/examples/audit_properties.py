#!/usr/bin/env python3
"""Audit installed factories in disposable normal-startup Dia workers.

Run under Xvfb in the built image with the source package on PYTHONPATH. No
property value is fetched. Each batch has a private HOME; abnormal worker exits
are isolated by retrying each factory in that batch, never in the user's GUI.
"""

import argparse
import collections
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from dia_mcp.property_policy import classify_property

# Trusted local startup hook only: neither installed nor exposed by the MCP API.
HOOK = r"""
import json
import os
from pathlib import Path
import dia
from gi.repository import GLib

def audit():
    request = json.loads(Path(os.environ["DIA_PROPERTY_AUDIT_REQUEST"]).read_text())
    response = Path(os.environ["DIA_PROPERTY_AUDIT_RESPONSE"])
    types = dia.registered_types()
    if request["action"] == "catalog":
        result = {"types": sorted(types), "dia_version": getattr(dia, "application_version", None)}
    elif request["action"] == "group":
        member, _, _ = types["Standard - Box"].create(0, 0)
        group = dia.group_create([member])
        result = {"type": "Group", "construction": "dia.group_create([Standard - Box])",
                  "status": "ok", **group.property_descriptors(256)}
    else:
        result = {"objects": []}
        retained = []
        for name in request["types"]:
            try:
                obj, _, _ = types[name].create(0, 0)
                retained.append(obj)
                descriptors = obj.property_descriptors(256)
                result["objects"].append({"type": name, "status": "ok", **descriptors})
            except Exception as exc:
                result["objects"].append({"type": name, "status": "failed",
                                          "error": type(exc).__name__ + ": " + str(exc)[:500]})
    response.write_text(json.dumps(result, ensure_ascii=False, default=str))
    os._exit(0)

GLib.idle_add(audit)
"""


def worker(binary, request, timeout):
    with tempfile.TemporaryDirectory(prefix="dia-property-audit-") as directory:
        root = Path(directory)
        plugin = root / ".dia/python"
        plugin.mkdir(parents=True)
        (plugin / "property_audit.py").write_text(HOOK)
        input_path, output = root / "input.json", root / "output.json"
        input_path.write_text(json.dumps(request))
        env = {
            **os.environ,
            "HOME": str(root),
            "DIA_MCP_LIVE": "0",
            "DIA_PROPERTY_AUDIT_REQUEST": str(input_path),
            "DIA_PROPERTY_AUDIT_RESPONSE": str(output),
        }
        env.pop("DIA_PYTHON_PATH", None)
        started = time.monotonic()
        try:
            process = subprocess.run(
                [binary, "--nosplash"], env=env, capture_output=True, timeout=timeout
            )
            code = process.returncode
            error = process.stderr.decode(errors="replace")[-1500:] if code else None
        except subprocess.TimeoutExpired:
            code, error = None, "worker timed out"
        record = {"returncode": code, "elapsed_seconds": round(time.monotonic() - started, 3)}
        if code == 0 and output.exists():
            return json.loads(output.read_text()), record
        return None, {**record, "error": error or "worker produced no response"}


def audit(binary, batch_size, timeout):
    catalog, catalog_worker = worker(binary, {"action": "catalog"}, timeout)
    if catalog is None:
        raise RuntimeError(f"Catalog worker failed: {catalog_worker}")
    names, rows, workers = catalog["types"], [], [catalog_worker]
    for offset in range(0, len(names), batch_size):
        batch = names[offset : offset + batch_size]
        result, run = worker(binary, {"action": "describe", "types": batch}, timeout)
        workers.append({**run, "factory_count": len(batch)})
        if result is not None:
            rows.extend(result["objects"])
        else:
            for name in batch:
                retry, run = worker(binary, {"action": "describe", "types": [name]}, timeout)
                workers.append({**run, "factory_count": 1, "isolated_retry": True})
                rows.extend(
                    retry["objects"]
                    if retry
                    else [
                        {
                            "type": name,
                            "status": "failed",
                            "error": run.get("error"),
                            "returncode": run["returncode"],
                        }
                    ]
                )
    group, group_worker = worker(binary, {"action": "group"}, timeout)
    workers.append({**group_worker, "action": "supplemental_group"})
    if group:
        for descriptor in group["items"]:
            descriptor["classification"] = classify_property(descriptor)["classification"]
    by_kind, categories = collections.Counter(), collections.Counter()
    for row in rows:
        for descriptor in row.get("items", []):
            policy = classify_property(descriptor)
            descriptor["classification"] = policy["classification"]
            by_kind[descriptor["type"]] += 1
            categories[policy["classification"]] += 1
    source = Path("/src/dia")
    if not (source / "lib/properties.h").exists():
        source = Path(__file__).resolve().parents[2]
    evidence_paths = [
        "plug-ins/python/pydia-object.c",
        "plug-ins/python/pydia-property.c",
        "plug-ins/python/pydia-live.c",
        "lib/properties.h",
    ]
    return {
        "schema_version": 1,
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source),
        "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        "image_id": os.environ.get("DIA_PROPERTY_AUDIT_IMAGE", "unspecified"),
        "method": "disposable_normal_startup_factories_descriptor_only",
        "binary": binary,
        "dia_version": catalog.get("dia_version"),
        "property_values_fetched": False,
        "property_writes_attempted": False,
        "descriptor_limit": 256,
        "descriptor_flags": {
            "visible": "PROP_FLAG_VISIBLE",
            "load_only": "PROP_FLAG_LOAD_ONLY | PROP_FLAG_WIDGET_ONLY",
        },
        "kind_policy": {
            kind: classify_property({"type": kind, "visible": True, "load_only": False})
            for kind in sorted(set(by_kind) | {d["type"] for d in (group or {}).get("items", [])})
        },
        "source_sha256": {
            p: hashlib.sha256((source / p).read_bytes()).hexdigest()
            for p in evidence_paths
            if (source / p).exists()
        },
        "summary": {
            "registered_factories": len(names),
            "attempted_factories": len(rows),
            "successful_factories": sum(r["status"] == "ok" for r in rows),
            "failed_factories": sum(r["status"] != "ok" for r in rows),
            "truncated_factories": sum(bool(r.get("truncated")) for r in rows),
            "descriptor_count": sum(by_kind.values()),
            "descriptor_kinds": dict(sorted(by_kind.items())),
            "classifications": dict(sorted(categories.items())),
        },
        "supplemental_probes": [
            group or {"type": "Group", "status": "failed", "error": group_worker.get("error")}
        ],
        "workers": workers,
        "factories": sorted(rows, key=lambda row: row["type"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="/opt/dia/bin/dia")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 64 or not 1 <= args.timeout <= 120:
        parser.error("batch-size must be 1..64 and timeout 1..120 seconds")
    result = audit(args.binary, args.batch_size, args.timeout)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], sort_keys=True))
    return int(
        bool(result["summary"]["failed_factories"] or result["summary"]["truncated_factories"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
