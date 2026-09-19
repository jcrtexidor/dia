"""Stdlib-only adapter, executed inside Dia's embedded CPython on its main thread."""

import json
import math
import os
from pathlib import Path

TYPES = {"Flowchart - Box", "Flowchart - Ellipse", "Flowchart - Diamond"}
PORTS = {"auto", "north", "east", "south", "west", "center"}


def point(position):
    return [position.x, position.y]


def port(obj, side):
    cps = obj.connections
    xs, ys = [cp.pos.x for cp in cps], [cp.pos.y for cp in cps]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    desired = {
        "north": (cx, min(ys)),
        "south": (cx, max(ys)),
        "west": (min(xs), cy),
        "east": (max(xs), cy),
        "center": (cx, cy),
    }[side]
    index = min(range(len(cps)), key=lambda i: math.dist(point(cps[i].pos), desired))
    return index, cps[index]


def center(obj):
    box = obj.bounding_box
    return (box.left + box.right) / 2, (box.top + box.bottom) / 2


def automatic_ports(source, target):
    a, b = center(source), center(target)
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        return ("east", "west") if dx >= 0 else ("west", "east")
    return ("south", "north") if dy >= 0 else ("north", "south")


def validate(spec):
    # The startup hook is also callable directly by Dia; guard native factories here too.
    if spec.get("api_version") != "1":
        raise ValueError("unsupported api_version")
    nodes, edges = spec["nodes"], spec["edges"]
    if len(nodes) > 100 or len(edges) > 200:
        raise ValueError("document exceeds MVP limits")
    identifiers = set()
    for node in nodes:
        if node["type"] not in TYPES or node["id"] in identifiers:
            raise ValueError("unsupported or duplicate object")
        identifiers.add(node["id"])
        for name in ("x", "y", "width", "height"):
            value = node[name]
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("invalid geometry")
            if (
                name in ("x", "y")
                and abs(value) > 1000
                or name in ("width", "height")
                and not 0.1 <= value <= 100
            ):
                raise ValueError("geometry exceeds MVP limits")
        text = node["text"]
        if not isinstance(text, str) or len(text) > 2000:
            raise ValueError("invalid text")
        if any(
            ord(c) < 32
            and c not in "\t\n\r"
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) in (0xFFFE, 0xFFFF)
            for c in text
        ):
            raise ValueError("invalid XML text")
    node_ids = identifiers.copy()
    for edge in edges:
        if (
            edge["source"] not in node_ids
            or edge["target"] not in node_ids
            or edge["source"] == edge["target"]
            or edge["id"] in identifiers
            or edge["source_port"] not in PORTS
            or edge["target_port"] not in PORTS
            or type(edge["arrow"]) is not bool
        ):
            raise ValueError("invalid connection")
        identifiers.add(edge["id"])


def materialize(spec, data):
    import dia

    validate(spec)
    objects, geometry = {}, {"nodes": {}, "edges": {}}
    layer = data.active_layer
    for node in spec["nodes"]:
        obj, _, _ = dia.get_object_type(node["type"]).create(node["x"], node["y"])
        layer.add_object(obj)
        obj.properties["elem_width"] = node["width"]
        obj.properties["elem_height"] = node["height"]
        obj.properties["text"] = node["text"]
        obj.move(node["x"], node["y"])
        obj.properties["meta"] = {"dia_mcp_id": node["id"]}
        objects[node["id"]] = obj
        box = obj.bounding_box
        geometry["nodes"][node["id"]] = {
            "bounds": [box.left, box.top, box.right, box.bottom],
            "ports": {
                side: {"index": port(obj, side)[0], "position": point(port(obj, side)[1].pos)}
                for side in sorted(PORTS - {"auto"})
            },
        }
    for edge in spec["edges"]:
        source, target = objects[edge["source"]], objects[edge["target"]]
        source_side, target_side = automatic_ports(source, target)
        source_side = source_side if edge["source_port"] == "auto" else edge["source_port"]
        target_side = target_side if edge["target_port"] == "auto" else edge["target_port"]
        source_index, start = port(source, source_side)
        target_index, end = port(target, target_side)
        obj, h1, h2 = dia.get_object_type("Standard - Line").create(start.pos.x, start.pos.y)
        layer.add_object(obj)
        obj.properties["end_arrow"] = (3 if edge["arrow"] else 0, 0.5, 0.5)
        obj.properties["meta"] = {"dia_mcp_id": edge["id"]}
        # object_connect alone does not move a handle to its connection point.
        for handle, cp in ((h1, start), (h2, end)):
            obj.move_handle(handle, tuple(point(cp.pos)), 0, 0)
            handle.connect(cp)
        geometry["edges"][edge["id"]] = {
            "source_port": source_side,
            "target_port": target_side,
            "source_index": source_index,
            "target_index": target_index,
            "start": point(h1.pos),
            "end": point(h2.pos),
        }
    data.update_extents()
    if os.environ.get("DIA_MCP_FORMAT") == "png":
        extents = data.extents
        scale = 20.0 * data.paper.scaling  # lib/renderer/diacairo.c::cairo_export_data
        width = math.ceil((extents.right - extents.left) * scale) + 1
        height = math.ceil((extents.bottom - extents.top) * scale) + 1
        if width > 8192 or height > 8192 or width * height > 20_000_000:
            raise ValueError("PNG exceeds 8192 px per side or 20 million pixels; use SVG")
    return geometry


def import_snapshot(filename, data):
    response = Path(os.environ["DIA_MCP_RESPONSE"])
    try:
        spec = json.loads(Path(filename).read_text(encoding="utf-8"))
        report = {"ok": True, "geometry": materialize(spec, data)}
    except Exception as exc:
        report = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    response.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
    return report["ok"]


def register():
    import dia

    dia.register_import("Dia operations v1", "diacmd", import_snapshot)
