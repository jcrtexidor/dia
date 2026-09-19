"""Real running GUI tests. Run under Xvfb and separately under a real Wayland compositor."""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import dia_mcp
from dia_mcp.errors import DiaError
from dia_mcp.live.client import LiveClient

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires Dia"),
]


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.03)
    raise AssertionError("Timed out waiting for GUI fixture")


@pytest.fixture
def gui(tmp_path):
    home = tmp_path / "home"
    plugins = home / ".dia" / "python"
    plugins.mkdir(parents=True)
    (plugins / "fixture.py").write_text("from live_fixture import install\ninstall()\n")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    # A Wayland run must retain the real compositor path; the private endpoint
    # still lives under its normal XDG_RUNTIME_DIR/dia-mcp location.
    runtime_env = (
        os.environ.get("XDG_RUNTIME_DIR")
        if os.environ.get("GDK_BACKEND") == "wayland"
        else str(runtime)
    )
    shapes, sheets = tmp_path / "shapes", tmp_path / "sheets"
    shapes.mkdir()
    sheets.mkdir()
    (shapes / "custom.shape").write_text("""<?xml version="1.0"?>
<shape xmlns="http://www.daa.com.au/~james/dia-shape-ns"
       xmlns:svg="http://www.w3.org/2000/svg">
<name>Live - Unfamiliar</name><icon>none.png</icon>
<connections><point x="0" y="0"/></connections><aspectratio type="free"/>
<svg:svg><svg:rect x="0" y="0" width="2" height="1"/></svg:svg></shape>""")
    (sheets / "custom.sheet").write_text("""<?xml version="1.0"?>
<sheet xmlns="http://www.lysator.liu.se/~alla/dia/dia-sheet-ns">
<name>Live custom</name><description>Fixture</description><contents>
<object name="Live - Unfamiliar"><description>Unfamiliar</description></object>
</contents></sheet>""")
    import shutil

    binary = shutil.which(os.environ.get("DIA_BINARY", "dia"))
    data = Path(binary).resolve().parent.parent / "share" / "dia"
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_RUNTIME_DIR": runtime_env,
        "DIA_MCP_LIVE": "1",
        "DIA_LIVE_TEST": str(tmp_path),
        "DIA_SHAPE_PATH": f"{data / 'shapes'}:{shapes}",
        "DIA_SHEET_PATH": f"{data / 'sheets'}:{sheets}",
        "PYTHONPATH": f"{Path(__file__).parent}:{Path(dia_mcp.__file__).parent.parent}",
    }
    env.pop("DIA_PYTHON_PATH", None)
    log = (tmp_path / "gui.log").open("w+")
    process = subprocess.Popen([binary, "--nosplash"], env=env, stdout=log, stderr=log)
    path = Path(runtime_env) / "dia-mcp" / f"live-{process.pid}.sock"

    def command(action):
        reply = tmp_path / "reply.json"
        reply.unlink(missing_ok=True)
        staging = tmp_path / "command.tmp"
        staging.write_text(json.dumps({"action": action}))
        staging.rename(tmp_path / "command.json")

        def completed():
            assert process.poll() is None or reply.exists(), f"Dia exited: {process.returncode}"
            return reply.exists()

        wait_for(completed)
        result = json.loads(reply.read_text())
        assert result["ok"], result
        return result

    try:
        wait_for(path.exists)
        yield LiveClient(path), command, process, path
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.seek(0)
        print(log.read())
        log.close()


def test_live_gui_lifecycle_domains_concurrency(gui, tmp_path):
    client, command, process, path = gui
    hello = client.request("handshake")
    assert hello["integration_api_version"] == 1
    assert hello["dia_version"]
    defaults = client.request("list_documents")["items"]
    assert defaults, "Normal GUI startup must expose the default document"
    command("create")
    docs = client.request("list_documents")["items"]
    doc = next(d for d in docs if d["name"] == "live-fixture.dia")
    did = doc["document_id"]
    assert client.request("get_active_document")["document"]["document_id"] == did
    layers = client.request("list_layers", document_id=did)["items"]
    assert layers[0]["active"] and layers[0]["visible"] and layers[0]["object_count"] == 8
    objects = client.request("list_objects", document_id=did)["items"]
    assert len(objects) == 8
    oid = objects[0]["object_id"]
    with pytest.raises(DiaError) as foreign:
        client.request("get_object", document_id=defaults[0]["document_id"], object_id=oid)
    assert foreign.value.code == "OBJECT_NOT_FOUND"
    assert client.request("get_selection", document_id=did)["items"][0]["object_id"] == oid
    for obj in objects:
        result = client.request(
            "get_object", document_id=did, object_id=obj["object_id"], properties=True
        )
        assert result["object"]["type"] == obj["type"]
    custom = next(o for o in objects if o["type"] == "Live - Unfamiliar")
    assert (
        client.request("get_object", document_id=did, object_id=custom["object_id"])["object"][
            "sheet_entries"
        ][0]["sheet"]
        == "Live custom"
    )
    connector = next(o for o in objects if o["type"] == "Standard - Line")
    connections = client.request(
        "get_connections", document_id=did, object_id=connector["object_id"]
    )
    assert connections["handles"][0]["attached_to"] == {"object_id": oid, "connection_point": 0}
    assert connections["handles"][1]["attached_to"] is None
    cp = client.request("get_connections", document_id=did, object_id=oid)
    assert connector["object_id"] in cp["connection_points"][0]["connected_objects"]
    first = client.request("get_object", document_id=did, object_id=oid)
    command("move")
    moved = client.request("get_object", document_id=did, object_id=oid)
    assert moved["object"]["bounds"] != first["object"]["bounds"]
    assert moved["generation"] > first["generation"]
    command("property")
    changed = client.request("get_object", document_id=did, object_id=oid, properties=True)
    assert changed["generation"] > moved["generation"]
    assert any(
        p.get("value") == "Changed from GUI side" for p in changed["object"]["properties"]["items"]
    )
    command("select")
    assert client.request("get_selection", document_id=did)["items"][0]["object_id"] != oid
    command("duplicate")
    assert len(client.request("list_objects", document_id=did)["items"]) == 9
    before = command("status")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: client.request("get_object", document_id=did, object_id=oid), range(80)
            )
        )
    assert all(r["object"]["object_id"] == oid for r in results)
    stop = threading.Event()

    def read_until_stopped():
        count = 0
        while not stop.is_set():
            client.request("get_object", document_id=did, object_id=oid)
            count += 1
        return count

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read_until_stopped) for _ in range(4)]
        try:
            started = time.monotonic()
            command("select")
            after = command("status")
            assert time.monotonic() - started < 2
        finally:
            stop.set()
        assert sum(f.result() for f in futures) > 0
    assert after["ticks"] > before["ticks"], "GTK timer must run during concurrent reads"
    if os.environ.get("GDK_BACKEND") == "wayland":
        assert after["display"] == "GdkWaylandDisplay"
    command("delete")
    with pytest.raises(DiaError, match="detached") as error:
        client.request("get_object", document_id=did, object_id=oid)
    assert error.value.code == "STALE_OBJECT_REFERENCE"
    command("restore")
    with pytest.raises(DiaError):
        client.request("get_object", document_id=did, object_id=oid)
    restored = client.request("list_objects", document_id=did)["items"]
    restored_id = restored[-1]["object_id"]
    command("native_delete")
    with pytest.raises(DiaError):
        client.request("get_object", document_id=did, object_id=restored_id)
    command("undo")
    with pytest.raises(DiaError):
        client.request("get_object", document_id=did, object_id=restored_id)
    assert client.request("list_objects", document_id=did)["total"] == 9
    command("redo")
    assert client.request("list_objects", document_id=did)["total"] == 8
    command("undo")
    command("group")
    grouped = client.request("list_objects", document_id=did)["items"]
    assert any(o["group_id"] is not None for o in grouped)

    async def stdio_read():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "dia_mcp.server",
                "--workspace",
                str(tmp_path / "out"),
                "--live-socket",
                str(path),
            ],
            env={k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH"}},
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                document_args = {"document_id": did}
                object_args = {**document_args, "object_id": connector["object_id"]}
                for name, arguments in [
                    ("live_handshake", {}),
                    ("live_list_documents", {}),
                    ("live_get_active_document", {}),
                    ("live_get_document", document_args),
                    ("live_list_layers", document_args),
                    ("live_get_selection", document_args),
                    ("live_list_objects", document_args),
                    ("live_get_object", object_args),
                    ("live_get_connections", object_args),
                ]:
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result
                    assert json.loads(result.content[0].text)["scope"] == "live"

    asyncio.run(stdio_read())
    command("layer")
    layer_page = client.request("list_layers", document_id=did, limit=1)
    assert layer_page["items"][0]["name"] == "Extra"
    assert layer_page["items"][0]["active"]
    assert layer_page["next_offset"] == 1
    assert (
        client.request("list_layers", document_id=did, offset=1)["items"][0]["layer_id"]
        == layers[0]["layer_id"]
    )
    with pytest.raises(DiaError) as error:
        client.request("get_document", document_id="snapshot-document")
    assert error.value.code == "WRONG_SESSION"
    command("close")
    with pytest.raises(DiaError) as error:
        client.request("get_document", document_id=did)
    assert error.value.code == "STALE_DOCUMENT_REFERENCE"
    command("open")
    assert client.request("get_active_document")["document"]["document_id"] != did
    for default in defaults:
        with pytest.raises(DiaError) as error:
            client.request("get_document", document_id=default["document_id"])
        assert error.value.code == "STALE_DOCUMENT_REFERENCE"
    assert LiveClient(path).request("handshake")["session_id"] == hello["session_id"]
    command("quit")
    process.wait(timeout=10)
    assert not path.exists()


def test_live_wire_rejections_and_disconnect(gui):
    import socket

    from dia_mcp.live.protocol import decode, encode

    client, command, _, path = gui

    def exchange(request):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(3)
            sock.connect(str(path))
            sock.sendall(encode(request, 20000))
            return decode(sock.makefile("rb").readline(1048576), 1048576)

    assert (
        exchange({"protocol_version": 2, "action": "handshake"})["error"]["code"]
        == "LIVE_PROTOCOL_MISMATCH"
    )
    assert (
        exchange({"protocol_version": 1, "action": "list_documents"})["error"]["code"]
        == "LIVE_PROTOCOL_MISMATCH"
    )
    assert (
        exchange({"protocol_version": 1, "action": "exec"})["error"]["code"]
        == "UNSUPPORTED_LIVE_CAPABILITY"
    )
    for _ in range(20):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.connect(str(path))
            sock.sendall(b'{"protocol_version":1,"action":"handshake"}\n')
    assert client.request("handshake")["integration_api_version"] == 1
    assert command("status")["ok"]
    command("quit")
