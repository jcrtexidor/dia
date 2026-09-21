"""Versioned, bounded wire contract shared with Dia's embedded system Python.

No SDK/Pydantic dependency: this module is also imported by the GUI plugin.
"""

import json
import math
from dataclasses import dataclass

from ..errors import DiaError

VERSION = 1
CAPABILITIES = [
    "documents.read",
    "layers.read",
    "selection.read",
    "objects.read",
    "connections.read",
]
ACTIONS = {
    "handshake": set(),
    "list_documents": set(),
    "get_active_document": set(),
    "get_document": {"document_id"},
    "list_layers": {"document_id"},
    "get_selection": {"document_id"},
    "list_objects": {"document_id"},
    "get_object": {"document_id", "object_id"},
    "get_connections": {"document_id", "object_id"},
}
MUTATIONS = {
    "apply_commands",
    "history",
    "open_document",
    "save_document",
    "save_document_as",
    "export_document",
}
ACTIONS.update(
    {
        "prepare_operation": set(),
        "get_operation": {"request_id"},
        "apply_commands": {"document_id", "request_id", "expected_generation", "commands"},
        "history": {"document_id", "request_id", "expected_generation", "direction"},
        "open_document": {"request_id", "path"},
        "save_document": {"document_id", "request_id", "expected_generation"},
        "save_document_as": {"document_id", "request_id", "expected_generation", "path"},
        "export_document": {"document_id", "request_id", "expected_generation", "path", "format"},
        "summarize_document": {"document_id"},
        "analyze_document": {"document_id"},
        "get_dependencies": {"document_id"},
    }
)
# Required capability for each request; old protocol-v1 peers can omit only optional
# additions, never silently execute a capability they did not advertise.
REQUIRED_CAPABILITY = {
    "list_documents": "documents.read",
    "get_active_document": "documents.read",
    "get_document": "documents.read",
    "list_layers": "layers.read",
    "get_selection": "selection.read",
    "list_objects": "objects.read",
    "get_object": "objects.read",
    "get_connections": "connections.read",
    "apply_commands": "objects.write",
    "history": "history.write",
    "open_document": "files.open",
    "save_document": "files.write",
    "save_document_as": "files.write",
    "export_document": "files.write",
    "summarize_document": "summary.read",
    "analyze_document": "semantics.read",
    "get_dependencies": "dependencies.read",
    "prepare_operation": "objects.write",
}

COMMAND_FIELDS = {
    "move": ({"op", "object_id", "x", "y"}, set()),
    "set_properties": ({"op", "object_id", "properties"}, set()),
    "create": ({"op", "type", "x", "y"}, {"properties", "layer_id"}),
    "delete": ({"op", "object_id"}, set()),
    "connect": ({"op", "object_id", "handle", "target_id", "point"}, set()),
    "disconnect": ({"op", "object_id", "handle"}, set()),
    "layout": ({"op", "object_ids", "mode"}, set()),
}


def validate_commands(commands):
    if not isinstance(commands, list) or not 1 <= len(commands) <= 64:
        raise DiaError("INVALID_ARGUMENT", "commands must contain 1..64 operations")
    for command in commands:
        if (
            not isinstance(command, dict)
            or not isinstance(command.get("op"), str)
            or command["op"] not in COMMAND_FIELDS
        ):
            raise DiaError("INVALID_ARGUMENT", "Unknown native command")
        required, optional = COMMAND_FIELDS[command["op"]]
        if not required <= command.keys() or command.keys() - required - optional:
            raise DiaError("INVALID_ARGUMENT", "Invalid native command fields")
        for name, value in command.items():
            if name in {"x", "y"} and (
                type(value) not in (int, float) or abs(value) > 1000000 or not math.isfinite(value)
            ):
                raise DiaError("INVALID_ARGUMENT", "Coordinates must be finite centimeters")
            if name in {"handle", "point"} and (type(value) is not int or not 0 <= value < 256):
                raise DiaError("INVALID_ARGUMENT", "Invalid native connection index")
            if name in {"object_id", "target_id", "layer_id", "type", "mode"} and (
                not isinstance(value, str) or not 1 <= len(value) <= 256
            ):
                raise DiaError("INVALID_ARGUMENT", "Invalid command reference")
        if "object_ids" in command:
            ids = command["object_ids"]
            if (
                not isinstance(ids, list)
                or not 2 <= len(ids) <= 64
                or any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in ids)
                or len(set(ids)) != len(ids)
            ):
                raise DiaError("INVALID_ARGUMENT", "layout requires 2..64 distinct object IDs")
        if "properties" in command:
            props = command["properties"]
            if not isinstance(props, dict) or len(props) > 32:
                raise DiaError("INVALID_ARGUMENT", "At most 32 scalar properties are supported")
            for name, value in props.items():
                if (
                    not isinstance(name, str)
                    or not 1 <= len(name) <= 128
                    or type(value) not in (bool, int, float, str)
                ):
                    raise DiaError("INVALID_ARGUMENT", "Only named scalar properties are supported")
                if (isinstance(value, str) and (len(value) > 2048 or "\0" in value)) or (
                    type(value) is float and not math.isfinite(value)
                ):
                    raise DiaError("INVALID_ARGUMENT", "Invalid property value")
    return commands


PAGED = {"list_documents", "list_layers", "get_selection", "list_objects"}


@dataclass(frozen=True)
class Limits:
    request_bytes: int = 16384
    response_bytes: int = 1048576
    queue: int = 16
    clients: int = 32
    page: int = 100
    properties: int = 32
    structure: int = 256
    objects: int = 10000
    timeout: float = 5.0

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            expected = (int, float) if name == "timeout" else (int,)
            if type(value) not in expected or value <= 0:
                raise ValueError(f"Invalid live limit: {name}")
        if self.request_bytes < 256 or self.response_bytes < 512:
            raise ValueError("Live byte limits must fit a handshake and structured error")
        if not 0 < self.timeout <= 30:
            raise ValueError("Live timeout must be <=30 seconds")


def encode(value, maximum):
    try:
        data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    except (ValueError, TypeError) as exc:
        raise DiaError("LIVE_INVALID_RESPONSE", "Live result is not serializable") from exc
    if len(data) > maximum:
        raise DiaError("LIVE_LIMIT_EXCEEDED", "Live message exceeds byte limit")
    return data


def decode(data, maximum):
    if len(data) > maximum:
        raise DiaError("LIVE_LIMIT_EXCEEDED", "Live message exceeds byte limit")
    try:
        value = json.loads(data, parse_constant=lambda _: None)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DiaError("INVALID_ARGUMENT", "Invalid live JSON") from exc
    if not isinstance(value, dict):
        raise DiaError("INVALID_ARGUMENT", "Live message must be an object")
    return value


def validate(request, limits=Limits()):
    if type(request.get("protocol_version")) is not int or request["protocol_version"] != VERSION:
        raise DiaError("LIVE_PROTOCOL_MISMATCH", "Live integration protocol version 1 required")
    action = request.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise DiaError("UNSUPPORTED_LIVE_CAPABILITY", "Unknown live operation")
    allowed = {"protocol_version", "action"} | ACTIONS[action]
    if action in PAGED:
        allowed |= {"offset", "limit"}
    if action in {"save_document", "save_document_as", "export_document"}:
        allowed |= {"overwrite"}
    if action == "analyze_document":
        allowed |= {"domain"}
    if action == "get_object":
        allowed |= {"properties"}
    if set(request) - allowed or not ACTIONS[action] <= set(request):
        raise DiaError("INVALID_ARGUMENT", "Invalid live operation fields")
    for name in ACTIONS[action] - {"expected_generation", "commands"}:
        if not isinstance(request[name], str) or not 1 <= len(request[name]) <= 256:
            raise DiaError("INVALID_ARGUMENT", "Invalid live reference")
    if "expected_generation" in request and (
        type(request["expected_generation"]) is not int or request["expected_generation"] < 1
    ):
        raise DiaError("INVALID_ARGUMENT", "expected_generation must be a positive integer")
    if "overwrite" in request and type(request["overwrite"]) is not bool:
        raise DiaError("INVALID_ARGUMENT", "overwrite must be boolean")
    if "path" in request and "\0" in request["path"]:
        raise DiaError("INVALID_ARGUMENT", "Invalid path")
    if action == "apply_commands":
        validate_commands(request["commands"])
    if action == "history" and request["direction"] not in {"undo", "redo"}:
        raise DiaError("INVALID_ARGUMENT", "direction must be undo or redo")
    if action == "analyze_document":
        domain = request.get("domain", "auto")
        if not isinstance(domain, str) or domain not in {
            "auto",
            "uml",
            "flowchart",
            "database",
            "network",
            "electrical",
            "pneumatic",
        }:
            raise DiaError("INVALID_ARGUMENT", "Unsupported analysis domain")
    if action in PAGED:
        offset, limit = request.get("offset", 0), request.get("limit", limits.page)
        if type(offset) is not int or not 0 <= offset <= 1000000:
            raise DiaError("INVALID_ARGUMENT", "offset must be 0..1000000")
        if type(limit) is not int or not 1 <= limit <= limits.page:
            raise DiaError("INVALID_ARGUMENT", f"limit must be 1..{limits.page}")
    if "properties" in request and type(request["properties"]) is not bool:
        raise DiaError("INVALID_ARGUMENT", "properties must be boolean")
    return request


def page(items, request, limits):
    start, size = request.get("offset", 0), request.get("limit", limits.page)
    end = start + size
    return {
        "items": items[start:end],
        "total": len(items),
        "next_offset": end if end < len(items) else None,
    }
