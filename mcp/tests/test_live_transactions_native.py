"""Native GUI transactions through the real live socket, including failure recovery."""

import os

import pytest
from test_live_native import gui  # noqa: F401

from dia_mcp.errors import DiaError

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires rebuilt Dia"),
]


@pytest.fixture
def writable_gui(monkeypatch, request):
    monkeypatch.setenv("DIA_MCP_WRITE", "1")
    client, command, process, path = request.getfixturevalue("gui")
    assert client.request("handshake")["writable"]
    document = client.request("get_active_document")["document"]
    assert document is not None
    return client, document["document_id"], command


def objects(client, did):
    return client.request("list_objects", document_id=did)["items"]


def mutate(client, did, action="apply_commands", **arguments):
    generation = client.request("get_document", document_id=did)["generation"]
    ticket = client.request("prepare_operation")["request_id"]
    return client.request(
        action,
        document_id=did,
        request_id=ticket,
        expected_generation=generation,
        **arguments,
    )


def apply(client, did, *commands):
    return mutate(client, did, commands=list(commands))


def history(client, did, direction):
    return mutate(client, did, "history", direction=direction)["history"]


def create(kind, x=1, y=2, **extra):
    return {"op": "create", "type": kind, "x": x, "y": y, **extra}


def details(client, did, oid):
    return client.request("get_object", document_id=did, object_id=oid, properties=True)["object"]


def property_value(obj, name):
    return next(p["value"] for p in obj["properties"]["items"] if p["name"] == name)


def geometry(client, did):
    # Identity may be invalidated after native detach/reattach. Compare actual state.
    return [(o["type"], o["position"], o["bounds"]) for o in objects(client, did)]


def test_native_heterogeneous_create_uses_shared_gui_history(writable_gui):
    client, did, command = writable_gui
    baseline = geometry(client, did)
    assert history(client, did, "undo") is False
    kinds = [
        "UML - Class",
        "Flowchart - Box",
        "ER - Entity",
        "Database - Table",
        "Cisco - PC",
        "Circuit - Horizontal Resistor",
        "Live - Unfamiliar",
        "Live - ZeroPort",
    ]
    result = apply(client, did, *(create(kind, index * 6, 4) for index, kind in enumerate(kinds)))
    assert result["committed"] and len(result["created"]) == len(kinds)
    assert [obj["type"] for obj in objects(client, did)] == kinds
    created_geometry = geometry(client, did)
    # GTK's ordinary Undo/Redo menu must operate on exactly the same transaction.
    command("undo")
    assert geometry(client, did) == baseline
    command("redo")
    assert geometry(client, did) == created_geometry
    assert history(client, did, "undo") is True
    assert geometry(client, did) == baseline
    assert history(client, did, "redo") is True
    assert geometry(client, did) == created_geometry


def test_native_property_move_atomic_and_failed_batches_preserve_redo(writable_gui):
    client, did, _ = writable_gui
    oid = apply(client, did, create("UML - Class", properties={"name": "Before"}))["created"][0]
    before = details(client, did, oid)
    apply(
        client,
        did,
        {"op": "move", "object_id": oid, "x": 25, "y": 19},
        {"op": "set_properties", "object_id": oid, "properties": {"name": "After"}},
    )
    after = details(client, did, oid)
    assert after["position"] != before["position"]
    assert property_value(after, "name") == "After"
    assert history(client, did, "undo") is True
    restored = objects(client, did)[0]["object_id"]
    undo_state = details(client, did, restored)
    assert undo_state["position"] == before["position"]
    assert property_value(undo_state, "name") == "Before"
    # Force failure inside C after a successful native move, with a redo pending.
    with pytest.raises(DiaError) as failure:
        apply(
            client,
            did,
            {"op": "move", "object_id": restored, "x": 80, "y": 60},
            {
                "op": "set_properties",
                "object_id": restored,
                "properties": {"definitely_missing_property": "invalid"},
            },
        )
    assert failure.value.code == "NATIVE_COMMAND_FAILED"
    current = objects(client, did)[0]["object_id"]
    failed_state = details(client, did, current)
    assert failed_state["position"] == before["position"]
    assert property_value(failed_state, "name") == "Before"
    assert history(client, did, "redo") is True
    redone = details(client, did, objects(client, did)[0]["object_id"])
    assert redone["position"] == after["position"]
    assert property_value(redone, "name") == "After"
    assert history(client, did, "undo") is True
    before_failed_create = geometry(client, did)
    with pytest.raises(DiaError) as failure:
        apply(
            client,
            did,
            create("Standard - Box"),
            create("UML - Class", properties={"definitely_missing_property": "invalid"}),
        )
    assert failure.value.code == "NATIVE_COMMAND_FAILED"
    assert geometry(client, did) == before_failed_create
    assert history(client, did, "redo") is True
    assert (
        property_value(details(client, did, objects(client, did)[0]["object_id"]), "name")
        == "After"
    )


def test_native_connections_disconnect_delete_and_history(writable_gui):
    client, did, _ = writable_gui
    created = apply(client, did, create("Standard - Box", 10, 10), create("Standard - Line", 0, 0))
    box, line = created["created"]

    def attachment():
        return client.request("get_connections", document_id=did, object_id=line)["handles"][0][
            "attached_to"
        ]

    assert attachment() is None
    apply(
        client, did, {"op": "connect", "object_id": line, "handle": 0, "target_id": box, "point": 0}
    )
    assert attachment() == {"object_id": box, "connection_point": 0}
    assert history(client, did, "undo") is True
    assert attachment() is None
    assert history(client, did, "redo") is True
    assert attachment()["object_id"] == box
    apply(client, did, {"op": "disconnect", "object_id": line, "handle": 0})
    assert attachment() is None
    assert history(client, did, "undo") is True
    assert attachment()["object_id"] == box
    assert history(client, did, "redo") is True
    apply(client, did, {"op": "delete", "object_id": line})
    assert len(objects(client, did)) == 1
    assert history(client, did, "undo") is True
    assert len(objects(client, did)) == 2
    assert history(client, did, "redo") is True
    assert len(objects(client, did)) == 1


def test_native_layout_modes_are_reversible(writable_gui):
    client, did, _ = writable_gui
    apply(
        client,
        did,
        create("Standard - Box", 1, 2),
        create("Standard - Box", 8, 13),
        create("Standard - Box", 23, 30),
    )
    baseline = geometry(client, did)
    for mode in (
        "left",
        "center",
        "right",
        "top",
        "middle",
        "bottom",
        "distribute_horizontal",
        "distribute_vertical",
    ):
        ids = [obj["object_id"] for obj in objects(client, did)]
        apply(client, did, {"op": "layout", "object_ids": ids, "mode": mode})
        aligned = objects(client, did)
        horizontal = mode in {"left", "center", "right", "distribute_horizontal"}
        start, end = ("left", "right") if horizontal else ("top", "bottom")
        bounds = [obj["bounds"] for obj in aligned]
        if mode.startswith("distribute"):
            ordered = sorted(bounds, key=lambda box: box[start])
            gaps = [b[start] - a[end] for a, b in zip(ordered, ordered[1:])]
            assert gaps[0] == pytest.approx(gaps[1])
        else:
            values = [
                (box[start] + box[end]) / 2
                if mode in {"center", "middle"}
                else box[end]
                if mode in {"right", "bottom"}
                else box[start]
                for box in bounds
            ]
            assert values == pytest.approx([values[0]] * 3)
        assert history(client, did, "undo") is True
        assert geometry(client, did) == baseline


def test_native_property_resize_updates_connected_geometry_and_rolls_back(writable_gui):
    client, did, _ = writable_gui
    created = apply(
        client,
        did,
        create("UML - Class", properties={"name": "A"}),
        create("Standard - Line", 10, 10),
        create("Live - ZeroPort", 20, 20),
    )["created"]
    box, line, zero = created
    zero_connections = client.request("get_connections", document_id=did, object_id=zero)
    assert zero_connections["connection_points"] == []
    with pytest.raises(DiaError) as failure:
        apply(
            client,
            did,
            {"op": "connect", "object_id": line, "handle": 0, "target_id": zero, "point": 0},
        )
    assert failure.value.code == "NATIVE_COMMAND_FAILED"
    # A top-edge connection moves when the class name grows in width.
    point_index = 2
    apply(
        client,
        did,
        {"op": "connect", "object_id": line, "handle": 0, "target_id": box, "point": point_index},
    )

    def endpoints():
        source = client.request("get_connections", document_id=did, object_id=line)
        target = client.request("get_connections", document_id=did, object_id=box)
        handle = source["handles"][0]
        assert handle["attached_to"] == {"object_id": box, "connection_point": point_index}
        port = target["connection_points"][point_index]
        assert handle["position"] == pytest.approx(port["position"])
        return handle["position"], geometry(client, did)

    before = endpoints()
    name_change = {
        "op": "set_properties",
        "object_id": box,
        "properties": {"name": "A much wider class name for connection geometry"},
    }
    apply(client, did, name_change)
    grown = endpoints()
    assert grown[0] != before[0]
    assert history(client, did, "undo") is True
    assert endpoints() == before
    # Failure after the property edit must restore both box and attached line,
    # and must retain the successful property's pending redo.
    with pytest.raises(DiaError) as failure:
        apply(
            client,
            did,
            name_change,
            {
                "op": "set_properties",
                "object_id": box,
                "properties": {"definitely_missing_property": "invalid"},
            },
        )
    assert failure.value.code == "NATIVE_COMMAND_FAILED"
    assert endpoints() == before
    assert history(client, did, "redo") is True
    assert endpoints() == grown
