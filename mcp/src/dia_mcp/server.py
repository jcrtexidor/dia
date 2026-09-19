"""Local stdio MCP adapter; stdout is reserved for protocol frames."""

import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .backend import NativeBackend
from .discovery import Offset, PageSize
from .errors import DiaError
from .models import (
    ConnectionIndex,
    ConnectionType,
    ExportFormat,
    NodeType,
    Port,
    UMLClassProperties,
)
from .service import Operations


def build_server(operations: Operations) -> FastMCP:
    server = FastMCP(
        "Dia operations",
        instructions=(
            "Create a document, create labeled objects (coordinates in cm), connect their IDs, "
            "then export .dia, .svg or .png into the configured workspace. State lasts for this "
            "server session. Inspect geometry for actual text-expanded bounds and native ports."
            " Use list_sheets/list_object_types to discover installed native types; only those "
            "with a creatable_as marker can be created through the current MCP contract."
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
        """Describe MCP creation types and limits; use list tools for installed native types."""
        return operations.capabilities()

    @server.tool(annotations=read)
    def list_sheets(offset: Offset = 0, limit: PageSize = 100) -> dict:
        """Discover native worker sheets with names, descriptions and entry counts.

        Read-only, fresh worker inventory, not the open GUI. Follow next_offset for more.
        """
        return call(operations.list_sheets, offset, limit)

    @server.tool(annotations=read)
    def list_object_types(
        sheet: str | None = None, offset: Offset = 0, limit: PageSize = 100
    ) -> dict:
        """Discover registered Dia types, optionally filtered by an exact list_sheets name.

        Includes native version, sheet labels and creatable_as (object/connection/null).
        Installed types with null are not yet creatable through MCP. Follow next_offset.
        This queries a fresh worker, not the open GUI; no objects are instantiated.
        """
        return call(operations.list_object_types, sheet, offset, limit)

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
        properties: UMLClassProperties | None = None,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> dict:
        """Create a native labeled shape; return object_id and actual geometry in cm."""
        return call(
            operations.create_object,
            document_id,
            type,
            x,
            y,
            width,
            height,
            text,
            properties,
            flip_horizontal,
            flip_vertical,
        )

    @server.tool(annotations=edit)
    def connect_objects(
        document_id: str,
        source: str,
        target: str,
        source_port: Port = "auto",
        target_port: Port = "auto",
        arrow: bool = True,
        type: ConnectionType = "Standard - Line",
        source_connection: ConnectionIndex | None = None,
        target_connection: ConnectionIndex | None = None,
        label: str = "",
    ) -> dict:
        """Attach native endpoints; inspect connection_points to select exact terminal indices.

        Explicit indices require the corresponding port=auto. UML generalization points from
        target (subclass) to source (superclass). UML symbols control their own arrowheads.
        """
        return call(
            operations.connect_objects,
            document_id,
            source,
            target,
            source_port,
            target_port,
            arrow,
            type,
            source_connection,
            target_connection,
            label,
        )

    @server.tool(annotations=edit)
    def update_object(
        document_id: str,
        object_id: str,
        text: str | None = None,
        width: float | None = None,
        height: float | None = None,
        properties: UMLClassProperties | None = None,
        flip_horizontal: bool | None = None,
        flip_vertical: bool | None = None,
    ) -> dict:
        """Update supplied object fields; properties replaces the entire UML property set.

        Omitted/null fields stay unchanged. Send properties={} to reset UML members.
        Geometry and attached connectors are rebuilt before the change is committed.
        """
        return call(
            operations.update_object,
            document_id,
            object_id,
            text,
            width,
            height,
            properties,
            flip_horizontal,
            flip_vertical,
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
