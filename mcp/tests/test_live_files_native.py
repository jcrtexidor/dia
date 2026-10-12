"""Native serializer round trip through the actual live socket and GTK editor."""

import os
from collections import Counter

import pytest
from test_live_native import gui  # noqa: F401

from dia_mcp.errors import DiaError

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires Dia"),
]


@pytest.fixture
def files_gui(monkeypatch, tmp_path, request):
    monkeypatch.setenv("DIA_MCP_WRITE", "1")
    monkeypatch.setenv("DIA_MCP_FILES_ROOT", str(tmp_path))
    return request.getfixturevalue("gui")


def perform(client, action, did=None, **kwargs):
    receipt = client.request("prepare_operation")["request_id"]
    if did is not None:
        generation = client.request("get_document", document_id=did)["generation"]
        kwargs.update(document_id=did, expected_generation=generation)
    return client.request(action, request_id=receipt, **kwargs)


def test_native_files_round_trip_and_failure_state(files_gui, tmp_path):
    client, command, _, _ = files_gui
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    command("group")
    command("layer")
    before = client.request("list_objects", document_id=did)["items"]
    types = Counter(o["type"] for o in before)
    assert "Live - Unfamiliar" in types
    assert any(o["group_id"] for o in before)
    layers = client.request("list_layers", document_id=did)["items"]
    assert len(layers) == 2
    path = tmp_path / "native-preserved.dia"
    saved = perform(client, "save_document_as", did, path=str(path))
    assert saved["saved"] and path.stat().st_size > 0
    summary = client.request("get_document", document_id=did)["document"]
    assert summary["filename"] == str(path) and not summary["modified"]

    # Real editor operation establishes dirty state; export must preserve it.
    custom = next(o for o in before if o["type"] == "Live - Unfamiliar")
    perform(
        client,
        "apply_commands",
        did,
        commands=[
            {
                "op": "move",
                "object_id": custom["object_id"],
                "x": custom["position"]["x"] + 1,
                "y": custom["position"]["y"] + 1,
            }
        ],
    )
    assert client.request("get_document", document_id=did)["document"]["modified"]
    for fmt in ("dia", "svg", "png"):
        exported = tmp_path / f"exported.{fmt}"
        result = perform(client, "export_document", did, path=str(exported), format=fmt)
        assert not result["saved"] and exported.stat().st_size > 0
        assert client.request("get_document", document_id=did)["document"]["modified"]
    original = path.read_bytes()
    with pytest.raises(DiaError) as failed:
        perform(client, "save_document", did)
    assert failed.value.code == "FILE_EXISTS"
    assert path.read_bytes() == original
    assert client.request("get_document", document_id=did)["document"]["modified"]
    # Save As failure must leave the current filename and dirty flag untouched.
    with pytest.raises(DiaError):
        perform(client, "save_document_as", did, path=str(tmp_path / "missing" / "x.dia"))
    summary = client.request("get_document", document_id=did)["document"]
    assert summary["filename"] == str(path) and summary["modified"]
    command("undo")
    perform(client, "save_document", did, overwrite=True)
    assert not client.request("get_document", document_id=did)["document"]["modified"]

    opened = perform(client, "open_document", path=str(path))["document"]
    reopened = opened["document_id"]
    assert reopened != did and not opened["modified"]
    objects = client.request("list_objects", document_id=reopened)["items"]
    assert Counter(o["type"] for o in objects) == types
    assert sum(bool(o["group_id"]) for o in objects) == sum(bool(o["group_id"]) for o in before)
    reloaded_layers = client.request("list_layers", document_id=reopened)["items"]
    assert [(x["name"], x["visible"]) for x in reloaded_layers] == [
        (x["name"], x["visible"]) for x in layers
    ]
    line = next(o for o in objects if o["type"] == "Standard - Line")
    connection = client.request(
        "get_connections", document_id=reopened, object_id=line["object_id"]
    )["handles"][0]["attached_to"]
    assert connection is not None
    owner = next(o for o in objects if o["object_id"] == connection["object_id"])
    assert owner["type"] == "UML - Class"
    dependencies = client.request("get_dependencies", document_id=reopened)
    assert dependencies["complete"] is False and isinstance(dependencies["items"], list)
    assert all(item["exists"] is None for item in dependencies["items"])
    assert client.request("get_document", document_id=did)["document"]["filename"] == str(path)
    assert not list(tmp_path.glob(".dia-live-*"))
    command("quit")
