"""Local stdio MCP adapter; stdout is reserved for protocol frames."""

import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .backend import NativeBackend
from .errors import DiaError
from .models import ExportFormat, NodeType, Port
from .service import Operations


def build_server(operations: Operations) -> FastMCP:
    server = FastMCP(
        "Dia operations",
        instructions=(
            "Create a document, create labeled objects (coordinates in cm), connect their IDs, "
            "then export .dia, .svg or .png into the configured workspace. State lasts for this "
            "server session. Inspect geometry for actual text-expanded bounds and native ports."
        ),
    )

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except DiaError as exc:
            raise ToolError(json.dumps(exc.as_dict())) from exc

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    edit = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=read)
    def get_capabilities() -> dict:
        """List the exact object types, formats, semantic ports and MVP limits."""
        return operations.capabilities()

    @server.tool(annotations=edit)
    def create_document(name: str = "Diagram") -> dict:
        """Create an empty session document; return its document.id."""
        return call(operations.create_document, name)

    @server.tool(annotations=edit)
    def create_object(
        document_id: str,
        type: NodeType = "Flowchart - Box",
        x: float = 0,
        y: float = 0,
        width: float = 4,
        height: float = 2,
        text: str = "",
    ) -> dict:
        """Create a native labeled shape; return object_id and actual geometry in cm."""
        return call(operations.create_object, document_id, type, x, y, width, height, text)

    @server.tool(annotations=edit)
    def connect_objects(
        document_id: str,
        source: str,
        target: str,
        source_port: Port = "auto",
        target_port: Port = "auto",
        arrow: bool = True,
    ) -> dict:
        """Connect two shape IDs using an attached native line; auto selects facing ports."""
        return call(
            operations.connect_objects, document_id, source, target, source_port, target_port, arrow
        )

    @server.tool(annotations=edit)
    def move_object(document_id: str, object_id: str, x: float, y: float) -> dict:
        """Move a shape to x,y in cm and rebuild attached connection geometry."""
        return call(operations.move_object, document_id, object_id, x, y)

    @server.tool(annotations=read)
    def inspect_document(document_id: str) -> dict:
        """Read current logical IDs, revision, objects, connections and native geometry."""
        return call(operations.inspect_document, document_id)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def export_diagram(
        document_id: str, filename: str, format: ExportFormat = "svg", overwrite: bool = False
    ) -> dict:
        """Export using Dia. filename is a basename such as workflow.svg; no paths.

        Existing files are preserved unless overwrite=true. Returns path, size and SHA256.
        """
        return call(operations.export_diagram, document_id, filename, format, overwrite)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def close_document(document_id: str) -> dict:
        """Discard session state for a document. Export first to preserve the diagram."""
        return call(operations.close_document, document_id)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--dia-binary", default="dia")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout must be between 0 and 300 seconds")
    operations = Operations(NativeBackend(args.dia_binary, args.timeout), args.workspace)
    build_server(operations).run(transport="stdio")


if __name__ == "__main__":
    main()
