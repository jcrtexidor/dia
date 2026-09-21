"""Main-context-only inspection. Native wrappers never survive dispatch().

Opaque native lifetime tokens are scoped by process and document session. Resolve
against current ownership on every request; no pointer keys or stale wrappers.
"""

import importlib.util
import math
import threading
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

from ..errors import DiaError
from ..property_policy import classify_property
from .files import NativeFiles
from .operations import Receipts
from .protocol import CAPABILITIES, MUTATIONS, VERSION, Limits, page


def point(value):
    return {"x": value.x, "y": value.y}


def bounded(text):
    return str(text)[:2048]


def semantic_available():
    try:
        return importlib.util.find_spec("dia_mcp.semantics") is not None
    except (ImportError, ValueError):
        return False


class Registry:
    def __init__(self, dia, limits=Limits(), writable=False, files_root=None):
        self.dia = dia
        self.limits = limits
        self.session = uuid4().hex
        self.thread = threading.get_ident()
        self._generations = {}
        self._sheets = None
        self._sheets_truncated = False
        self.writable = writable
        self.files = NativeFiles(dia, files_root)
        self.receipts = Receipts(self.session)

    def _assert_main(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError("Live native access outside the GTK main thread")

    def _doc_id(self, doc):
        return f"live:{self.session}:{doc.live_state[0]}"

    def _object_id(self, doc_id, obj):
        return f"{doc_id}:object:{obj.live_id}" if obj is not None else None

    def _layer_id(self, doc_id, layer):
        return f"{doc_id}:layer:{layer.live_id}"

    def _check_session(self, reference):
        if not reference.startswith(f"live:{self.session}:"):
            raise DiaError("WRONG_SESSION", "Reference belongs to another live process or snapshot")

    def _generation(self, doc, doc_id):
        # Native updates include conservative redraw invalidations. Include cheap
        # layer/selection/filename state not uniformly covered by editor redraws.
        stamp = (
            doc.live_state[1],
            doc.filename,
            doc.modified,
            tuple((layer.live_id, layer.name, layer.visible) for layer in doc.layers),
            doc.active_layer.live_id,
            tuple(o.live_id for o in doc.selected),
        )
        previous, generation = self._generations.get(doc_id, (None, 0))
        if stamp != previous:
            generation += 1
            self._generations[doc_id] = (stamp, generation)
        return generation

    def _summary(self, doc, active):
        doc_id = self._doc_id(doc)
        return {
            "document_id": doc_id,
            "name": bounded(Path(doc.filename).name),
            "filename": bounded(doc.filename),
            "active": active is not None and doc == active,
            "modified": bool(doc.modified),
            "generation": self._generation(doc, doc_id),
            "active_layer_id": self._layer_id(doc_id, doc.active_layer),
            "units": "cm",
        }

    def _objects(self, doc, doc_id):
        result = {}

        # Iterative traversal is intentional: a recursive nested function forms
        # a closure cycle, retaining its result (and wrappers) until cyclic GC.
        for layer in doc.layers:
            stack = [(obj, None, 0) for obj in reversed(layer.objects)]
            while stack:
                obj, group, depth = stack.pop()
                oid = self._object_id(doc_id, obj)
                if oid in result:
                    continue
                if depth > 32 or len(result) >= self.limits.objects:
                    raise DiaError("LIVE_LIMIT_EXCEEDED", "Document exceeds live traversal budget")
                result[oid] = (obj, layer, group)
                stack.extend((child, oid, depth + 1) for child in reversed(obj.group_members))
        return result

    def _sheet_entries(self, type_name):
        if self._sheets is None:
            self._sheets = {}
            count = 0
            for sheet in self.dia.registered_sheets():
                for kind, description, _ in sheet.objects:
                    if kind:
                        if count >= self.limits.objects:
                            self._sheets_truncated = True
                            return self._sheets.get(type_name, [])[: self.limits.structure]
                        count += 1
                        self._sheets.setdefault(kind.name, []).append(
                            {"sheet": bounded(sheet.name), "description": bounded(description)}
                        )
        return self._sheets.get(type_name, [])[: self.limits.structure]

    def _object(self, doc_id, oid, entry, selected, detail=False):
        obj, layer, group = entry
        box = obj.bounding_box
        result = {
            "object_id": oid,
            "type": bounded(obj.type.name),
            "bounds": {k: getattr(box, k) for k in ("left", "top", "right", "bottom")},
            "position": point(obj.position),
            "layer_id": self._layer_id(doc_id, layer),
            "selected": oid in selected,
            "group_id": group,
            "parent_id": self._object_id(doc_id, obj.parent),
            "handle_count": len(obj.handles),
            "connection_point_count": len(obj.connections),
        }
        if detail:
            result.update(
                sheet_entries=self._sheet_entries(obj.type.name),
                sheet_cache_truncated=self._sheets_truncated,
                child_count=len(obj.children),
                group_member_count=len(obj.group_members),
                children_truncated=len(obj.children) > self.limits.structure,
                group_members_truncated=len(obj.group_members) > self.limits.structure,
                children=[
                    self._object_id(doc_id, o) for o in obj.children[: self.limits.structure]
                ],
                group_members=[
                    self._object_id(doc_id, o) for o in obj.group_members[: self.limits.structure]
                ],
            )
        return result

    def _properties(self, obj):
        # The ordinary PyDiaProperties subscript fetches native values. Use the
        # descriptor-only accessor before touching even that subscript.
        descriptions = obj.property_descriptors(min(self.limits.properties, 256))
        values = []
        for descriptor in descriptions["items"]:
            name, kind = descriptor["name"], descriptor["type"]
            policy = classify_property(descriptor)
            item = {
                "name": bounded(name),
                "type": bounded(kind),
                "visible": descriptor["visible"],
                "supported": False,
                "editable": policy["editable"],
                "classification": policy["classification"],
            }
            if policy["readable"]:
                try:
                    value = obj.properties[name].value
                    if kind == "text":
                        value = value.text
                    if isinstance(value, str):
                        item.update(value=value[:2048], truncated=len(value) > 2048, supported=True)
                    elif type(value) in (bool, int) or (
                        type(value) is float and math.isfinite(value)
                    ):
                        item.update(value=value, supported=True)
                except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
                    item["reason"] = "Value unavailable or unsupported"
            values.append(item)
        return {
            "items": values,
            "total": descriptions["total"],
            "truncated": descriptions["truncated"],
        }

    def _connections(self, doc_id, obj):
        handles, points = obj.handles, obj.connections
        if max(len(handles), len(points)) > self.limits.structure:
            raise DiaError("LIVE_LIMIT_EXCEEDED", "Object exceeds connection inspection budget")
        hs, cps = [], []
        for index, handle in enumerate(handles):
            target = handle.connected_to
            attached = None
            if target is not None:
                owner = target.object
                owner_points = owner.connections
                if len(owner_points) > self.limits.structure:
                    raise DiaError("LIVE_LIMIT_EXCEEDED", "Target exceeds connection budget")
                attached = {
                    "object_id": self._object_id(doc_id, owner),
                    "connection_point": next(
                        (i for i, cp in enumerate(owner_points) if cp == target), None
                    ),
                }
            hs.append(
                {
                    "index": index,
                    "id": handle.id,
                    "type": handle.type,
                    "connect_type": handle.connect_type,
                    "position": point(handle.pos),
                    "attached_to": attached,
                }
            )
        for index, cp in enumerate(points):
            connected = cp.connected
            if len(connected) > self.limits.structure:
                raise DiaError("LIVE_LIMIT_EXCEEDED", "Connection exceeds fanout budget")
            cps.append(
                {
                    "index": index,
                    "position": point(cp.pos),
                    "directions": cp.directions,
                    "flags": cp.flags,
                    "connected_objects": [self._object_id(doc_id, o) for o in connected],
                }
            )
        return {"handles": hs, "connection_points": cps}

    def dispatch(self, request):
        self._assert_main()
        action = request["action"]
        if action in MUTATIONS or action == "prepare_operation":
            if not self.writable:
                raise DiaError(
                    "LIVE_WRITE_DISABLED",
                    "Enable read/write in Dia MCP Settings and restart Dia "
                    "(legacy: DIA_MCP_WRITE=1)",
                )
        if action == "prepare_operation":
            return self.receipts.prepare()
        if action == "get_operation":
            return self.receipts.status(request["request_id"])
        if action in MUTATIONS:
            return self.receipts.run(request, lambda: self._mutation(request))
        return self._dispatch(request)

    def _mutation(self, request):
        try:
            return self._dispatch(request)
        except DiaError as exc:
            # These checks resolve references/eligibility before entering native code.
            if exc.outcome is None and exc.code in {
                "LIVE_WRITE_DISABLED",
                "GENERATION_CONFLICT",
                "WRONG_SESSION",
                "STALE_DOCUMENT_REFERENCE",
                "STALE_OBJECT_REFERENCE",
                "STALE_LAYER_REFERENCE",
                "UNSUPPORTED_OPERATION",
                "LIVE_LIMIT_EXCEEDED",
            }:
                exc.outcome = "not_started"
            raise

    def _dispatch(self, request):
        action = request["action"]
        base = {"scope": "live", "session_id": self.session}
        if action == "handshake":
            return {
                **base,
                "integration_api_version": VERSION,
                "dia_version": self.dia.application_version,
                "capabilities": CAPABILITIES
                + [
                    "summary.read",
                    "dependencies.read",
                    "context.read",
                    "plans.read",
                    "commands.validate",
                ]
                + (["semantics.read"] if semantic_available() else [])
                + (
                    ["objects.write", "history.write", "layout.write"]
                    if self.writable
                    and hasattr(self.dia, "live_apply")
                    and hasattr(self.dia, "live_history")
                    else []
                )
                + (
                    ["files.write", "files.open"]
                    if self.writable and self.files.root and hasattr(self.dia, "live_file")
                    else []
                ),
                "writable": self.writable,
                "integration_mode": "read-write" if self.writable else "read-only",
                "files_root": str(self.files.root) if self.files.root else None,
                "receipt_states": [
                    "prepared",
                    "queued",
                    "executing",
                    "committed",
                    "rolled_back",
                    "failed",
                    "uncertain",
                ],
                "operation_receipts": {
                    "capacity": self.receipts.capacity,
                    "seconds": self.receipts.lifetime,
                },
                "limits": vars(self.limits),
                "identity": "runtime; detach invalidates objects",
                "generation_semantics": "observed conservative editor invalidation",
            }
        docs = [d for d in self.dia.diagrams() if d.displays]
        current = {self._doc_id(d): d for d in docs}
        self._generations = {k: v for k, v in self._generations.items() if k in current}
        display = self.dia.active_display()
        active = display.diagram if display else None
        if action == "list_documents":
            return {**base, **page([self._summary(d, active) for d in docs], request, self.limits)}
        if action == "get_active_document":
            return {
                **base,
                "document": self._summary(active, active)
                if active is not None and active in docs
                else None,
            }
        if action == "get_current_context":
            if active is None or active not in docs:
                return {
                    **base,
                    "document": None,
                    "selection": {"items": [], "total": 0, "next_offset": None},
                }
            request = {**request, "document_id": self._doc_id(active)}
        if action == "open_document":
            opened = self.files.open(request)
            return {**base, "document": self._summary(opened, opened)}
        doc_id = request["document_id"]
        self._check_session(doc_id)
        doc = current.get(doc_id)
        if doc is None:
            raise DiaError("STALE_DOCUMENT_REFERENCE", "Document is closed, replaced, or unknown")
        summary = self._summary(doc, active)
        base.update(document_id=doc_id, generation=summary["generation"])
        if action in MUTATIONS or action == "validate_commands":
            if request["expected_generation"] != summary["generation"]:
                raise DiaError(
                    "GENERATION_CONFLICT",
                    "Document changed; inspect it and prepare a new operation",
                    details={
                        "expected_generation": request["expected_generation"],
                        "current_generation": summary["generation"],
                        "recovery": "Inspect current context and review a fresh plan",
                    },
                )
            if action in {"save_document", "save_document_as", "export_document"}:
                result = self.files.write(doc, request)
                return {**base, **result, "generation": self._generation(doc, doc_id)}
            if action == "history":
                try:
                    result = self.dia.live_history(doc, request["direction"])
                except Exception as exc:
                    raise self._native_error(exc) from exc
                return {**base, "history": result, "generation": self._generation(doc, doc_id)}
        if action == "get_document":
            return {**base, "document": summary}
        if action == "list_layers":
            return {
                **base,
                **page(
                    [
                        {
                            "layer_id": self._layer_id(doc_id, layer),
                            "name": bounded(layer.name),
                            "visible": bool(layer.visible),
                            "order": i,
                            "active": layer == doc.active_layer,
                            "object_count": len(layer.objects),
                        }
                        for i, layer in enumerate(doc.layers)
                    ],
                    request,
                    self.limits,
                ),
            }
        objects = self._objects(doc, doc_id)
        selected = {self._object_id(doc_id, o) for o in doc.selected}
        if action in {"get_current_context", "inspect_selection"}:
            ids = [oid for oid in objects if oid in selected]
            selection = page(ids, {"limit": 8, **request}, self.limits)
            selection["items"] = [
                self._inspect(doc_id, oid, objects[oid], selected) for oid in selection["items"]
            ]
            if action == "inspect_selection":
                return {**base, **selection}
            return {
                **base,
                "document": summary,
                "selection": selection,
                "object_count": len(objects),
                "layer_count": len(doc.layers),
                "active_layer": {
                    "layer_id": summary["active_layer_id"],
                    "name": bounded(doc.active_layer.name),
                    "visible": bool(doc.active_layer.visible),
                },
                "evidence": "native_fact",
            }
        if action == "plan_selection":
            from .planning import plan_selection

            ids = [oid for oid in objects if oid in selected]
            if len(ids) > 64:
                raise DiaError("LIVE_LIMIT_EXCEEDED", "Selection plan requires at most 64 objects")
            summaries = [self._object(doc_id, oid, objects[oid], selected) for oid in ids]
            if request["intent"] == "set_properties":
                for item, oid in zip(summaries, ids):
                    descriptors = objects[oid][0].property_descriptors(self.limits.properties)
                    item["properties"] = {
                        "items": [
                            {"name": desc["name"], "editable": classify_property(desc)["editable"]}
                            for desc in descriptors["items"]
                        ],
                        "truncated": descriptors["truncated"],
                    }
            try:
                plan = plan_selection(summaries, request["intent"], request["options"])
            except ValueError as exc:
                raise DiaError("INVALID_ARGUMENT", str(exc)[:512]) from exc
            return {**base, **plan}
        if action == "validate_commands":
            from .validation import validate_batch

            return {
                **base,
                "mutates": False,
                **validate_batch(self, doc, doc_id, objects, request["commands"]),
            }
        if action == "apply_commands":
            return self._apply(doc, doc_id, objects, request, base)
        if action == "get_dependencies":
            return {**base, **self.files.dependencies(objects, self.limits.structure)}
        if action == "summarize_document":
            return {
                **base,
                "document": summary,
                "object_count": len(objects),
                "selected_count": len(selected),
                "layer_count": len(doc.layers),
                "types": dict(Counter(entry[0].type.name for entry in objects.values())),
                "topology": "Use analyze_document for actual handle attachments",
            }
        if action == "analyze_document":
            try:
                from ..semantics import analyze_graph
            except ImportError as exc:
                raise DiaError(
                    "UNSUPPORTED_LIVE_CAPABILITY", "Optional semantic analysis is unavailable"
                ) from exc
            if len(objects) > self.limits.structure:
                raise DiaError(
                    "LIVE_LIMIT_EXCEEDED", "Analysis requires at most the structure limit objects"
                )
            started = time.monotonic()
            summaries = [
                self._object(doc_id, oid, entry, selected) for oid, entry in objects.items()
            ]
            connections = {
                oid: self._connections(doc_id, entry[0]) for oid, entry in objects.items()
            }
            return {
                **base,
                "analysis": analyze_graph(summaries, connections, request.get("domain", "auto")),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            }
        if action in {"list_objects", "get_selection"}:
            ids = (
                list(objects) if action == "list_objects" else [o for o in objects if o in selected]
            )
            result = page(ids, request, self.limits)
            result["items"] = [
                self._object(doc_id, oid, objects[oid], selected) for oid in result["items"]
            ]
            return {**base, **result}
        oid = request["object_id"]
        self._check_session(oid)
        if not oid.startswith(f"{doc_id}:object:"):
            raise DiaError("OBJECT_NOT_FOUND", "Object belongs to another document")
        if oid not in objects:
            raise DiaError("STALE_OBJECT_REFERENCE", "Object is detached, deleted, or unknown")
        obj = objects[oid][0]
        if action == "inspect_object_neighborhood":
            detail = self._inspect(doc_id, oid, objects[oid], selected)
            connections = detail["connections"]
            neighbors = {
                h["attached_to"]["object_id"] for h in connections["handles"] if h["attached_to"]
            }
            neighbors.update(
                ref for cp in connections["connection_points"] for ref in cp["connected_objects"]
            )
            neighbors.discard(oid)
            present = sorted(neighbors & objects.keys())
            result = page(present, {"limit": 8, **request}, self.limits)
            result["items"] = [
                self._object(doc_id, ref, objects[ref], selected) for ref in result["items"]
            ]
            return {
                **base,
                "object": detail,
                "neighbors": result,
                "external_neighbor_count": len(neighbors - objects.keys()),
                "basis": "native_handle_attachments_and_connection_point_membership",
                "scope": "one_hop",
                "evidence": "derived_structural_fact",
            }
        if action == "get_connections":
            return {**base, "object_id": oid, **self._connections(doc_id, obj)}
        result = self._object(doc_id, oid, objects[oid], selected, detail=True)
        if request.get("properties", False):
            result["properties"] = self._properties(obj)
        return {**base, "object": result}

    def _inspect(self, doc_id, oid, entry, selected):
        return {
            **self._object(doc_id, oid, entry, selected, detail=True),
            "properties": self._properties(entry[0]),
            "connections": self._connections(doc_id, entry[0]),
        }

    def _apply(self, doc, doc_id, objects, request, base):
        def resolve(oid):
            self._check_session(oid)
            if oid not in objects:
                raise DiaError(
                    "STALE_OBJECT_REFERENCE", "Object is not a current member of this document"
                )
            if objects[oid][2] is not None:
                raise DiaError(
                    "UNSUPPORTED_OPERATION", "Editing group members requires native group support"
                )
            return objects[oid][0]

        commands = []
        # Resolve the entire batch before entering C. References target existing
        # members; newly created objects can be used in a subsequent transaction.
        for source in request["commands"]:
            command = dict(source)
            for key, native in (("object_id", "object"), ("target_id", "target")):
                if key in command:
                    command[native] = resolve(command.pop(key))
            if "object_ids" in command:
                command["objects"] = [resolve(oid) for oid in command.pop("object_ids")]
            if "layer_id" in command:
                lid = command.pop("layer_id")
                layers = [layer for layer in doc.layers if self._layer_id(doc_id, layer) == lid]
                if not layers:
                    raise DiaError("STALE_LAYER_REFERENCE", "Layer is not in this document")
                command["layer"] = layers[0]
            commands.append(command)
        try:
            result = self.dia.live_apply(doc, commands)
        except Exception as exc:
            raise self._native_error(exc) from exc
        created = [self._object_id(doc_id, obj) for obj in result.get("created", [])]
        return {
            **base,
            "created": created,
            "command_count": len(commands),
            "generation": self._generation(doc, doc_id),
            "committed": True,
        }

    def _native_error(self, exc):
        if isinstance(exc, getattr(self.dia, "LiveRollbackError", ())):
            return DiaError("NATIVE_COMMAND_FAILED", str(exc)[:512], outcome="rolled_back")
        if isinstance(exc, getattr(self.dia, "LiveValidationError", ())):
            return DiaError("NATIVE_VALIDATION_FAILED", str(exc)[:512], outcome="not_started")
        return DiaError(
            "OPERATION_UNCERTAIN",
            "Native result unavailable; inspect state and receipt",
            outcome="uncertain",
        )
