"""Transactional operations API. Native success precedes a revision change."""

import hashlib
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import get_args
from uuid import uuid4

from pydantic import ValidationError

from .backend import Backend
from .discovery import Catalog
from .errors import DiaError
from .models import (
    ConnectionType,
    Document,
    Edge,
    ExportFormat,
    Node,
    NodeType,
    Port,
    UMLClassProperties,
)


class Operations:
    def __init__(self, backend: Backend, workspace: Path, live=None):
        self.live = live
        self.backend = backend
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._documents: dict[str, Document] = {}
        self._geometry: dict[str, dict] = {}
        self._lock = threading.RLock()

    def inspect_live(self, action: str, **params) -> dict:
        """Transport-independent live reads; no snapshot IDs are resolved here."""
        if self.live is None:
            raise DiaError(
                "LIVE_BACKEND_UNAVAILABLE", "Configure --live-socket to inspect a running GUI"
            )
        return self.live.request(action, **params)

    @staticmethod
    def capabilities() -> dict:
        return {
            "api_version": "1",
            "object_types": list(get_args(NodeType)),
            "connection_types": list(get_args(ConnectionType)),
            "object_schema": Node.model_json_schema(),
            "connection_schema": Edge.model_json_schema(),
            "terminal_selection": (
                "inspect connection_points; pass a selectable index with port=auto"
            ),
            "uml_direction": "Generalization: source is superclass, target is subclass",
            "ports": list(get_args(Port)),
            "formats": list(get_args(ExportFormat)),
            "units": "cm",
            "max_documents": 32,
            "max_nodes": 100,
            "max_edges": 200,
            "persistence": "session; export native .dia files to keep diagrams",
            "runtime_discovery": {
                "tools": ["list_sheets", "list_object_types"],
                "scope": "fresh native worker; not an open GUI session",
            },
            "live_documents": True,
            "live_integration": {
                "mode": "opt-in read-only; configure --live-socket",
                "handshake_tool": "live_handshake",
                "scope": "running GUI; distinct from snapshots",
            },
            "generic_creation": False,
        }

    @staticmethod
    def _page(items: list, offset: int, limit: int) -> dict:
        end = offset + limit
        return {
            "api_version": "1",
            "scope": "native_worker",
            "items": items[offset:end],
            "total": len(items),
            "next_offset": end if end < len(items) else None,
        }

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise DiaError("INVALID_ARGUMENT", "offset must be >=0 and limit must be 1..100")

    def _catalog(self) -> Catalog:
        discover = getattr(self.backend, "discover", None)
        if discover is None:
            raise DiaError("UNSUPPORTED_CAPABILITY", "Backend does not support runtime discovery")
        return discover()

    def list_sheets(self, offset: int = 0, limit: int = 100) -> dict:
        self._validate_page(offset, limit)
        catalog = self._catalog()
        return self._page(
            [
                {
                    "name": sheet.name,
                    "description": sheet.description,
                    "user": sheet.user,
                    "object_count": len(sheet.objects),
                }
                for sheet in sorted(catalog.sheets, key=lambda sheet: sheet.name)
            ],
            offset,
            limit,
        )

    def list_object_types(
        self, sheet: str | None = None, offset: int = 0, limit: int = 100
    ) -> dict:
        self._validate_page(offset, limit)
        if sheet is not None and (not isinstance(sheet, str) or not 1 <= len(sheet) <= 4096):
            raise DiaError("INVALID_ARGUMENT", "sheet must be a nonempty name from list_sheets")
        catalog = self._catalog()
        if sheet is not None and not any(s.name == sheet for s in catalog.sheets):
            raise DiaError("NOT_FOUND", "Unknown sheet; use list_sheets for available names")
        membership: dict[str, list[dict]] = {}
        for entry in catalog.sheets:
            for obj in entry.objects:
                if obj.type is not None:
                    membership.setdefault(obj.type, []).append(
                        {"sheet": entry.name, "description": obj.description}
                    )
        node_types, connection_types = set(get_args(NodeType)), set(get_args(ConnectionType))
        items = []
        for kind in sorted(catalog.object_types, key=lambda kind: kind.name):
            entries = membership.get(kind.name, [])
            if sheet is not None and not any(entry["sheet"] == sheet for entry in entries):
                continue
            items.append(
                {
                    "name": kind.name,
                    "version": kind.version,
                    "sheet_entries": entries,
                    "creatable_as": (
                        "object"
                        if kind.name in node_types
                        else "connection"
                        if kind.name in connection_types
                        else None
                    ),
                }
            )
        return self._page(items, offset, limit)

    def _document(self, document_id: str) -> Document:
        try:
            return self._documents[document_id]
        except KeyError as exc:
            raise DiaError("NOT_FOUND", "Unknown document_id") from exc

    def _commit(self, candidate: Document) -> dict:
        # Enforce list limits again: appending to a Pydantic list bypasses assignment validation.
        try:
            candidate = Document.model_validate(candidate.model_dump())
        except ValidationError as exc:
            raise DiaError("INVALID_ARGUMENT", str(exc)) from exc
        try:
            with tempfile.TemporaryDirectory(prefix="dia-mcp-check-") as folder:
                geometry = self.backend.render(candidate, Path(folder) / "check.dia", "dia")
        except OSError as exc:
            raise DiaError("IO_ERROR", str(exc)) from exc
        candidate.revision += 1
        self._documents[candidate.id] = candidate
        self._geometry[candidate.id] = geometry
        return self.inspect_document(candidate.id)

    def create_document(self, name: str = "Diagram") -> dict:
        with self._lock:
            if len(self._documents) >= 32:
                raise DiaError("LIMIT_EXCEEDED", "Close a document before creating another")
            try:
                doc = Document(id=uuid4().hex, name=name)
            except ValidationError as exc:
                raise DiaError("INVALID_ARGUMENT", str(exc)) from exc
            # An empty document has no native objects. The first edit validates the backend.
            self._documents[doc.id] = doc
            self._geometry[doc.id] = {"nodes": {}, "edges": {}}
            return self.inspect_document(doc.id)

    def inspect_document(self, document_id: str) -> dict:
        with self._lock:
            document = self._document(document_id)
            # Return independent JSON data, never mutable internal state.
            import copy

            return {
                "document": document.model_dump(),
                "geometry": copy.deepcopy(self._geometry[document_id]),
            }

    def create_object(
        self,
        document_id: str,
        type: NodeType = "Flowchart - Box",
        x: float = 0,
        y: float = 0,
        width: float = 4,
        height: float = 2,
        text: str = "",
        properties: UMLClassProperties | dict | None = None,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> dict:
        with self._lock:
            doc = self._document(document_id).model_copy(deep=True)
            try:
                node = Node(
                    id=uuid4().hex,
                    type=type,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    text=text,
                    properties=properties,
                    flip_horizontal=flip_horizontal,
                    flip_vertical=flip_vertical,
                )
            except ValidationError as exc:
                raise DiaError("INVALID_ARGUMENT", str(exc)) from exc
            doc.nodes.append(node)
            result = self._commit(doc)
            return {"object_id": node.id, **result}

    def connect_objects(
        self,
        document_id: str,
        source: str,
        target: str,
        source_port: Port = "auto",
        target_port: Port = "auto",
        arrow: bool = True,
        type: ConnectionType = "Standard - Line",
        source_connection: int | None = None,
        target_connection: int | None = None,
        label: str = "",
    ) -> dict:
        with self._lock:
            doc = self._document(document_id).model_copy(deep=True)
            ids = {node.id for node in doc.nodes}
            if source not in ids or target not in ids:
                raise DiaError("NOT_FOUND", "Both endpoints must belong to this document")
            if source == target:
                raise DiaError("INVALID_ARGUMENT", "Self-connections are outside this MVP")
            try:
                edge = Edge(
                    id=uuid4().hex,
                    source=source,
                    target=target,
                    source_port=source_port,
                    target_port=target_port,
                    arrow=arrow,
                    type=type,
                    source_connection=source_connection,
                    target_connection=target_connection,
                    label=label,
                )
            except ValidationError as exc:
                raise DiaError("INVALID_ARGUMENT", str(exc)) from exc
            if type.startswith("UML - ") and any(
                node.type != "UML - Class" for node in doc.nodes if node.id in (source, target)
            ):
                raise DiaError("INVALID_ARGUMENT", "UML connectors require two UML classes")
            for object_id, side, index in (
                (source, source_port, source_connection),
                (target, target_port, target_connection),
            ):
                if index is not None:
                    points = self._geometry[document_id]["nodes"][object_id].get(
                        "connection_points"
                    )
                    if side != "auto" or points is not None and index >= len(points):
                        raise DiaError("INVALID_ARGUMENT", "Invalid or ambiguous connection index")
                    node = next(n for n in doc.nodes if n.id == object_id)
                    if node.type == "UML - Class" and index >= 8:
                        raise DiaError(
                            "INVALID_ARGUMENT",
                            "Dynamic UML member ports require semantic selection",
                        )
            doc.edges.append(edge)
            result = self._commit(doc)
            return {"connection_id": edge.id, **result}

    def update_object(
        self,
        document_id: str,
        object_id: str,
        text: str | None = None,
        width: float | None = None,
        height: float | None = None,
        properties: UMLClassProperties | dict | None = None,
        flip_horizontal: bool | None = None,
        flip_vertical: bool | None = None,
    ) -> dict:
        """Replace supplied fields atomically; properties replaces the full UML property set."""
        with self._lock:
            doc = self._document(document_id).model_copy(deep=True)
            index = next((i for i, node in enumerate(doc.nodes) if node.id == object_id), None)
            if index is None:
                raise DiaError("NOT_FOUND", "Unknown object_id in this document")
            values = doc.nodes[index].model_dump()
            for key, value in (
                ("text", text),
                ("width", width),
                ("height", height),
                ("properties", properties),
                ("flip_horizontal", flip_horizontal),
                ("flip_vertical", flip_vertical),
            ):
                if value is not None:
                    values[key] = (
                        value.model_dump() if isinstance(value, UMLClassProperties) else value
                    )
            try:
                doc.nodes[index] = Node.model_validate(values)
            except ValidationError as exc:
                raise DiaError("INVALID_ARGUMENT", str(exc)) from exc
            return self._commit(doc)

    def move_object(self, document_id: str, object_id: str, x: float, y: float) -> dict:
        with self._lock:
            doc = self._document(document_id).model_copy(deep=True)
            node = next((node for node in doc.nodes if node.id == object_id), None)
            if node is None:
                raise DiaError("NOT_FOUND", "Unknown object_id in this document")
            try:
                node.x, node.y = x, y
            except ValidationError as exc:
                raise DiaError("INVALID_ARGUMENT", str(exc)) from exc
            return self._commit(doc)

    def export_diagram(
        self, document_id: str, filename: str, format: ExportFormat = "svg", overwrite: bool = False
    ) -> dict:
        with self._lock:
            doc = self._document(document_id)
            if not doc.nodes:
                raise DiaError("EMPTY_DIAGRAM", "Create an object before exporting")
            if format not in get_args(ExportFormat):
                raise DiaError("INVALID_ARGUMENT", "Unsupported export format")
            if (
                not isinstance(filename, str)
                or len(filename) > 120
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", filename)
                or not filename.endswith(f".{format}")
            ):
                raise DiaError(
                    "INVALID_ARGUMENT", "Use a basename with the selected file extension"
                )
            destination = self.workspace / filename
            if destination.is_symlink() or (destination.exists() and not overwrite):
                raise DiaError("ALREADY_EXISTS", "Output exists; choose another name or overwrite")
            # Staging on the same filesystem enables atomic publication after validation.
            staged = None
            try:
                fd, stage = tempfile.mkstemp(prefix=".dia-mcp-", dir=self.workspace)
                staged = Path(stage)
                os.close(fd)
                self.backend.render(doc, staged, format)
                digest = hashlib.sha256(staged.read_bytes()).hexdigest()
                size = staged.stat().st_size
                if overwrite:
                    os.replace(staged, destination)
                else:
                    # link() fails atomically if another process won the destination name.
                    os.link(staged, destination)
                return {
                    "api_version": "1",
                    "document_id": doc.id,
                    "revision": doc.revision,
                    "path": str(destination),
                    "format": format,
                    "bytes": size,
                    "sha256": digest,
                }
            except FileExistsError as exc:
                raise DiaError("ALREADY_EXISTS", "Output was created by another process") from exc
            except OSError as exc:
                raise DiaError("IO_ERROR", str(exc)) from exc
            finally:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError:
                        # Cleanup must not mask a backend error or a published success.
                        logging.getLogger(__name__).warning(
                            "Could not remove temporary export %s", staged
                        )

    def close_document(self, document_id: str) -> dict:
        with self._lock:
            self._document(document_id)
            del self._documents[document_id]
            del self._geometry[document_id]
            return {"api_version": "1", "closed": document_id}
