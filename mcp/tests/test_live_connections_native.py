"""Evidence for native attachments across palettes, dynamic ports and group boundaries."""

import os

import pytest
from test_live_files_native import perform
from test_live_native import gui  # noqa: F401

from dia_mcp.errors import DiaError

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia"),
]


@pytest.fixture
def connections_gui(monkeypatch, request):
    monkeypatch.setenv("DIA_MCP_WRITE", "1")
    return request.getfixturevalue("gui")


def connections(client, did, oid):
    return client.request("get_connections", document_id=did, object_id=oid)


def apply(client, did, *commands):
    return perform(client, "apply_commands", did, commands=list(commands))


def test_heterogeneous_targets_and_connector_handles(connections_gui):
    client, command, _, _ = connections_gui
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    targets = [
        obj
        for obj in client.request("list_objects", document_id=did)["items"]
        if obj["type"] != "Standard - Line"
    ]
    connector_types = [
        "Standard - Line",
        "Standard - PolyLine",
        "Standard - ZigZagLine",
        "Standard - BezierLine",
        "UML - Association",
        "Database - Reference",
    ]
    evidence = []
    for index, target in enumerate(targets):
        kind = connector_types[index % len(connector_types)]
        oid = apply(client, did, {"op": "create", "type": kind, "x": 5, "y": 30})["created"][0]
        ports = connections(client, did, target["object_id"])["connection_points"]
        assert ports, target["type"]
        handles = connections(client, did, oid)["handles"]
        handle = next(h["index"] for h in handles if h["connect_type"] != 0)
        point = len(ports) - 1 if len(ports) < 3 else 1
        apply(
            client,
            did,
            {
                "op": "connect",
                "object_id": oid,
                "handle": handle,
                "target_id": target["object_id"],
                "point": point,
            },
        )
        attached = connections(client, did, oid)["handles"][handle]
        assert attached["attached_to"] == {
            "object_id": target["object_id"],
            "connection_point": point,
        }
        assert attached["position"] == pytest.approx(ports[point]["position"])
        assert (
            oid
            in connections(client, did, target["object_id"])["connection_points"][point][
                "connected_objects"
            ]
        )
        assert perform(client, "history", did, direction="undo")["history"]
        assert connections(client, did, oid)["handles"][handle]["attached_to"] is None
        assert perform(client, "history", did, direction="redo")["history"]
        assert connections(client, did, oid)["handles"][handle]["attached_to"] is not None
        apply(client, did, {"op": "disconnect", "object_id": oid, "handle": handle})
        assert connections(client, did, oid)["handles"][handle]["attached_to"] is None
        evidence.append((kind, target["type"], handle, point))
    print("HETEROGENEOUS_ATTACHMENTS", evidence)


def test_dynamic_zero_ports_group_members_and_nonconnectable_handles(connections_gui):
    client, command, _, _ = connections_gui
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    items = client.request("list_objects", document_id=did)["items"]
    klass = next(o for o in items if o["type"] == "UML - Class")["object_id"]
    before = len(connections(client, did, klass)["connection_points"])
    command("dynamic_ports")
    after = connections(client, did, klass)["connection_points"]
    assert len(after) == before + 4
    line, zero, box = apply(
        client,
        did,
        {"op": "create", "type": "Standard - Line", "x": 0, "y": 30},
        {"op": "create", "type": "Live - ZeroPort", "x": 10, "y": 30},
        {"op": "create", "type": "Standard - Box", "x": 20, "y": 30},
    )["created"]
    dynamic_point = len(after) - 2  # member port before final whole-class mainpoint
    apply(
        client,
        did,
        {
            "op": "connect",
            "object_id": line,
            "handle": 0,
            "target_id": klass,
            "point": dynamic_point,
        },
    )
    assert connections(client, did, line)["handles"][0]["attached_to"] == {
        "object_id": klass,
        "connection_point": dynamic_point,
    }
    assert connections(client, did, zero)["connection_points"] == []
    nonconnectable = next(
        h["index"] for h in connections(client, did, box)["handles"] if h["connect_type"] == 0
    )
    for rejected in (
        {"op": "connect", "object_id": line, "handle": 0, "target_id": zero, "point": 0},
        {
            "op": "connect",
            "object_id": box,
            "handle": nonconnectable,
            "target_id": klass,
            "point": 0,
        },
        {"op": "connect", "object_id": line, "handle": 255, "target_id": klass, "point": 0},
        {"op": "connect", "object_id": line, "handle": 0, "target_id": klass, "point": 255},
    ):
        with pytest.raises(DiaError) as error:
            apply(client, did, rejected)
        assert error.value.code == "NATIVE_COMMAND_FAILED"
        assert (
            connections(client, did, line)["handles"][0]["attached_to"]["connection_point"]
            == dynamic_point
        )
    command("group")
    grouped = client.request("list_objects", document_id=did)["items"]
    member = next(o for o in grouped if o["group_id"] is not None)
    assert connections(client, did, member["object_id"])["connection_points"]
    with pytest.raises(DiaError) as error:
        apply(
            client,
            did,
            {
                "op": "connect",
                "object_id": line,
                "handle": 0,
                "target_id": member["object_id"],
                "point": 0,
            },
        )
    assert error.value.code == "UNSUPPORTED_OPERATION"
    assert connections(client, did, line)["handles"][0]["attached_to"]["object_id"] == klass
