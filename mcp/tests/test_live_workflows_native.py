"""M9 agent workflows against real native state, static plans and stdio surfaces."""

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_live_files_native import perform
from test_live_native import gui  # noqa: F401

from dia_mcp.errors import DiaError

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia"),
]


@pytest.fixture
def workflows_gui(monkeypatch, request):
    monkeypatch.setenv("DIA_MCP_WRITE", "1")
    client, command, _, _ = request.getfixturevalue("gui")
    command("create")
    did = client.request("get_active_document")["document"]["document_id"]
    return client, command, did


def snapshot(client, did):
    document = client.request("get_document", document_id=did)
    objects = client.request("list_objects", document_id=did)["items"]
    return {
        "generation": document["generation"],
        "modified": document["document"]["modified"],
        "objects": [(obj["object_id"], obj["position"], obj["bounds"]) for obj in objects],
    }


def test_native_compact_selection_pagination_neighborhood_and_evidence(workflows_gui):
    client, command, did = workflows_gui
    perform(
        client,
        "apply_commands",
        did,
        commands=[
            {"op": "create", "type": "Standard - Box", "x": i * 3, "y": 30} for i in range(4)
        ],
    )
    command("select_all")
    before = snapshot(client, did)
    context = client.request("get_current_context")
    assert context["document"]["document_id"] == did
    assert context["document"]["generation"] == before["generation"]
    assert context["object_count"] == 12
    assert context["active_layer"]
    selection = context["selection"]
    assert selection["total"] == 12 and selection["next_offset"] == 8
    page1 = client.request("inspect_selection", document_id=did)
    page2 = client.request("inspect_selection", document_id=did, offset=8, limit=8)
    assert page1["generation"] == page2["generation"] == before["generation"]
    assert page1["total"] == page2["total"] == 12
    assert len(page1["items"]) == 8 and len(page2["items"]) == 4
    assert page2["next_offset"] is None
    selected = page1["items"] + page2["items"]
    assert len({item["object_id"] for item in selected}) == 12
    assert all("properties" in item and "connections" in item for item in selected)
    assert any(item["type"] == "Live - Unfamiliar" for item in selected)
    with pytest.raises(DiaError):
        client.request("inspect_selection", document_id=did, limit=9)
    line = next(item for item in selected if item["type"] == "Standard - Line")
    neighborhood = client.request(
        "inspect_object_neighborhood", document_id=did, object_id=line["object_id"]
    )
    assert neighborhood["generation"] == before["generation"]
    assert neighborhood["object"]["object_id"] == line["object_id"]
    assert neighborhood["neighbors"]["total"] == 1
    assert neighborhood["neighbors"]["items"][0]["type"] == "UML - Class"
    assert neighborhood["neighbors"]["next_offset"] is None
    analysis = client.request("analyze_document", document_id=did)["analysis"]
    assert analysis["classification"] == "mixed"
    custom = next(item for item in selected if item["type"] == "Live - Unfamiliar")
    assert custom["object_id"] in analysis["unknown_objects"]
    assert all("basis" in item for item in analysis["evidence"])
    assert analysis["limitations"]
    levels = analysis["evidence_levels"]
    assert set(levels) == {"native_facts", "derived_structure", "heuristics"}
    assert levels["derived_structure"]["basis"] == "native_attachments_in_supplied_subgraph"
    assert levels["native_facts"]["layer_object_counts"]
    assert levels["heuristics"]["bbox_overlaps"]["meaning"]
    assert snapshot(client, did) == before


def test_native_plans_validation_preserve_state_and_apply_uses_gui_history(workflows_gui):
    client, command, did = workflows_gui
    # The trusted fixture attaches a handle without moving it. Use the native
    # command to synchronize its geometry before comparing reversible edits.
    items = client.request("list_objects", document_id=did)["items"]
    klass = next(item["object_id"] for item in items if item["type"] == "UML - Class")
    line = next(item["object_id"] for item in items if item["type"] == "Standard - Line")
    perform(
        client,
        "apply_commands",
        did,
        commands=[
            {
                "op": "connect",
                "object_id": line,
                "handle": 0,
                "target_id": klass,
                "point": 0,
            }
        ],
    )
    command("select_all")
    before = snapshot(client, did)
    plans = []
    for intent, options in (
        ("move", {"dx": 2, "dy": 3}),
        ("layout", {"mode": "left"}),
    ):
        planned = client.request("plan_selection", document_id=did, intent=intent, options=options)
        assert planned["generation"] == before["generation"]
        plan = planned
        assert plan["commands"]
        checked = client.request(
            "validate_commands",
            document_id=did,
            expected_generation=before["generation"],
            commands=plan["commands"],
        )
        assert checked["valid"] is True and checked["issues"] == []
        assert type(checked["complete"]) is bool and isinstance(checked["deferred"], list)
        assert checked["complete"] == (checked["deferred_count"] == 0)
        assert checked["mutates"] is False
        assert snapshot(client, did) == before
        plans.append(plan)
    ticket = client.request("prepare_operation")["request_id"]
    changed = client.request(
        "apply_commands",
        document_id=did,
        request_id=ticket,
        expected_generation=before["generation"],
        commands=plans[0]["commands"],
    )
    assert changed["committed"]
    assert snapshot(client, did)["objects"] != before["objects"]
    command("undo")
    assert snapshot(client, did)["objects"] == before["objects"]
    command("redo")
    assert snapshot(client, did)["objects"] != before["objects"]
    command("undo")
    # The only earlier transaction is the explicit fixture normalization.
    # Read/planning/static validation created no additional undo entries.
    assert perform(client, "history", did, direction="undo")["history"] is True
    assert perform(client, "history", did, direction="undo")["history"] is False


def test_native_validation_reports_property_and_point_issues_without_mutation(workflows_gui):
    client, command, did = workflows_gui
    items = client.request("list_objects", document_id=did)["items"]
    klass = next(item["object_id"] for item in items if item["type"] == "UML - Class")
    line = next(item["object_id"] for item in items if item["type"] == "Standard - Line")
    before = snapshot(client, did)
    property_plan = client.request(
        "plan_selection",
        document_id=did,
        intent="set_properties",
        options={"properties": {"name": "Review before applying"}},
    )
    assert property_plan["commands"] == [
        {
            "op": "set_properties",
            "object_id": klass,
            "properties": {"name": "Review before applying"},
        }
    ]
    assert (
        client.request(
            "validate_commands",
            document_id=did,
            expected_generation=before["generation"],
            commands=property_plan["commands"],
        )["valid"]
        is True
    )
    assert snapshot(client, did) == before
    for commands in (
        [
            {
                "op": "set_properties",
                "object_id": klass,
                "properties": {"definitely_missing_property": "invalid"},
            }
        ],
        [{"op": "connect", "object_id": line, "handle": 0, "target_id": klass, "point": 255}],
    ):
        checked = client.request(
            "validate_commands",
            document_id=did,
            expected_generation=before["generation"],
            commands=commands,
        )
        assert checked["valid"] is False and checked["issues"]
        assert snapshot(client, did) == before
    command("move")
    with pytest.raises(DiaError) as conflict:
        client.request(
            "validate_commands",
            document_id=did,
            expected_generation=before["generation"],
            commands=[{"op": "move", "object_id": klass, "x": 1, "y": 2}],
        )
    assert conflict.value.code == "GENERATION_CONFLICT"


def test_native_workflow_stdio_resources_prompt_and_readonly_annotations(workflows_gui, tmp_path):
    client, _, did = workflows_gui
    before = snapshot(client, did)

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "dia_mcp.server",
                "--workspace",
                str(tmp_path / "out"),
                "--live-socket",
                client.path,
            ],
            env={key: value for key, value in os.environ.items() if key in {"PATH", "PYTHONPATH"}},
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                for name in (
                    "live_get_current_context",
                    "live_inspect_selection",
                    "live_inspect_object_neighborhood",
                    "live_plan_selection",
                    "live_validate_commands",
                ):
                    assert tools[name].annotations.readOnlyHint is True
                context = await session.read_resource("dia://live/context")
                assert json.loads(context.contents[0].text)["document"]["document_id"] == did
                capabilities = await session.read_resource("dia://live/capabilities")
                assert {"context.read", "plans.read", "commands.validate"} <= set(
                    json.loads(capabilities.contents[0].text)["capabilities"]
                )
                prompt = await session.get_prompt("inspect_live_selection", {})
                assert prompt.messages
                result = await session.call_tool("live_inspect_selection", {"document_id": did})
                assert not result.isError
                assert json.loads(result.content[0].text)["generation"] == before["generation"]

    asyncio.run(run())
    assert snapshot(client, did) == before
