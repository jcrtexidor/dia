"""Exercise actual MCP initialize/list/call messages over an OS stdio subprocess."""

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia"),
]


def test_stdio_workflow(tmp_path):
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
                key: value
                for key, value in os.environ.items()
                if key in ("DISPLAY", "XAUTHORITY", "PATH", "PYTHONPATH", "LD_LIBRARY_PATH")
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "Dia operations"
                listing = await session.list_tools()
                tools = {tool.name: tool for tool in listing.tools}
                assert set(tools) == {
                    "get_capabilities",
                    "create_document",
                    "create_object",
                    "connect_objects",
                    "move_object",
                    "update_object",
                    "inspect_document",
                    "export_diagram",
                    "close_document",
                }
                assert tools["inspect_document"].annotations.readOnlyHint is True

                async def call(tool_name, **arguments):
                    result = await session.call_tool(tool_name, arguments)
                    assert not result.isError, result
                    return json.loads(result.content[0].text)

                doc = (await call("create_document", name="MCP real"))["document"]["id"]
                a = await call("create_object", document_id=doc, text="Crear", x=1, y=1)
                b = await call("create_object", document_id=doc, text="Exportar", x=8, y=1)
                await call(
                    "connect_objects", document_id=doc, source=a["object_id"], target=b["object_id"]
                )
                for format in ("dia", "svg", "png"):
                    exported = await call(
                        "export_diagram",
                        document_id=doc,
                        filename=f"protocol.{format}",
                        format=format,
                    )
                    assert exported["bytes"] > 100
                invalid = await session.call_tool(
                    "export_diagram",
                    {"document_id": doc, "filename": "../escape.svg", "format": "svg"},
                )
                assert invalid.isError
                assert "INVALID_ARGUMENT" in invalid.content[0].text
                # Errors must not damage the session or consume a new revision.
                state = await call("inspect_document", document_id=doc)
                assert state["document"]["revision"] == 3
                await call("close_document", document_id=doc)
                unknown = await session.call_tool("inspect_document", {"document_id": doc})
                assert unknown.isError

    asyncio.run(run())
