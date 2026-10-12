"""Bounded sustained-load acceptance against the real GTK process and Unix socket."""

import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_live_files_native import perform
from test_live_native import gui, wait_for  # noqa: F401

from dia_mcp.errors import DiaError
from dia_mcp.live.client import LiveClient
from dia_mcp.live.protocol import VERSION, decode, encode

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia"),
]


@pytest.fixture
def endurance_gui(monkeypatch, tmp_path, request):
    monkeypatch.setenv("DIA_MCP_WRITE", "1")
    monkeypatch.setenv("DIA_MCP_FILES_ROOT", str(tmp_path))
    return request.getfixturevalue("gui")


def settled(command):
    def sample():
        stats = command("stats")["listener"]
        return stats if stats["clients"] == 0 and stats["queue"] == 0 else None

    return wait_for(sample)


def assert_bounded(stats):
    assert stats["clients"] == stats["queue"] == stats["cache_native_wrappers"] == 0
    assert stats["sources"] == 2  # listener accept and expiry timer only
    assert stats["receipts"] <= stats["receipt_capacity"]
    assert stats["generations"] <= stats["visible_documents"]


def test_live_sustained_reads_mutations_and_resource_plateau(endurance_gui, tmp_path):
    client, command, process, path = endurance_gui
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    oid = client.request("list_objects", document_id=did)["items"][0]["object_id"]
    # Populate lazy sheet/font/cache state before measuring the retained baseline.
    client.request("get_object", document_id=did, object_id=oid, properties=True)
    baseline = settled(command)
    started = time.monotonic()
    samples = [{"stage": "warm", **baseline}]

    def read(index):
        reader = LiveClient(path)
        result = reader.request(
            "get_object", document_id=did, object_id=oid, properties=index % 5 == 0
        )
        assert result["object"]["object_id"] == oid
        return result["generation"]

    for batch in range(5):
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert len(list(pool.map(read, range(200)))) == 200
        stats = settled(command)
        assert_bounded(stats)
        samples.append({"stage": f"read_{(batch + 1) * 200}", **stats})
    count = client.request("list_objects", document_id=did)["total"]
    for cycle in range(100):
        created = perform(
            client,
            "apply_commands",
            did,
            commands=[
                {"op": "create", "type": "Standard - Box", "x": cycle % 10, "y": 20},
            ],
        )["created"][0]
        perform(
            client,
            "apply_commands",
            did,
            commands=[
                {"op": "move", "object_id": created, "x": 30, "y": 25},
            ],
        )
        assert perform(client, "history", did, direction="undo")["history"]
        assert perform(client, "history", did, direction="redo")["history"]
        perform(client, "apply_commands", did, commands=[{"op": "delete", "object_id": created}])
        assert client.request("list_objects", document_id=did)["total"] == count
        if cycle % 20 == 19:
            stats = settled(command)
            assert_bounded(stats)
            samples.append({"stage": f"cycle_{cycle + 1}", **stats})
    final = samples[-1]
    if final["native_identity_entries"] is not None:
        assert samples[5]["native_identity_entries"] == baseline["native_identity_entries"]
        # Undo deliberately retains a bounded tail; old deleted objects should
        # be reclaimed once those transactions leave native history.
        assert final["native_identity_entries"] <= samples[-3]["native_identity_entries"] + 4
    assert final["fds"] <= baseline["fds"] + 2
    # Native undo deliberately retains objects. This is a regression ceiling,
    # not an assertion that the native history/font allocators release all RSS.
    assert final["rss_kib"] - baseline["rss_kib"] < 64 * 1024
    assert final["rss_kib"] - samples[-3]["rss_kib"] < 16 * 1024
    evidence = {
        "reads": 1000,
        "clients": 8,
        "cycles": 100,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "pid": process.pid,
        "samples": samples,
    }
    (tmp_path / "endurance.json").write_text(json.dumps(evidence, indent=2))
    print("ENDURANCE " + json.dumps(evidence))


def test_live_repeated_file_lifecycle_and_gui_stale_mutation(endurance_gui, tmp_path):
    client, command, _, _ = endurance_gui
    command("create")
    original = client.request("get_active_document")["document"]["document_id"]
    oid = client.request("list_objects", document_id=original)["items"][0]["object_id"]
    generation = client.request("get_document", document_id=original)["generation"]
    ticket = client.request("prepare_operation")["request_id"]
    command("move")
    moved = client.request("get_object", document_id=original, object_id=oid)["object"]["position"]
    with pytest.raises(DiaError) as stale:
        client.request(
            "apply_commands",
            request_id=ticket,
            document_id=original,
            expected_generation=generation,
            commands=[{"op": "move", "object_id": oid, "x": 99, "y": 99}],
        )
    assert stale.value.code == "GENERATION_CONFLICT"
    assert (
        client.request("get_object", document_id=original, object_id=oid)["object"]["position"]
        == moved
    )
    source = tmp_path / "source.dia"
    perform(client, "save_document_as", original, path=str(source))
    baseline = settled(command)
    for index in range(20):
        did = perform(client, "open_document", path=str(source))["document"]["document_id"]
        objects = client.request("list_objects", document_id=did)["items"]
        assert len(objects) == 8
        target = tmp_path / f"roundtrip-{index}.dia"
        perform(client, "save_document_as", did, path=str(target))
        assert target.stat().st_size > 0
        command("close_active")
        with pytest.raises(DiaError) as closed:
            client.request("get_document", document_id=did)
        assert closed.value.code == "STALE_DOCUMENT_REFERENCE"
        client.request("list_documents")  # prune closed generation entries
        assert_bounded(settled(command))
    final = settled(command)
    if final["native_identity_entries"] is not None:
        assert final["native_identity_entries"] == baseline["native_identity_entries"]
    assert final["fds"] <= baseline["fds"] + 2
    assert final["rss_kib"] - baseline["rss_kib"] < 64 * 1024
    print("FILE_ENDURANCE " + json.dumps({"roundtrips": 20, "before": baseline, "after": final}))


def test_live_queued_connection_shutdown_releases_resources(endurance_gui):
    client, command, process, path = endurance_gui
    did = client.request("get_active_document")["document"]["document_id"]
    generation = client.request("get_document", document_id=did)["generation"]
    ticket = client.request("prepare_operation")["request_id"]
    initial_objects = settled(command)["visible_objects"]
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(str(path))
        sock.sendall(encode({"protocol_version": VERSION, "action": "handshake"}, 16384))
        with sock.makefile("rb") as stream:
            assert "result" in decode(stream.readline(1048576), 1048576)
            command("hold_dispatch")
            sock.sendall(
                encode(
                    {
                        "protocol_version": VERSION,
                        "action": "apply_commands",
                        "request_id": ticket,
                        "document_id": did,
                        "expected_generation": generation,
                        "commands": [{"op": "create", "type": "Standard - Box", "x": 10, "y": 10}],
                    },
                    16384,
                )
            )
            queued = wait_for(lambda: s if (s := command("stats")["listener"])["queue"] else None)
            assert queued["clients"] == 1 and queued["sources"] == 4
            assert command("stats", receipt_id=ticket)["receipt"]["state"] == "queued"
            result = command("stop_listener", receipt_id=ticket)
            assert result["receipt"]["state"] == "failed"
            assert result["receipt"]["outcome"] == "not_started"
            stopped = result["listener"]
            assert stopped["visible_objects"] == initial_objects
            assert stopped["closed"]
            assert stopped["clients"] == stopped["queue"] == stopped["sources"] == 0
            assert not path.exists()
            assert stream.read(1) == b""
    with pytest.raises(DiaError) as disconnected:
        client.request("handshake")
    assert disconnected.value.code == "LIVE_BACKEND_UNAVAILABLE"
    command("quit")
    process.wait(timeout=10)


def test_live_gui_delete_race_and_competing_history(endurance_gui):
    client, command, _, path = endurance_gui
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    oid = client.request("list_objects", document_id=did)["items"][0]["object_id"]
    generation = client.request("get_document", document_id=did)["generation"]
    ticket = client.request("prepare_operation")["request_id"]
    command("delete")
    with pytest.raises(DiaError) as stale:
        client.request(
            "apply_commands",
            request_id=ticket,
            document_id=did,
            expected_generation=generation,
            commands=[{"op": "move", "object_id": oid, "x": 99, "y": 99}],
        )
    assert stale.value.code == "GENERATION_CONFLICT"
    with pytest.raises(DiaError) as detached:
        perform(
            client,
            "apply_commands",
            did,
            commands=[{"op": "move", "object_id": oid, "x": 99, "y": 99}],
        )
    assert detached.value.code == "STALE_OBJECT_REFERENCE"
    command("restore")
    perform(
        client,
        "apply_commands",
        did,
        commands=[{"op": "create", "type": "Standard - Box", "x": 1, "y": 1}],
    )
    generation = client.request("get_document", document_id=did)["generation"]
    tickets = [client.request("prepare_operation")["request_id"] for _ in range(2)]

    def undo(ticket):
        try:
            return LiveClient(path).request(
                "history",
                document_id=did,
                request_id=ticket,
                expected_generation=generation,
                direction="undo",
            )
        except DiaError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(undo, tickets))
    assert sum(isinstance(value, dict) and value["history"] for value in outcomes) == 1
    assert outcomes.count("GENERATION_CONFLICT") == 1
    assert client.request("list_objects", document_id=did)["total"] == 8


def test_mcp_process_restart_and_explicit_dia_reconnect(endurance_gui, tmp_path):
    import asyncio
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    client, command, process, path = endurance_gui
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    original_session = client.request("handshake")["session_id"]

    def parameters(endpoint):
        return StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "dia_mcp.server",
                "--workspace",
                str(tmp_path / "stdio-output"),
                "--live-socket",
                str(endpoint),
            ],
            env={key: value for key, value in os.environ.items() if key in {"PATH", "PYTHONPATH"}},
        )

    async def first_mcp():
        async with stdio_client(parameters(path)) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("live_get_document", {"document_id": did})
                assert not result.isError
                return json.loads(result.content[0].text)

    assert asyncio.run(first_mcp())["document_id"] == did

    async def restarted_mcp():
        # A fresh external MCP process attaches to the existing Dia session.
        async with stdio_client(parameters(path)) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("live_get_document", {"document_id": did})
                assert not result.isError
                assert json.loads(result.content[0].text)["session_id"] == original_session
                command("quit")
                process.wait(timeout=10)
                fresh_root = tmp_path / "r"
                fresh_root.mkdir()
                replacement = gui.__wrapped__(fresh_root)
                try:
                    fresh_client, fresh_command, _, fresh_path = next(replacement)
                    assert fresh_client.request("handshake")["session_id"] != original_session
                    with pytest.raises(DiaError) as wrong_session:
                        fresh_client.request("get_document", document_id=did)
                    assert wrong_session.value.code == "WRONG_SESSION"
                    # Existing MCP stays bound to its explicit, now dead endpoint.
                    unavailable = await session.call_tool("live_get_document", {"document_id": did})
                    assert unavailable.isError
                    assert "LIVE_BACKEND_UNAVAILABLE" in unavailable.content[0].text
                    async with stdio_client(parameters(fresh_path)) as (new_reader, new_writer):
                        async with ClientSession(new_reader, new_writer) as new_session:
                            await new_session.initialize()
                            documents = await new_session.call_tool("live_list_documents", {})
                            assert not documents.isError
                            assert all(
                                item["document_id"] != did
                                for item in json.loads(documents.content[0].text)["items"]
                            )
                    fresh_command("quit")
                finally:
                    replacement.close()

    asyncio.run(restarted_mcp())


def test_live_document_close_while_mutation_is_queued(endurance_gui):
    client, command, _, path = endurance_gui
    command("create")
    document = client.request("get_active_document")["document"]
    did, generation = document["document_id"], document["generation"]
    ticket = client.request("prepare_operation")["request_id"]
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(str(path))
        sock.sendall(encode({"protocol_version": VERSION, "action": "handshake"}, 16384))
        with sock.makefile("rb") as stream:
            assert "result" in decode(stream.readline(1048576), 1048576)
            command("hold_dispatch")
            sock.sendall(
                encode(
                    {
                        "protocol_version": VERSION,
                        "action": "apply_commands",
                        "request_id": ticket,
                        "document_id": did,
                        "expected_generation": generation,
                        "commands": [{"op": "create", "type": "Standard - Box", "x": 10, "y": 10}],
                    },
                    16384,
                )
            )
            wait_for(lambda: command("stats")["listener"]["queue"] == 1)
            assert command("stats", receipt_id=ticket)["receipt"]["state"] == "queued"
            closed = command("close")["listener"]
            assert closed["queue"] == 1
            command("resume_dispatch")
            result = decode(stream.readline(1048576), 1048576)
            assert result["error"]["code"] == "STALE_DOCUMENT_REFERENCE"
            assert result["error"]["outcome"] == "not_started"
    receipt = client.request("get_operation", request_id=ticket)
    assert receipt["state"] == "failed" and receipt["outcome"] == "not_started"
    remaining = client.request("list_documents")["items"]
    assert all(doc["document_id"] != did for doc in remaining)
    after = settled(command)
    assert after["visible_documents"] == closed["visible_documents"]
    assert after["visible_objects"] == closed["visible_objects"]
    assert_bounded(after)
    with pytest.raises(DiaError) as stale:
        client.request("get_document", document_id=did)
    assert stale.value.code == "STALE_DOCUMENT_REFERENCE"
