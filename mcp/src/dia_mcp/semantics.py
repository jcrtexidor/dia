"""Portable, read-only analysis of bounded live summaries and native attachments.

Pass a list of get_object ``object`` values and an object-id mapping of
get_connections results. Completeness applies only to this supplied subgraph;
callers must report paging/truncation separately. Sheets are never treated as
exclusive domains. Geometry, captions and visual touching cannot establish edges.
"""

import math
from collections import Counter

from .native.uml import superclass_endpoints

DOMAINS = ("flowchart", "uml", "database", "network", "electrical", "pneumatic")
_PREFIXES = {
    "Flowchart - ": "flowchart",
    "UML - ": "uml",
    "Database - ": "database",
    "Network - ": "network",
    "Cisco - ": "network",
    "Electric - ": "electrical",
    "Circuit - ": "electrical",
    "Pneum - ": "pneumatic",
}


def analyze_graph(objects, connections, domain="auto"):
    """Return evidence and findings for at most 500 objects/20,000 attachments.

    ``domain`` selects domain findings, not classification or native connectivity.
    Unknown/custom types remain unknown even when placed on a familiar sheet.
    Generic components include connector objects. Isolated objects are observations,
    not errors: labels and decoration are legitimate disconnected objects.
    """
    if domain not in ("auto", *DOMAINS):
        raise ValueError("unsupported semantic domain")
    if not isinstance(objects, list) or len(objects) > 500:
        raise ValueError("semantic analysis requires at most 500 objects")
    if not isinstance(connections, dict):
        raise ValueError("connections must map object IDs to native summaries")
    indexed = {}
    evidence = []
    for obj in objects:
        oid = obj.get("object_id")
        if not isinstance(oid, str) or not oid or oid in indexed:
            raise ValueError("objects require unique object_id strings")
        indexed[oid] = obj
        kind = obj.get("type", "")
        detected = next((d for p, d in _PREFIXES.items() if kind.startswith(p)), "unknown")
        evidence.append(
            {
                "object_id": oid,
                "type": kind,
                "domain": detected,
                "basis": "native_type_prefix" if detected != "unknown" else "unknown",
                "evidence_level": "heuristic" if detected != "unknown" else "unknown",
            }
        )
    domains = sorted({e["domain"] for e in evidence if e["domain"] != "unknown"})
    unknown = [e["object_id"] for e in evidence if e["domain"] == "unknown"]
    classification = (
        "mixed"
        if len(domains) > 1 or (domains and unknown)
        else domains[0]
        if domains
        else "unknown"
    )
    adjacency = {oid: set() for oid in indexed}
    external = set()
    count = 0
    missing = sorted(set(indexed) - set(connections))
    findings = []
    for oid, obj in indexed.items():
        summary = connections.get(oid, {})
        handles = summary.get("handles", [])
        points = summary.get("connection_points", [])
        if len(handles) + len(points) > 2048:
            raise ValueError("object exceeds semantic structure budget")
        targets = [h["attached_to"].get("object_id") for h in handles if h.get("attached_to")]
        for cp in points:
            targets.extend(cp.get("connected_objects", []))
            if len(targets) > 20000:
                raise ValueError("semantic analysis exceeds attachment budget")
        count += len(targets)
        if count > 20000:
            raise ValueError("semantic analysis exceeds attachment budget")
        for target in targets:
            if target in indexed:
                adjacency[oid].add(target)
                adjacency[target].add(oid)
            elif target is not None:
                external.add(target)
        if domain in ("auto", "uml") and obj.get("type") == "UML - Generalization":
            relation = superclass_endpoints(handles)
            if relation and all(
                indexed.get(ref, {}).get("type") == "UML - Class" for ref in relation.values()
            ):
                findings.append(
                    {
                        "code": "uml_generalization",
                        "object_id": oid,
                        **relation,
                        "basis": "native_type_and_attached_endpoint_ids",
                        "evidence_level": "derived_from_native",
                    }
                )
    components = []
    remaining = set(indexed)
    while remaining:
        todo = [min(remaining)]
        component = set()
        while todo:
            current = todo.pop()
            if current in component:
                continue
            component.add(current)
            todo.extend(adjacency[current] - component)
        remaining -= component
        components.append(sorted(component))
    isolated = sorted(oid for oid, neighbors in adjacency.items() if not neighbors)
    limitations = [
        "Connectivity reflects native attachments in the supplied subgraph only.",
        "Sheet membership and visual touching do not establish domain or connectivity.",
        "Isolated objects may be intentional labels or decoration.",
        "Electrical/pneumatic simulation and network reachability are not supported.",
    ]
    selected = domains if domain == "auto" else [domain]
    if "flowchart" in selected:
        limitations.append(
            "Directed flow cycles are not evaluated: live scalar summaries do not "
            "expose native arrow properties; handle order alone is not flow direction."
        )
    if "database" in selected:
        limitations.append(
            "Field/primary-key checks are not evaluated: live scalar summaries do "
            "not expose the Database Table attributes array."
        )
    return {
        "domain": domain,
        "classification": classification,
        "domains": domains,
        "evidence": evidence,
        "unknown_objects": unknown,
        "components": components,
        "isolated_objects": isolated,
        "findings": findings,
        "coverage": {
            "object_count": len(indexed),
            "missing_connections": missing,
            "external_objects": sorted(external),
            "scope": "supplied_subgraph",
        },
        "limitations": limitations,
        "evidence_levels": _evidence_levels(objects, connections, components, isolated, findings),
    }


def _evidence_levels(objects, connections, components, isolated, findings):
    """Separate observations, derivations and bounded hints; none is simulation."""
    boxes, missing_bounds = [], []
    layers, groups = Counter(), Counter()
    unknown_layers = []
    unattached, unattached_count = [], 0
    for obj in objects:
        oid = obj["object_id"]
        if isinstance(obj.get("layer_id"), str):
            layers[obj["layer_id"]] += 1
        else:
            unknown_layers.append(oid)
        if isinstance(obj.get("group_id"), str):
            groups[obj["group_id"]] += 1
        bounds = obj.get("bounds")
        if (
            isinstance(bounds, dict)
            and all(
                type(bounds.get(k)) in (int, float)
                and abs(bounds[k]) <= 1_000_000
                and math.isfinite(bounds[k])
                for k in ("left", "top", "right", "bottom")
            )
            and bounds["left"] <= bounds["right"]
            and bounds["top"] <= bounds["bottom"]
        ):
            boxes.append((oid, bounds))
        else:
            missing_bounds.append(oid)
        for handle in connections.get(oid, {}).get("handles", []):
            if (
                type(handle.get("connect_type")) is int
                and handle["connect_type"] in (1, 2)
                and "attached_to" in handle
                and handle["attached_to"] is None
            ):
                unattached_count += 1
                if len(unattached) < 64:
                    unattached.append(
                        {
                            "object_id": oid,
                            "handle_index": handle.get("index"),
                            "handle_id": handle.get("id"),
                        }
                    )
    overlaps, overlap_count = [], 0
    for i, (aid, a) in enumerate(boxes):
        for bid, b in boxes[i + 1 :]:
            if max(a["left"], b["left"]) < min(a["right"], b["right"]) and max(
                a["top"], b["top"]
            ) < min(a["bottom"], b["bottom"]):
                overlap_count += 1
                if len(overlaps) < 64:
                    overlaps.append(
                        {"object_ids": [aid, bid], "basis": "positive_bbox_intersection"}
                    )
    return {
        "native_facts": {
            "layer_object_counts": dict(sorted(layers.items())),
            "group_member_counts": dict(sorted(groups.items())),
            "unknown_layer_objects": unknown_layers,
            "scope": "supplied_objects_only; group counts include supplied members only",
        },
        "derived_structure": {
            "basis": "native_attachments_in_supplied_subgraph",
            "component_count": len(components),
            "isolated_object_count": len(isolated),
            "supported_relationship_count": len(findings),
        },
        "heuristics": {
            "bbox_overlaps": {
                "items": overlaps,
                "total": overlap_count,
                "truncated": overlap_count > 64,
                "missing_or_invalid_bounds": missing_bounds,
                "meaning": "Bounding-box overlap only; not collision, touching, or connectivity.",
            },
            "unattached_connectable_handles": {
                "items": unattached,
                "total": unattached_count,
                "truncated": unattached_count > 64,
                "meaning": "Native connect_type 1/2 without attachment; may be intentional. "
                "No two-ended connector or missing-edge inference.",
            },
            "domain_classification": "Native type prefix suggests domain; sheets are nonexclusive.",
        },
    }
