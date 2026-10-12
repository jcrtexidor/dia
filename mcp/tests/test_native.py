"""Integration and C regressions: run against the compiled fork, never a fake."""

import gzip
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dia_mcp.backend import NativeBackend, validate_artifact
from dia_mcp.errors import DiaError
from dia_mcp.service import Operations

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(
        os.environ.get("DIA_MCP_NATIVE") != "1", reason="set DIA_MCP_NATIVE=1 with compiled Dia"
    ),
]
NS = {"d": "http://www.lysator.liu.se/~alla/dia/"}


def dia_xml(path):
    payload = Path(path).read_bytes()
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    return ET.fromstring(payload)


@pytest.fixture
def api(tmp_path):
    return Operations(NativeBackend(os.environ.get("DIA_BINARY", "dia")), tmp_path)


def connected(api):
    doc = api.create_document("Inicio → fin")["document"]["id"]
    a = api.create_object(doc, text="Inicio áéí", x=1, y=1)["object_id"]
    b = api.create_object(doc, type="Flowchart - Ellipse", text="Fin", x=9, y=1)["object_id"]
    result = api.connect_objects(doc, a, b)
    return doc, a, b, result["connection_id"]


def test_create_connect_move_export_and_native_reload(api, tmp_path):
    doc, a, b, edge = connected(api)
    initial = api.inspect_document(doc)
    geometry = initial["geometry"]["edges"][edge]
    assert geometry["source_port"] == "east" and geometry["target_port"] == "west"
    assert geometry["start"] != geometry["end"]
    moved = api.move_object(doc, b, 9, 7)
    assert moved["geometry"]["edges"][edge]["end"] != geometry["end"]
    assert moved["document"]["revision"] == initial["document"]["revision"] + 1

    for format in ("dia", "svg", "png"):
        report = api.export_diagram(doc, f"diagram.{format}", format)
        assert report["bytes"] > 100 and len(report["sha256"]) == 64
        validate_artifact(Path(report["path"]), format)
    tree = dia_xml(tmp_path / "diagram.dia")
    objects = tree.findall(".//d:object", NS)
    assert len(objects) == 3
    line = next(obj for obj in objects if obj.get("type") == "Standard - Line")
    connections = line.findall("d:connections/d:connection", NS)
    assert len(connections) == 2
    assert {c.get("to") for c in connections} == {obj.get("id") for obj in objects if obj != line}
    assert "Inicio áéí" in ET.tostring(tree, encoding="unicode")
    assert a in ET.tostring(tree, encoding="unicode")  # stable ID stored in native meta
    endpoints = line.findall("d:attribute[@name='conn_endpoints']/d:point", NS)
    positions = [list(map(float, p.get("val").split(","))) for p in endpoints]
    assert positions[0] == pytest.approx(moved["geometry"]["edges"][edge]["start"], abs=1e-4)
    assert positions[1] == pytest.approx(moved["geometry"]["edges"][edge]["end"], abs=1e-4)
    # A second native process loads the .dia file and exports again: not our JSON importer.
    process = subprocess.run(
        [
            api.backend.executable,
            "-e",
            str(tmp_path / "reloaded.svg"),
            "-t",
            "svg",
            str(tmp_path / "diagram.dia"),
        ],
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr.decode()
    validate_artifact(tmp_path / "reloaded.svg", "svg")
    reloaded = tmp_path / "reloaded.dia"
    process = subprocess.run(
        [api.backend.executable, "-e", str(reloaded), "-t", "dia", str(tmp_path / "diagram.dia")],
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr.decode()
    reloaded_connections = dia_xml(reloaded).findall(".//d:connections/d:connection", NS)
    assert [c.attrib for c in reloaded_connections] == [c.attrib for c in connections]


@pytest.mark.parametrize("type", Operations.capabilities()["object_types"])
def test_all_advertised_shapes_and_ports(api, type):
    doc = api.create_document()["document"]["id"]
    a = api.create_object(doc, type=type, text="Texto que amplía el objeto")
    b = api.create_object(doc, x=10, y=5)
    for port in ("north", "east", "south", "west", "center"):
        result = api.connect_objects(doc, a["object_id"], b["object_id"], port, "west", False)
        geometry = result["geometry"]["edges"][result["connection_id"]]
        assert geometry["source_port"] == port


def test_native_validation_failure_does_not_commit(api):
    doc, _, _, _ = connected(api)
    before = api.inspect_document(doc)
    original = api.backend.executable
    api.backend.executable = "/bin/false"
    with pytest.raises(DiaError, match="Missing native response"):
        api.create_object(doc, text="Must not survive")
    api.backend.executable = original
    assert api.inspect_document(doc) == before


@pytest.mark.parametrize(
    "result,success", [("False", False), ("None", True), ("True", True), ("1 / 0", False)]
)
def test_python_import_return_value(tmp_path, result, success):
    # Directly exercises PyDia_import_data and preserves legacy implicit-None importers.
    startup = tmp_path / "python-startup.py"
    startup.write_text(
        "import dia\n"
        "def load(filename, data):\n"
        "    obj, _, _ = dia.get_object_type('Standard - Box').create(1, 1)\n"
        "    data.active_layer.add_object(obj)\n"
        f"    return {result}\n"
        "dia.register_import('Regression', 'diatest', load)\n"
    )
    request = tmp_path / "input.diatest"
    request.write_text("test")
    output = tmp_path / "output.svg"
    process = subprocess.run(
        [os.environ.get("DIA_BINARY", "dia"), "-e", str(output), "-t", "svg", str(request)],
        env={**os.environ, "DIA_PYTHON_PATH": str(tmp_path)},
        capture_output=True,
        timeout=30,
    )
    assert (process.returncode == 0) == success, process.stderr.decode()
    assert output.exists() == success


def test_export_failure_returns_nonzero(api, tmp_path):
    doc, _, _, _ = connected(api)
    saved = api.export_diagram(doc, "source.dia", "dia")
    missing = tmp_path / "missing" / "out.dia"
    process = subprocess.run(
        [api.backend.executable, "-e", str(missing), "-t", "dia", saved["path"]],
        capture_output=True,
        timeout=30,
    )
    assert process.returncode != 0
    assert not missing.exists()


def test_bridge_rejects_invalid_json(api, tmp_path):
    import dia_mcp.backend

    startup = Path(dia_mcp.backend.__file__).parent / "native"
    request = tmp_path / "bad.diacmd"
    response = tmp_path / "response.json"
    request.write_text('{"api_version": "unsupported"}')
    process = subprocess.run(
        [api.backend.executable, "-e", str(tmp_path / "bad.svg"), str(request)],
        env={**os.environ, "DIA_PYTHON_PATH": str(startup), "DIA_MCP_RESPONSE": str(response)},
        capture_output=True,
        timeout=30,
    )
    assert process.returncode != 0
    assert json.loads(response.read_text())["ok"] is False
    assert not (tmp_path / "bad.svg").exists()


def test_png_size_limit_prevents_native_raster_allocation(api, tmp_path):
    doc = api.create_document()["document"]["id"]
    api.create_object(doc, x=-1000, y=-1000)
    api.create_object(doc, x=1000, y=1000)
    with pytest.raises(DiaError, match="PNG exceeds"):
        api.export_diagram(doc, "oversized.png", "png")
    assert not (tmp_path / "oversized.png").exists()
    assert api.export_diagram(doc, "large.svg", "svg")["bytes"] > 100
