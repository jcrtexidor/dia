"""Versioned, bounded wire contract shared with Dia's embedded system Python.

No SDK/Pydantic dependency: this module is also imported by the GUI plugin.
"""

import json
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
        raise DiaError("UNSUPPORTED_LIVE_CAPABILITY", "Unknown live read operation")
    allowed = {"protocol_version", "action"} | ACTIONS[action]
    if action in PAGED:
        allowed |= {"offset", "limit"}
    if action == "get_object":
        allowed |= {"properties"}
    if set(request) - allowed or not ACTIONS[action] <= set(request):
        raise DiaError("INVALID_ARGUMENT", "Invalid live operation fields")
    for name in ACTIONS[action]:
        if not isinstance(request[name], str) or not 1 <= len(request[name]) <= 256:
            raise DiaError("INVALID_ARGUMENT", "Invalid live reference")
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
