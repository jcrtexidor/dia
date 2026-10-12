"""The installed-facing Rust process owns MCP while Python holds diagram state."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dia_mcp.protocol_catalog import catalog as generated_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_protocol_catalog_matches_operations():
    catalog = json.loads((ROOT / "protocol-catalog.json").read_text())
    assert catalog == generated_catalog()


def test_rust_stdio_session(tmp_path):
    binary = ROOT / "rust/target/debug/dia-mcp"
    if not binary.is_file():
        binary = ROOT / "rust/target/release/dia-mcp"
    assert binary.is_file(), "Build the Rust transport before running tests"

    async def run():
        params = StdioServerParameters(
            command=str(binary),
            args=["--workspace", str(tmp_path), "--dia-binary", "/bin/true"],
            env={**os.environ, "DIA_MCP_PYTHON": sys.executable},
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "Dia operations"
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert "live_apply_commands" in tools
                assert "create_document" in tools
                created = await session.call_tool("create_document", {"name": "Rust bridge"})
                assert not created.isError
                document_id = json.loads(created.content[0].text)["document"]["id"]
                inspected = await session.call_tool(
                    "inspect_document", {"document_id": document_id}
                )
                assert not inspected.isError
                assert json.loads(inspected.content[0].text)["document"]["name"] == "Rust bridge"
                invalid = await session.call_tool("inspect_document", {"document_id": "missing"})
                assert invalid.isError
                assert len((await session.list_resources()).resources) == 3
                assert len((await session.list_prompts()).prompts) == 2

    asyncio.run(run())


@pytest.mark.native
@pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia")
def test_rust_native_snapshot(tmp_path):
    binary = ROOT / "rust/target/release/dia-mcp"

    async def run():
        params = StdioServerParameters(
            command=str(binary),
            args=[
                "--workspace",
                str(tmp_path),
                "--dia-binary",
                os.environ.get("DIA_BINARY", "dia"),
            ],
            env={**os.environ, "DIA_MCP_PYTHON": sys.executable},
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def call(name, arguments):
                    response = await session.call_tool(name, arguments)
                    assert not response.isError, response
                    return json.loads(response.content[0].text)

                created = await call("create_document", {"name": "Rust native"})
                document = created["document"]["id"]
                await call("create_object", {"document_id": document, "text": "Rust"})
                exported = await call(
                    "export_diagram",
                    {"document_id": document, "filename": "rust.svg", "format": "svg"},
                )
                assert exported["bytes"] > 100
                assert (tmp_path / "rust.svg").is_file()

    asyncio.run(run())
