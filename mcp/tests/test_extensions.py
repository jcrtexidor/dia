"""Extension contract and real native persistence/stdio regressions."""

import asyncio
import gzip
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from dia_mcp.backend import NativeBackend
from dia_mcp.errors import DiaError
from dia_mcp.models import Edge, Node
from dia_mcp.service import Operations

NS = {"d": "http://www.lysator.liu.se/~alla/dia/"}
native = pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia")


@pytest.fixture
def api(tmp_path):
    return Operations(NativeBackend(os.environ.get("DIA_BINARY", "dia")), tmp_path)


def xml(path):
    payload = Path(path).read_bytes()
    return ET.fromstring(gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload)


def objects(tree, kind):
    return tree.findall(f".//d:object[@type='{kind}']", NS)


def value(obj, name, kind="string"):
    element = obj.find(f"d:attribute[@name='{name}']/d:{kind}", NS)
    assert element is not None, (name, ET.tostring(obj, encoding="unicode"))
    return element.text if kind == "string" else element.get("val")


def reload(api, source, destination):
    result = subprocess.run(
        [api.backend.executable, "-e", str(destination), "-t", "dia", str(source)],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    return xml(destination)


@pytest.mark.parametrize(
    "properties",
    [
        {"unknown": True},
        {"attributes": [{"name": "bad\x00"}]},
        {"operations": [{"name": "read", "visibility": "friend"}]},
        {"abstract": "yes"},
        {"attributes": [{"name": "a", "class_scope": 1}]},
        {"stereotype": "bad\ud800"},
    ],
)
def test_uml_contract_rejects_invalid_properties(properties):
    with pytest.raises(ValidationError):
        Node(id="a", type="UML - Class", x=0, y=0, properties=properties)


def test_contract_rejects_properties_on_other_objects_and_bad_edges():
    with pytest.raises(ValidationError):
        Node(id="a", x=0, y=0, properties={})
    for fields in (
        {"source_connection": -1},
        {"source_connection": True},
        {"target_connection": 1024},
        {"label": "unsupported"},
        {"type": "UML - Association", "label": "bad\x01"},
    ):
        with pytest.raises(ValidationError):
            Edge(id="e", source="a", target="b", **fields)


@native
@pytest.mark.native
def test_uml_members_relationships_and_native_reload(api, tmp_path):
    doc = api.create_document()["document"]["id"]
    properties = {
        "stereotype": "entity",
        "attributes": [
            {"name": "serial", "type": "str", "value": "none", "visibility": "private"},
            {"name": "count", "type": "int", "class_scope": True, "visibility": "protected"},
        ],
        "operations": [
            {
                "name": "read",
                "type": "bool",
                "visibility": "public",
                "parameters": [{"name": "sample", "type": "int", "kind": "in"}],
            }
        ],
    }
    parent = api.create_object(doc, type="UML - Class", text="Sensor", properties=properties)[
        "object_id"
    ]
    child = api.create_object(doc, type="UML - Class", text="Digital", x=12, y=8)["object_id"]
    gen = api.connect_objects(
        doc, parent, child, type="UML - Generalization", source_port="south", target_port="north"
    )
    api.connect_objects(doc, parent, child, type="UML - Association", label="observes")
    state = api.update_object(doc, parent, width=16, text="BaseSensor")
    assert state["document"]["nodes"][0]["properties"]["attributes"][0]["name"] == "serial"
    geometry = state["geometry"]["edges"][gen["connection_id"]]
    assert geometry["start"] == state["geometry"]["nodes"][parent]["ports"]["south"]["position"]
    path = api.export_diagram(doc, "uml.dia", "dia")["path"]
    for tree in (xml(path), reload(api, path, tmp_path / "uml-reloaded.dia")):
        classes = objects(tree, "UML - Class")
        superclass = next(o for o in classes if value(o, "name") == "#BaseSensor#")
        subclass = next(o for o in classes if value(o, "name") == "#Digital#")
        assert value(superclass, "stereotype") == "#entity#"
        attrs = superclass.findall("d:attribute[@name='attributes']/d:composite", NS)
        assert [value(a, "name") for a in attrs] == ["#serial#", "#count#"]
        assert value(attrs[0], "type") == "#str#"
        assert value(attrs[0], "value") == "#none#"
        assert value(attrs[0], "visibility", "enum") == "1"
        assert value(attrs[1], "class_scope", "boolean") == "true"
        op = superclass.find("d:attribute[@name='operations']/d:composite", NS)
        assert value(op, "name") == "#read#"
        assert value(op, "type") == "#bool#"
        parameter = op.find("d:attribute[@name='parameters']/d:composite", NS)
        assert value(parameter, "name") == "#sample#"
        assert value(parameter, "type") == "#int#"
        assert value(parameter, "kind", "enum") == "1"
        # The ordinary operation contract must not silently create abstract methods.
        assert value(op, "inheritance_type", "enum") == "2"
        generalization = objects(tree, "UML - Generalization")[0]
        connections = generalization.findall("d:connections/d:connection", NS)
        assert connections[0].get("to") == superclass.get("id")
        assert connections[1].get("to") == subclass.get("id")
        assert connections[0].get("connection") == "6"  # native triangle is at start
        assert value(objects(tree, "UML - Association")[0], "name") == "#observes#"


@native
@pytest.mark.native
@pytest.mark.parametrize(
    "kind,source_index,target_index",
    [
        ("Electric - contact_o", 0, 1),
        ("Electric - contact_f", 1, 0),
        ("Electric - relay", 2, 3),
        ("Electric - lamp", 0, 1),
        ("Electric - connpoint", 0, 0),
        ("Pneum - DEJack", 0, 1),
        ("Pneum - dist52", 4, 7),
        ("Pneum - presspn", 0, 0),
        ("Pneum - drain", 0, 0),
    ],
)
def test_exact_technical_terminals_survive_move_and_native_reload(
    api, tmp_path, kind, source_index, target_index
):
    doc = api.create_document()["document"]["id"]
    a = api.create_object(doc, type=kind, x=1, y=2)["object_id"]
    b = api.create_object(doc, type=kind, x=12, y=2)["object_id"]
    result = api.connect_objects(
        doc,
        a,
        b,
        type="Standard - ZigZagLine",
        arrow=False,
        source_connection=source_index,
        target_connection=target_index,
    )
    edge_id = result["connection_id"]
    initial_end = result["geometry"]["edges"][edge_id]["end"]
    moved = api.move_object(doc, b, 14, 8)
    for state in (result, moved):
        edge = state["geometry"]["edges"][edge_id]
        assert edge["source_index"] == source_index
        assert edge["target_index"] == target_index
        assert edge["start"] == pytest.approx(
            state["geometry"]["nodes"][a]["connection_points"][source_index]["position"]
        )
        assert edge["end"] == pytest.approx(
            state["geometry"]["nodes"][b]["connection_points"][target_index]["position"]
        )
    assert moved["geometry"]["edges"][edge_id]["end"] != initial_end
    path = api.export_diagram(doc, "terminals.dia", "dia")["path"]
    for tree in (xml(path), reload(api, path, tmp_path / "terminals-reloaded.dia")):
        edge = objects(tree, "Standard - ZigZagLine")[0]
        connections = edge.findall("d:connections/d:connection", NS)
        assert [int(c.get("connection")) for c in connections] == [source_index, target_index]
        points = edge.findall("d:attribute[@name='orth_points']/d:point", NS)
        assert list(map(float, points[0].get("val").split(","))) == pytest.approx(
            moved["geometry"]["edges"][edge_id]["start"]
        )
        assert list(map(float, points[-1].get("val").split(","))) == pytest.approx(
            moved["geometry"]["edges"][edge_id]["end"]
        )


@native
@pytest.mark.native
@pytest.mark.parametrize("kind", ["Pneum - dist52", "Pneum - presspn", "Pneum - drain"])
def test_textless_symbols_have_native_companion_labels(api, tmp_path, kind):
    doc = api.create_document()["document"]["id"]
    created = api.create_object(doc, type=kind, text="Valve α")
    node_id = created["object_id"]
    before = created["geometry"]["nodes"][node_id]["label_bounds"]
    moved = api.move_object(doc, node_id, 5, 8)
    assert moved["geometry"]["nodes"][node_id]["label_bounds"] != before
    api.update_object(doc, node_id, text="Valve β")
    path = api.export_diagram(doc, "label.dia", "dia")["path"]
    for tree in (xml(path), reload(api, path, tmp_path / "label-reloaded.dia")):
        assert len(objects(tree, kind)) == 1
        labels = objects(tree, "Standard - Text")
        assert len(labels) == 1
        serialized = ET.tostring(labels[0], encoding="unicode")
        assert "Valve β" in serialized and "Valve α" not in serialized
        assert "dia_mcp_parent" in serialized and node_id in serialized
    api.update_object(doc, node_id, text="")
    cleared = api.export_diagram(doc, "cleared.dia", "dia")["path"]
    assert not objects(xml(cleared), "Standard - Text")


@native
@pytest.mark.native
def test_updates_and_invalid_terminal_selection_are_transactional(api):
    doc = api.create_document()["document"]["id"]
    a = api.create_object(doc, type="UML - Class", text="A")["object_id"]
    b = api.create_object(doc, type="UML - Class", text="B", x=10)["object_id"]
    before = api.inspect_document(doc)
    binary = api.backend.executable
    api.backend.executable = "/bin/false"
    try:
        with pytest.raises(DiaError):
            api.update_object(
                doc, a, text="Must roll back", properties={"attributes": [{"name": "new"}]}
            )
    finally:
        api.backend.executable = binary
    assert api.inspect_document(doc) == before
    for changes in (
        {"text": "bad\x00"},
        {"properties": {"attributes": [{"name": "bad\uffff"}]}},
        {"properties": {"unknown": True}},
        {"width": -1},
    ):
        with pytest.raises(DiaError):
            api.update_object(doc, a, **changes)
        assert api.inspect_document(doc) == before
    for selection in (
        {"source_connection": 999},
        {"target_connection": -1},
        {"source_connection": 8},
        {"source_connection": 1, "source_port": "east"},
    ):
        with pytest.raises(DiaError):
            api.connect_objects(doc, a, b, **selection)
        assert api.inspect_document(doc) == before


@native
@pytest.mark.native
def test_extended_stdio_workflow(tmp_path):
    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "dia_mcp.server",
                "--workspace",
                str(tmp_path),
                "--dia-binary",
                os.environ.get("DIA_BINARY", "dia"),
            ],
            env={
                k: v
                for k, v in os.environ.items()
                if k in ("DISPLAY", "XAUTHORITY", "PATH", "PYTHONPATH", "LD_LIBRARY_PATH")
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def call(name, **arguments):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result
                    return json.loads(result.content[0].text)

                doc = (await call("create_document"))["document"]["id"]
                a = await call(
                    "create_object",
                    document_id=doc,
                    type="UML - Class",
                    text="Base",
                    properties={"attributes": [{"name": "id", "type": "int"}]},
                )
                b = await call(
                    "create_object", document_id=doc, type="UML - Class", text="Derived", x=12, y=8
                )
                update = await call(
                    "update_object", document_id=doc, object_id=a["object_id"], text="Updated"
                )
                assert update["document"]["nodes"][0]["text"] == "Updated"
                edge = await call(
                    "connect_objects",
                    document_id=doc,
                    source=a["object_id"],
                    target=b["object_id"],
                    type="UML - Generalization",
                    source_connection=6,
                    target_connection=1,
                )
                assert (
                    edge["geometry"]["edges"][edge["connection_id"]]["type"]
                    == "UML - Generalization"
                )
                exported = await call(
                    "export_diagram", document_id=doc, filename="stdio.dia", format="dia"
                )
                assert len(objects(xml(exported["path"]), "UML - Class")) == 2
                assert edge["document"]["revision"] == 4
                invalid = await session.call_tool(
                    "connect_objects",
                    {
                        "document_id": doc,
                        "source": a["object_id"],
                        "target": b["object_id"],
                        "source_connection": True,
                    },
                )
                assert invalid.isError, "MCP must not coerce a boolean to a terminal index"
                state = await call("inspect_document", document_id=doc)
                assert state["document"]["revision"] == 4

    asyncio.run(run())


@native
@pytest.mark.native
@pytest.mark.parametrize("flip_h,flip_v", [(True, False), (False, True), (True, True)])
def test_technical_flips_mirror_terminals_and_persist(api, tmp_path, flip_h, flip_v):
    doc = api.create_document()["document"]["id"]
    node = api.create_object(doc, type="Pneum - DEJack", width=6, height=2)
    node_id = node["object_id"]
    original = node["geometry"]["nodes"][node_id]["connection_points"]
    changed = api.update_object(doc, node_id, flip_horizontal=flip_h, flip_vertical=flip_v)
    mirrored = changed["geometry"]["nodes"][node_id]["connection_points"]
    for a, b in zip(original, mirrored):
        assert a["index"] == b["index"]
        x, y = a["position"]
        assert b["position"] == pytest.approx([6 - x if flip_h else x, 2 - y if flip_v else y])
    assert [p["directions"] for p in mirrored] == [
        4 if flip_v else 1,
        4 if flip_v else 1,
        2 if flip_h else 8,
        15,
    ]
    path = api.export_diagram(doc, "flipped.dia", "dia")["path"]
    cylinder = objects(xml(path), "Pneum - DEJack")[0]
    assert value(cylinder, "flip_horizontal", "boolean") == str(flip_h).lower()
    assert value(cylinder, "flip_vertical", "boolean") == str(flip_v).lower()

    # Inspect real connection-point direction flags after the native .dia loader.
    # The custom importer only orchestrates loading; it never reconstructs shapes.
    startup = tmp_path / "probe"
    startup.mkdir()
    (startup / "python-startup.py").write_text(
        "import dia, json, os\n"
        "def probe(filename, data):\n"
        "    loaded = dia.load(open(filename).read())\n"
        "    obj = loaded.active_layer.objects[0]\n"
        "    points = [{'index': i, 'position': [p.pos.x, p.pos.y], 'directions': p.directions} "
        "for i, p in enumerate(obj.connections)]\n"
        "    open(os.environ['DIA_PROBE_RESULT'], 'w').write(json.dumps(points))\n"
        "    box, _, _ = dia.get_object_type('Standard - Box').create(0, 0)\n"
        "    data.active_layer.add_object(box)\n"
        "    return True\n"
        "dia.register_import('Connection probe', 'cpprobe', probe)\n"
    )
    request, response = tmp_path / "load.cpprobe", tmp_path / "points.json"
    request.write_text(path)
    result = subprocess.run(
        [api.backend.executable, "-e", str(tmp_path / "probe.dia"), "-t", "dia", str(request)],
        env={**os.environ, "DIA_PYTHON_PATH": str(startup), "DIA_PROBE_RESULT": str(response)},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    loaded_points = json.loads(response.read_text())
    for actual, expected in zip(loaded_points, mirrored):
        assert actual["position"] == pytest.approx(expected["position"])
        assert actual["directions"] == expected["directions"]
    restored = api.update_object(doc, node_id, flip_horizontal=False, flip_vertical=False)
    assert restored["geometry"]["nodes"][node_id]["connection_points"] == original


def test_parameter_and_flip_contracts():
    for properties in (
        {"operations": [{"name": "read", "parameters": [{"name": "p", "kind": "bad"}]}]},
        {"operations": [{"name": "read", "inheritance": "bad"}]},
        {"operations": [{"name": "read", "parameters": [{"name": "bad\x00"}]}]},
    ):
        with pytest.raises(ValidationError):
            Node(id="a", type="UML - Class", x=0, y=0, properties=properties)
    with pytest.raises(ValidationError):
        Node(id="a", x=0, y=0, flip_vertical=True)
