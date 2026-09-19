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
from .live.client import LiveClient
from .models import (
    ConnectionIndex,
    ConnectionType,
    ExportFormat,
    NodeType,
    Port,
    UMLClassProperties,
)
from .recipes import plan_native
from .service import Operations


def build_server(operations: Operations) -> FastMCP:
    server = FastMCP(
        "Dia operations",
        instructions=(
            "Create a document, create labeled objects (coordinates in cm), connect their IDs, "
            "then export .dia, .svg or .png into the configured workspace. State lasts for this "
            "server session. Inspect geometry for actual text-expanded bounds and native ports."
            " Use list_sheets/list_object_types to discover installed native types; only those "
            "with a creatable_as marker can be created in snapshots. The opt-in "
            "live_apply_commands supports installed native factories."
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
        Installed types with null are not creatable in snapshots; live generic creation
        is separate. Follow next_offset.
        This queries a fresh worker, not the open GUI; no objects are instantiated.
        """
        return call(operations.list_object_types, sheet, offset, limit)

    @server.tool(annotations=read)
    def live_handshake() -> dict:
        """Connect to the configured running Dia GUI; return version, capabilities and limits."""
        return call(operations.inspect_live, "handshake")

    @server.tool(annotations=read)
    def live_list_documents(offset: Offset = 0, limit: PageSize = 100) -> dict:
        """List open GUI documents, distinct from MCP-owned snapshot documents."""
        return call(operations.inspect_live, "list_documents", offset=offset, limit=limit)

    @server.tool(annotations=read)
    def live_get_active_document() -> dict:
        """Read the actual active GUI document, or null when there is none."""
        return call(operations.inspect_live, "get_active_document")

    @server.tool(annotations=read)
    def live_get_document(document_id: str) -> dict:
        """Read a live document summary, modified status and conservative generation."""
        return call(operations.inspect_live, "get_document", document_id=document_id)

    @server.tool(annotations=read)
    def live_list_layers(document_id: str, offset: Offset = 0, limit: PageSize = 100) -> dict:
        """Read GUI layers in native order with visibility and active layer."""
        return call(
            operations.inspect_live,
            "list_layers",
            document_id=document_id,
            offset=offset,
            limit=limit,
        )

    @server.tool(annotations=read)
    def live_get_selection(document_id: str, offset: Offset = 0, limit: PageSize = 100) -> dict:
        """Explain what the user selected in Dia using current object IDs and geometry."""
        return call(
            operations.inspect_live,
            "get_selection",
            document_id=document_id,
            offset=offset,
            limit=limit,
        )

    @server.tool(annotations=read)
    def live_list_objects(document_id: str, offset: Offset = 0, limit: PageSize = 100) -> dict:
        """Read bounded summaries of arbitrary native types, including group members."""
        return call(
            operations.inspect_live,
            "list_objects",
            document_id=document_id,
            offset=offset,
            limit=limit,
        )

    @server.tool(annotations=read)
    def live_get_object(document_id: str, object_id: str, properties: bool = False) -> dict:
        """Inspect a live object, relations, sheets and optional safe properties."""
        return call(
            operations.inspect_live,
            "get_object",
            document_id=document_id,
            object_id=object_id,
            properties=properties,
        )

    @server.tool(annotations=read)
    def live_get_connections(document_id: str, object_id: str) -> dict:
        """Read actual native handle attachments and connection points, not visual proximity."""
        return call(
            operations.inspect_live, "get_connections", document_id=document_id, object_id=object_id
        )

    @server.tool(annotations=read)
    def live_plan_objects(domain: str, nodes: list[dict]) -> dict:
        """Preview generic create commands for flowchart, UML, database or network objects.

        nodes contain x,y and optional type,label. Does not mutate; apply returned
        commands using a prepared operation and a current document generation.
        Inspect created native handles before planning connections.
        """
        try:
            return plan_native(domain, nodes)
        except ValueError as exc:
            raise ToolError(json.dumps(DiaError("INVALID_ARGUMENT", str(exc)).as_dict())) from exc

    @server.tool(annotations=edit)
    def live_prepare_operation() -> dict:
        """Reserve a one-use request_id before a GUI mutation (requires DIA_MCP_WRITE=1).

        Retain it to query/retry identical input after transport failure. Receipts last
        at most 30 minutes/256 operations; unknown IDs never execute mutations.
        """
        return call(operations.inspect_live, "prepare_operation")

    @server.tool(annotations=read)
    def live_get_operation(request_id: str) -> dict:
        """Query a reserved operation receipt after success, failure or lost response."""
        return call(operations.inspect_live, "get_operation", request_id=request_id)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def live_apply_commands(
        document_id: str, expected_generation: int, request_id: str, commands: list[dict]
    ) -> dict:
        """Apply 1..64 commands as one native undo transaction.

        op=create: type,x,y,optional properties/layer_id; move: object_id,x,y;
        set_properties: object_id,properties (safe scalar/text values only);
        delete: object_id (disconnect first); connect: object_id,handle,target_id,point;
        disconnect: object_id,handle; layout: object_ids,mode (left,center,right,top,
        middle,bottom,distribute_horizontal,distribute_vertical).
        IDs must exist before the batch; create returns IDs for subsequent transactions.
        Read current generation first. After failure reread IDs/state; rollback may
        invalidate runtime IDs. Duplicate identical request_id returns its receipt.
        """
        return call(
            operations.inspect_live,
            "apply_commands",
            document_id=document_id,
            expected_generation=expected_generation,
            request_id=request_id,
            commands=commands,
        )

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def live_history(
        document_id: str, expected_generation: int, request_id: str, direction: str
    ) -> dict:
        """Undo or redo a native transaction; direction is undo or redo.

        This is the GUI's shared history, including the user's edits. Read state first.
        """
        return call(
            operations.inspect_live,
            "history",
            document_id=document_id,
            expected_generation=expected_generation,
            request_id=request_id,
            direction=direction,
        )

    @server.tool(annotations=edit)
    def live_open_document(path: str, request_id: str) -> dict:
        """Open a .dia file under DIA_MCP_FILES_ROOT in a new GUI document.

        Native importers can read referenced resources. Use trusted local files.
        """
        return call(operations.inspect_live, "open_document", path=path, request_id=request_id)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def live_save_document(
        document_id: str, expected_generation: int, request_id: str, overwrite: bool = False
    ) -> dict:
        """Save natively to the current filename; existing files require overwrite=true."""
        return call(
            operations.inspect_live,
            "save_document",
            document_id=document_id,
            expected_generation=expected_generation,
            request_id=request_id,
            overwrite=overwrite,
        )

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def live_save_document_as(
        document_id: str,
        expected_generation: int,
        request_id: str,
        path: str,
        overwrite: bool = False,
    ) -> dict:
        """Save native data under DIA_MCP_FILES_ROOT and update GUI filename after publication."""
        return call(
            operations.inspect_live,
            "save_document_as",
            document_id=document_id,
            expected_generation=expected_generation,
            request_id=request_id,
            path=path,
            overwrite=overwrite,
        )

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def live_export_document(
        document_id: str,
        expected_generation: int,
        request_id: str,
        path: str,
        format: str = "svg",
        overwrite: bool = False,
    ) -> dict:
        """Export native dia/svg/png under DIA_MCP_FILES_ROOT; preserve GUI dirty state."""
        return call(
            operations.inspect_live,
            "export_document",
            document_id=document_id,
            expected_generation=expected_generation,
            request_id=request_id,
            path=path,
            format=format,
            overwrite=overwrite,
        )

    @server.tool(annotations=read)
    def live_get_dependencies(document_id: str) -> dict:
        """Report declared native file properties; completeness/existence are not guaranteed."""
        return call(operations.inspect_live, "get_dependencies", document_id=document_id)

    @server.tool(annotations=read)
    def live_summarize_document(document_id: str) -> dict:
        """Summarize object types, layers, selection and current generation without mutation."""
        return call(operations.inspect_live, "summarize_document", document_id=document_id)

    @server.tool(annotations=read)
    def live_analyze_document(document_id: str, domain: str = "auto") -> dict:
        """Analyze actual attachments and mixed domains (at most 256 objects).

        Reports connected components, isolated objects, supported UML relationships
        and explicit semantic limitations. This is not electrical simulation.
        """
        return call(
            operations.inspect_live, "analyze_document", document_id=document_id, domain=domain
        )

    @server.resource("dia://live/documents")
    def live_documents_resource() -> str:
        """First page of live documents; follow next_offset with live_list_documents."""
        return json.dumps(call(operations.inspect_live, "list_documents"))

    @server.resource("dia://live/documents/{document_id}/summary")
    def live_summary_resource(document_id: str) -> str:
        """Current native document summary."""
        return json.dumps(
            call(operations.inspect_live, "summarize_document", document_id=document_id)
        )

    @server.prompt()
    def explain_live_diagram(document_id: str) -> str:
        """Inspect and explain a GUI document using evidence from native attachments."""
        return (
            f"Inspect live document {document_id!r} with live_summarize_document and "
            "live_analyze_document. Inspect selected objects and relevant properties. "
            "Explain supported structure, mixed domains, and unknowns; distinguish "
            "actual connections from geometry. Report truncation. Do not mutate the diagram."
        )

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
    parser.add_argument("--live-socket", type=Path, help="Opt-in running Dia Unix socket")
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout must be between 0 and 300 seconds")
    operations = Operations(
        NativeBackend(args.dia_binary, args.timeout),
        args.workspace,
        live=LiveClient(args.live_socket, min(args.timeout, 30)) if args.live_socket else None,
    )
    build_server(operations).run(transport="stdio")


if __name__ == "__main__":
    main()
