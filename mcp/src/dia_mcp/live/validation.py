"""Bounded, descriptor-only preflight; never execute native commands as a probe.

``valid`` means no known static rejection. ``complete`` is false when checks
require a factory, setter, native implementation, or intermediate batch state.
The native transaction remains authoritative even after a valid preview.
"""

import math

from ..errors import DiaError
from .protocol import validate_commands

ISSUE_LIMIT = 64
ALTERNATIVE_LIMIT = 12
PROPERTY_TYPES = frozenset({"bool", "int", "enum", "real", "length", "fontsize", "string", "text"})
LAYOUT_MODES = (
    "left",
    "center",
    "right",
    "top",
    "middle",
    "bottom",
    "distribute_horizontal",
    "distribute_vertical",
)


def _text(value):
    return str(value)[:512]


def _utf8(value):
    if not isinstance(value, str) or "\0" in value:
        return False
    try:
        value.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


class _Validation:
    def __init__(self, registry, doc, doc_id, objects):
        self.registry, self.doc, self.doc_id, self.objects = registry, doc, doc_id, objects
        self.issues, self.deferred = [], []
        self.issue_count = self.deferred_count = 0
        self.deleted = set()
        self.descriptors = {}
        self.types = None
        self.layers = {registry._layer_id(doc_id, layer) for layer in doc.layers}
        self.top_level = sorted(oid for oid, entry in objects.items() if entry[2] is None)

    def issue(self, index, field, code, message, alternatives=(), *, source_complete=True):
        self.issue_count += 1
        if len(self.issues) >= ISSUE_LIMIT:
            return
        options = sorted(set(alternatives))
        self.issues.append(
            {
                "command_index": index,
                "field": field,
                "code": code,
                "message": _text(message),
                "alternatives": [
                    value if type(value) is int else _text(value)
                    for value in options[:ALTERNATIVE_LIMIT]
                ],
                "alternatives_total": len(options),
                "alternatives_truncated": len(options) > ALTERNATIVE_LIMIT or not source_complete,
                "alternatives_source_complete": source_complete,
            }
        )

    def defer(self, index, field, reason):
        self.deferred_count += 1
        if len(self.deferred) < ISSUE_LIMIT:
            self.deferred.append(
                {
                    "command_index": index,
                    "field": field,
                    "reason": _text(reason),
                    "authority": "native",
                }
            )

    def resolve(self, index, field, oid):
        try:
            self.registry._check_session(oid)
        except DiaError as exc:
            self.issue(index, field, exc.code, str(exc), self.top_level)
            return None
        if oid in self.deleted:
            self.issue(
                index, field, "REFERENCE_AFTER_DELETE", "An earlier command deletes this object"
            )
            return None
        if oid not in self.objects:
            self.issue(
                index,
                field,
                "STALE_OBJECT_REFERENCE",
                "Object is not a current member of this document",
                self.top_level,
            )
            return None
        obj, _, group = self.objects[oid]
        if group is not None:
            self.issue(
                index,
                field,
                "UNSUPPORTED_OPERATION",
                "Editing group members is unsupported; target a top-level object",
                self.top_level,
            )
            return None
        return obj

    def properties(self, index, obj, values):
        if not values:
            self.defer(index, "properties", "Native setter availability is not exposed")
            return
        if index:
            self.defer(
                index, "properties", "Descriptors after earlier commands require native state"
            )
            return
        key = id(obj)
        if key not in self.descriptors:
            self.descriptors[key] = obj.property_descriptors(256)
        report = self.descriptors[key]
        descriptors = {d["name"]: d for d in report["items"]}
        alternatives = [
            name
            for name, d in descriptors.items()
            if d["type"] in PROPERTY_TYPES
            and not d.get("load_only", False)
            and (d.get("visible", False) or d["type"] == "text")
        ]
        for name, value in values.items():
            field = f"properties.{name}"
            descriptor = descriptors.get(name)
            if descriptor is None:
                if report["truncated"]:
                    self.defer(
                        index, field, "Property may be beyond the descriptor inspection limit"
                    )
                else:
                    self.issue(
                        index, field, "UNKNOWN_PROPERTY", "Property does not exist", alternatives
                    )
                continue
            kind = descriptor["type"]
            if (
                kind not in PROPERTY_TYPES
                or descriptor.get("load_only", False)
                or not (descriptor.get("visible", False) or kind == "text")
            ):
                self.issue(
                    index,
                    field,
                    "UNSUPPORTED_PROPERTY",
                    "Property is unsupported or not writable by native live commands",
                    alternatives,
                    source_complete=not report["truncated"],
                )
                continue
            valid = True
            if kind == "bool":
                valid = type(value) is bool
            elif kind in {"int", "enum"}:
                valid = type(value) is int and -(2**31) <= value < 2**31
            elif kind in {"real", "length", "fontsize"}:
                valid = (
                    type(value) in (int, float) and abs(value) <= 1000000 and math.isfinite(value)
                )
            elif kind in {"string", "text"}:
                valid = _utf8(value)
            if not valid:
                self.issue(
                    index,
                    field,
                    "INVALID_PROPERTY_VALUE",
                    f"Expected a supported {kind} value",
                    alternatives,
                    source_complete=not report["truncated"],
                )
                continue
            if kind in {"enum", "int", "real", "length", "fontsize"}:
                self.defer(
                    index, field, "Native enum membership or descriptor range is not exposed"
                )
            else:
                self.defer(
                    index, field, "Property setter support and behavior remain native authority"
                )

    def ports(self, index, command, obj, target=None):
        if command["op"] == "connect" and command["object_id"] == command["target_id"]:
            self.issue(index, "target_id", "SELF_CONNECTION", "An object cannot connect to itself")
            return
        if index:
            self.defer(
                index, "ports", "Ports after earlier commands require native intermediate state"
            )
            return
        handles = obj.handles
        if len(handles) > self.registry.limits.structure:
            self.defer(index, "ports", "Handle list exceeds the inspection budget")
            return
        handle = command["handle"]
        if handle >= len(handles):
            self.issue(
                index,
                "handle",
                "INVALID_HANDLE",
                "Handle index is outside this object",
                range(len(handles)),
            )
        elif target is not None and handles[handle].connect_type == 0:
            self.issue(
                index,
                "handle",
                "NONCONNECTABLE_HANDLE",
                "Handle cannot connect",
                (i for i, h in enumerate(handles) if h.connect_type != 0),
            )
        if target is not None:
            points = target.connections
            if len(points) > self.registry.limits.structure:
                self.defer(index, "ports", "Connection point list exceeds the inspection budget")
                return
            if command["point"] >= len(points):
                self.issue(
                    index,
                    "point",
                    "INVALID_CONNECTION_POINT",
                    "Connection point index is outside the target",
                    range(len(points)),
                )
        self.defer(index, "ports", "Native connection callbacks remain authoritative")

    def command(self, index, command):
        try:
            validate_commands([command])
        except DiaError as exc:
            self.issue(index, "command", exc.code, str(exc))
            return
        # Native C consumers use UTF-8 strings. Reject names that could alias a
        # prefix through an embedded NUL, even if an older wire validator accepts it.
        for field, value in command.items():
            if isinstance(value, str) and not _utf8(value):
                self.issue(index, field, "INVALID_ARGUMENT", "Expected valid UTF-8 without NUL")
                return
        for name, value in command.get("properties", {}).items():
            if not _utf8(name) or (isinstance(value, str) and not _utf8(value)):
                self.issue(
                    index,
                    "properties",
                    "INVALID_ARGUMENT",
                    "Property names and strings require valid UTF-8 without NUL",
                )
                return
        op = command["op"]
        if op == "create":
            if self.types is None:
                self.types = self.registry.dia.registered_types()
            if command["type"] not in self.types:
                self.issue(
                    index,
                    "type",
                    "UNKNOWN_OBJECT_TYPE",
                    "Installed type does not exist",
                    self.types,
                )
            else:
                self.defer(
                    index,
                    "type",
                    "Factory availability, defaults and properties require native creation",
                )
            if "layer_id" in command and command["layer_id"] not in self.layers:
                self.issue(
                    index,
                    "layer_id",
                    "STALE_LAYER_REFERENCE",
                    "Layer is not in this document",
                    self.layers,
                )
            return
        if op == "layout":
            if command["mode"] not in LAYOUT_MODES:
                self.issue(
                    index, "mode", "INVALID_LAYOUT_MODE", "Unsupported layout mode", LAYOUT_MODES
                )
            for oid in command["object_ids"]:
                self.resolve(index, "object_ids", oid)
            self.defer(index, "layout", "Geometry and native layout execution are not simulated")
            return
        obj = self.resolve(index, "object_id", command["object_id"])
        target = None
        if op == "connect":
            target = self.resolve(index, "target_id", command["target_id"])
        if obj is None:
            return
        if op == "set_properties":
            self.properties(index, obj, command["properties"])
        elif op in {"connect", "disconnect"}:
            if op == "disconnect" or target is not None:
                self.ports(index, command, obj, target)
        elif op == "delete":
            if index:
                self.defer(
                    index,
                    "delete",
                    "Attachment/parent state after earlier commands is not simulated",
                )
            else:
                if obj.parent is not None or obj.children:
                    self.issue(
                        index,
                        "object_id",
                        "PARENTED_OBJECT",
                        "Deleting parented objects is unsupported",
                    )
                if any(h.connected_to is not None for h in obj.handles):
                    self.issue(
                        index,
                        "object_id",
                        "OBJECT_CONNECTED",
                        "Disconnect this object's handles before deletion",
                    )
                if any(cp.connected for cp in obj.connections):
                    self.issue(
                        index,
                        "object_id",
                        "OBJECT_CONNECTED",
                        "Disconnect incoming attachments before deletion",
                    )
            self.deleted.add(command["object_id"])
        elif op == "move":
            self.defer(
                index, "move", "Native move callback availability and behavior are not exposed"
            )

    def result(self, count):
        issues_truncated = self.issue_count > len(self.issues)
        deferred_truncated = self.deferred_count > len(self.deferred)
        return {
            "valid": self.issue_count == 0,
            "complete": self.deferred_count == 0 and not issues_truncated,
            "issues": self.issues,
            "issue_count": self.issue_count,
            "issues_truncated": issues_truncated,
            "deferred": self.deferred,
            "deferred_count": self.deferred_count,
            "deferred_truncated": deferred_truncated,
            "command_count": count,
            "native_authority": True,
        }


def validate_batch(registry, doc, doc_id, objects, commands):
    """Inspect a batch on the GTK thread without probing setters or factories.

    The caller supplies the current document/object map and handles generation
    preconditions. No wrappers are retained after this call returns.
    """
    registry._assert_main()
    check = _Validation(registry, doc, doc_id, objects)
    if not isinstance(commands, list) or not 1 <= len(commands) <= 64:
        check.issue(None, "commands", "INVALID_ARGUMENT", "commands must contain 1..64 operations")
        return check.result(len(commands) if isinstance(commands, list) else 0)
    for index, command in enumerate(commands):
        try:
            check.command(index, command)
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            check.defer(
                index, "inspection", f"Native inspection unavailable ({type(exc).__name__})"
            )
    return check.result(len(commands))
