"""Inert selection plans composed exclusively from existing generic commands."""

import math

from ..errors import DiaError
from ..property_policy import classify_property
from .protocol import validate_commands

LAYOUT_MODES = frozenset(
    {
        "left",
        "center",
        "right",
        "top",
        "middle",
        "bottom",
        "distribute_horizontal",
        "distribute_vertical",
    }
)


def _coordinate(value):
    return type(value) in (int, float) and abs(value) <= 1_000_000 and math.isfinite(value)


def plan_selection(objects, intent, options):
    """Plan layout, move-by-delta or bulk named scalar updates for 1..64 objects.

    Inputs are observed object summaries. The caller binds session/document/G and
    must disclose selection truncation before invoking this function. No receipt,
    native object or document is created. Missing descriptors remain an explicit
    pending check; available negative descriptor evidence rejects property plans.
    """
    if not isinstance(objects, list) or not 1 <= len(objects) <= 64:
        raise ValueError("selection plan requires 1..64 objects")
    if not isinstance(options, dict):
        raise ValueError("plan options must be an object")
    expected = {"layout": {"mode"}, "move": {"dx", "dy"}, "set_properties": {"properties"}}
    if not isinstance(intent, str) or intent not in expected or set(options) != expected[intent]:
        raise ValueError("unsupported intent or invalid plan options")
    ids = []
    for obj in objects:
        if not isinstance(obj, dict):
            raise ValueError("selection objects must be summaries")
        oid = obj.get("object_id")
        if not isinstance(oid, str) or not 1 <= len(oid) <= 256 or oid in ids:
            raise ValueError("selection requires distinct bounded object IDs")
        if obj.get("group_id") is not None:
            raise ValueError("group members are not generic top-level mutation targets")
        ids.append(oid)
    assumptions = [
        "Caller binds this observed selection to its session, document and generation.",
        "Selection must be complete; replan after a generation or runtime identity change.",
        "Native validation, capability and transaction checks still apply at execution.",
        "Affected IDs are explicit targets; native attached geometry may also update.",
    ]
    if intent == "layout":
        if (
            len(ids) < 2
            or not isinstance(options["mode"], str)
            or options["mode"] not in LAYOUT_MODES
        ):
            raise ValueError("layout requires 2..64 objects and a native layout mode")
        commands = [{"op": "layout", "object_ids": ids.copy(), "mode": options["mode"]}]
        effect = "Native layout updates target positions and dependent connection geometry."
    elif intent == "move":
        if not all(_coordinate(options[key]) for key in ("dx", "dy")):
            raise ValueError("move deltas must be finite bounded centimeters")
        commands = []
        for obj in objects:
            pos = obj.get("position")
            if not isinstance(pos, dict) or not all(
                _coordinate(pos.get(key)) for key in ("x", "y")
            ):
                raise ValueError("move requires observed finite object positions")
            x, y = pos["x"] + options["dx"], pos["y"] + options["dy"]
            if not _coordinate(x) or not _coordinate(y):
                raise ValueError("planned position exceeds native coordinate bounds")
            commands.append({"op": "move", "object_id": obj["object_id"], "x": x, "y": y})
        effect = "Native move updates target positions and dependent connection geometry."
    else:
        properties = options["properties"]
        if not isinstance(properties, dict) or not properties:
            raise ValueError("property plan requires nonempty named scalar properties")
        commands = [
            {"op": "set_properties", "object_id": oid, "properties": properties.copy()}
            for oid in ids
        ]
        for obj in objects:
            observed = obj.get("properties")
            if not isinstance(observed, dict):
                continue
            descriptors = {p.get("name"): p for p in observed.get("items", [])}
            for name in properties:
                desc = descriptors.get(name)
                editable = desc.get("editable") if desc is not None else None
                if desc is not None and "load_only" in desc:
                    editable = classify_property(desc)["editable"]
                if editable is False:
                    raise ValueError(
                        "property is not editable on every selected object: " + str(name)
                    )
                if desc is None and observed.get("truncated") is False:
                    raise ValueError("property is absent on a selected object: " + str(name))
        assumptions.append(
            "Property existence/editability, enum choices and ranges need native "
            "validation wherever complete descriptor evidence is unavailable."
        )
        effect = "Native property updates may resize objects and update dependent geometry."
    try:
        validate_commands(commands)
    except DiaError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "mutates": False,
        "intent": intent,
        "commands": commands,
        "affected_existing": ids.copy(),
        "objects_to_create": [],
        "assumptions": assumptions,
        "unsupported_semantics": [
            "No domain-specific validity or simulation is inferred.",
            "Layer reassignment is not supported by the generic command ABI.",
        ],
        "expected_structural_effect": {
            "created_objects": 0,
            "deleted_objects": 0,
            "explicit_attachment_changes": 0,
            "target_count": len(ids),
            "description": effect,
        },
    }
