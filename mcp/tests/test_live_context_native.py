"""Real transport ordering, receipts, context surfaces and bounded performance sample."""

import asyncio
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_live_native import gui  # noqa: F401
from test_live_transactions_native import apply, create, writable_gui  # noqa: F401

from dia_mcp.errors import DiaError
from dia_mcp.live.client import LiveClient

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires Dia"),
]


def test_native_operation_fencing_and_receipts(writable_gui):  # noqa: F811
    client, did, _ = writable_gui
    generation = client.request("get_document", document_id=did)["generation"]
    ticket = client.request("prepare_operation")["request_id"]
    args = dict(
        document_id=did,
        expected_generation=generation,
        request_id=ticket,
        commands=[create("Standard - Box")],
    )
    result = client.request("apply_commands", **args)
    assert client.request("apply_commands", **args) == result
    assert client.request("get_operation", request_id=ticket)["result"] == result
    assert client.request("list_objects", document_id=did)["total"] == 1
    with pytest.raises(DiaError) as error:
        client.request("apply_commands", **{**args, "commands": [create("Standard - Line")]})
    assert error.value.code == "OPERATION_CONFLICT"
    second = client.request("prepare_operation")["request_id"]
    with pytest.raises(DiaError) as error:
        client.request("apply_commands", **{**args, "request_id": second})
    assert error.value.code == "GENERATION_CONFLICT"
    assert client.request("get_operation", request_id=second)["status"] == "failed"
    # Separate clients contend on the same observed generation: precisely one wins.
    generation = client.request("get_document", document_id=did)["generation"]
    tickets = [client.request("prepare_operation")["request_id"] for _ in range(2)]

    def contender(request_id):
        try:
            return LiveClient(client.path).request(
                "apply_commands",
                **{**args, "expected_generation": generation, "request_id": request_id},
            )["committed"]
        except DiaError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, tickets))
    assert results.count(True) == 1 and results.count("GENERATION_CONFLICT") == 1
    assert client.request("list_objects", document_id=did)["total"] == 2


def test_native_context_stdio_and_performance(writable_gui, tmp_path):  # noqa: F811
    client, did, command = writable_gui
    for batch in range(4):
        apply(client, did, *(create("Standard - Box", x=i * 3, y=batch * 3) for i in range(64)))
    timings = []
    for _ in range(20):
        start = time.monotonic()
        result = client.request("list_objects", document_id=did, limit=100)
        timings.append((time.monotonic() - start) * 1000)
        assert result["total"] == 256 and result["next_offset"] == 100
    print(
        "LIVE_BENCHMARK",
        json.dumps(
            {
                "objects": 256,
                "samples": 20,
                "list_page_median_ms": round(statistics.median(timings), 3),
                "list_page_p95_ms": round(sorted(timings)[18], 3),
            }
        ),
    )
    summary = client.request("summarize_document", document_id=did)
    assert summary["object_count"] == 256
    analysis = client.request("analyze_document", document_id=did)["analysis"]
    assert len(analysis["isolated_objects"]) == 256
    assert command("status")["ok"]

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "dia_mcp.server",
                "--workspace",
                str(tmp_path / "out"),
                "--live-socket",
                client.path,
            ],
            env={k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH"}},
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                resources = await session.list_resources()
                assert any(str(r.uri) == "dia://live/documents" for r in resources.resources)
                resource = await session.read_resource("dia://live/documents")
                assert json.loads(resource.contents[0].text)["items"]
                resource = await session.read_resource(f"dia://live/documents/{did}/summary")
                assert json.loads(resource.contents[0].text)["object_count"] == 256
                prompt = await session.get_prompt("explain_live_diagram", {"document_id": did})
                assert "Do not mutate" in prompt.messages[0].content.text
                planned = await session.call_tool(
                    "live_plan_objects",
                    {"domain": "flowchart", "nodes": [{"x": 0, "y": 0, "label": "Start"}]},
                )
                assert not planned.isError
                planned = json.loads(planned.content[0].text)
                receipt = await session.call_tool("live_prepare_operation", {})
                ticket = json.loads(receipt.content[0].text)["request_id"]
                generation = client.request("get_document", document_id=did)["generation"]
                changed = await session.call_tool(
                    "live_apply_commands",
                    {
                        "document_id": did,
                        "expected_generation": generation,
                        "request_id": ticket,
                        "commands": planned["commands"],
                    },
                )
                assert not changed.isError, changed
                result = json.loads(changed.content[0].text)
                assert result["committed"] and result["created"]

    asyncio.run(run())
    with pytest.raises(DiaError) as error:
        client.request("analyze_document", document_id=did)
    assert error.value.code == "LIVE_LIMIT_EXCEEDED"
