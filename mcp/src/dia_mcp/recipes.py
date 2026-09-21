"""Small semantic recipes producing ordinary live create commands, without mutation.

Labels use descriptor names verified in the bundled native object implementations.
Runtime catalog/descriptor validation still governs availability and writability.
There are no synthetic ports or speculative diagram-language relationships here.
"""

import math

from .native.catalog import xml_text

_DEFAULTS = {
    "flowchart": "Flowchart - Box",
    "uml": "UML - Class",
    "database": "Database - Table",
    "network": "Network - Base Station",
}
_LABELS = {
    "Flowchart - Box": ("flowchart", "text"),
    "Flowchart - Ellipse": ("flowchart", "text"),
    "Flowchart - Diamond": ("flowchart", "text"),
    "UML - Class": ("uml", "name"),
    "Database - Table": ("database", "name"),
    "Network - Base Station": ("network", "text"),
    "Network - Radio Cell": ("network", "text"),
}


def plan_native(domain, nodes):
    """Plan 1..64 native objects from type/x/y/label dictionaries.

    Type defaults to a verified domain factory, label defaults to empty, and x/y
    are required centimeters. Returned commands can be supplied unchanged to the
    generic live transaction API after review. This is a creation plan only:
    inspect returned live IDs and native endpoints before a separate connection
    transaction. No DB field/PK, protocol, simulation or UML member inference.
    """
    if domain not in _DEFAULTS:
        raise ValueError("recipe domain must be flowchart, uml, database, or network")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 64:
        raise ValueError("recipe requires 1..64 nodes")
    commands = []
    for node in nodes:
        if (
            not isinstance(node, dict)
            or not {"x", "y"} <= node.keys()
            or node.keys() - {"type", "x", "y", "label"}
        ):
            raise ValueError("recipe nodes require x/y and optional type/label")
        kind = node.get("type", _DEFAULTS[domain])
        if not isinstance(kind, str) or kind not in _LABELS or _LABELS[kind][0] != domain:
            raise ValueError("type lacks a verified recipe for the requested domain")
        for key in ("x", "y"):
            value = node[key]
            if (
                type(value) not in (int, float)
                or abs(value) > 1_000_000
                or not math.isfinite(value)
            ):
                raise ValueError("coordinates must be finite centimeters within native limits")
        label = xml_text(node.get("label", ""))
        if len(label) > 2048:
            raise ValueError("label exceeds native scalar property limit")
        commands.append(
            {
                "op": "create",
                "type": kind,
                "x": node["x"],
                "y": node["y"],
                "properties": {_LABELS[kind][1]: label},
            }
        )
    return {
        "domain": domain,
        "mutates": False,
        "commands": commands,
        "affected_existing": [],
        "objects_to_create": [dict(command) for command in commands],
        "assumptions": [
            "Factories and label descriptors must exist in the target live installation.",
            "Caller supplies current document generation and a separately prepared receipt.",
            "Runtime IDs are assigned only after native creation commits.",
        ],
        "unsupported_semantics": [
            "No ports, relationships, domain validity or simulation are inferred.",
            "Compound UML members and database fields are outside scalar creation recipes.",
        ],
        "expected_structural_effect": {
            "created_objects": len(commands),
            "deleted_objects": 0,
            "explicit_attachment_changes": 0,
            "description": "Create independent native objects with scalar labels.",
        },
        "followup": [
            "Inspect the live catalog for required native factories and property descriptors.",
            "Apply commands through a prepared generic transaction at the observed generation.",
            "Read created live object IDs from the transaction result; inspect native handles "
            "and connection points before planning attachments.",
            "Create connector objects separately and connect using inspected native indices; "
            "this plan does not guess ports, arrow direction or relationships.",
        ],
        "limitations": [
            "Labels and node creation only; no automatic edges or layout.",
            "Database attributes/primary keys and UML members require compound-property support.",
            "Network objects are diagram symbols, not verified reachability or configuration.",
        ],
    }
