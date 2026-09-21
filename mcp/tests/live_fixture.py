"""Trusted GUI-side test driver, never loaded or reachable by the live protocol."""

import json
import os
import threading
import traceback
from pathlib import Path


def install():
    import dia
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    root = Path(os.environ["DIA_LIVE_TEST"])
    state = {"ticks": 0}

    def tick():
        state["ticks"] += 1
        return True

    GLib.timeout_add(20, tick)

    def activate(name):
        seen = set()

        def find(widget):
            if widget in seen:
                return False
            seen.add(widget)
            if isinstance(widget, Gtk.Activatable):
                action = widget.get_related_action()
                if action and action.get_name() == name:
                    action.activate()
                    return True
            children = widget.get_children() if isinstance(widget, Gtk.Container) else []
            if isinstance(widget, Gtk.MenuItem) and widget.get_submenu():
                children.append(widget.get_submenu())
            return any(find(child) for child in children)

        if not any(find(window) for window in Gtk.Window.list_toplevels()):
            raise AssertionError(f"Native GTK action not found: {name}")

    def listener_stats():
        # Trusted fixture only: inspect cache ownership without exposing objects
        # or adding diagnostics/fault controls to the production wire protocol.
        from dia_mcp.live.plugin import _listener

        listener = _listener
        seen = set()

        def wrappers(value):
            if id(value) in seen:
                return 0
            seen.add(id(value))
            if type(value).__module__ == "dia":
                return 1
            if isinstance(value, dict):
                return sum(wrappers(v) for pair in value.items() for v in pair)
            if isinstance(value, (list, tuple, set)):
                return sum(wrappers(v) for v in value)
            return 0

        registry = listener.registry
        cache_wrappers = sum(
            wrappers(value)
            for value in (
                registry._generations,
                registry._sheets,
                registry.receipts.entries,
            )
        )
        sources = [listener.source, listener.timer, listener.idle]
        sources.extend(client.source for client in listener.clients)
        context = GLib.MainContext.default()
        active_sources = sum(
            source is not None and context.find_source_by_id(source) is not None
            for source in sources
        )
        status = Path("/proc/self/status").read_text().splitlines()
        rss = int(next(line.split()[1] for line in status if line.startswith("VmRSS:")))
        return {
            "clients": len(listener.clients),
            "queue": len(listener.queue),
            "sources": active_sources,
            "generations": len(registry._generations),
            "receipts": len(registry.receipts.entries),
            "receipt_capacity": registry.receipts.capacity,
            "cache_native_wrappers": cache_wrappers,
            "native_identity_entries": dia.live_identity_count()
            if hasattr(dia, "live_identity_count")
            else None,
            "closed": listener.closed,
            "fds": len(list(Path("/proc/self/fd").iterdir())),
            "rss_kib": rss,
            "visible_documents": sum(bool(doc.displays) for doc in dia.diagrams()),
            "visible_objects": sum(
                len(layer.objects) for doc in dia.diagrams() if doc.displays for layer in doc.layers
            ),
        }

    def poll():
        command = root / "command.json"
        if not command.exists():
            return True
        request = json.loads(command.read_text())
        command.unlink()
        try:
            action = request["action"]
            if action == "create":
                doc = dia.new("live-fixture.dia")
                state["doc"] = doc
                objects = []
                for i, name in enumerate(
                    [
                        "UML - Class",
                        "Flowchart - Box",
                        "ER - Entity",
                        "Database - Table",
                        "Cisco - PC",
                        "Circuit - Horizontal Resistor",
                        "Live - Unfamiliar",
                    ]
                ):
                    obj, _, _ = dia.get_object_type(name).create(i * 5, 3)
                    doc.active_layer.add_object(obj)
                    objects.append(obj)
                line, _, _ = dia.get_object_type("Standard - Line").create(0, 0)
                doc.active_layer.add_object(line)
                line.handles[0].connect(objects[0].connections[0])
                state["objects"] = objects
                state["line"] = line
                doc.display()
                doc.select(objects[0])
                doc.add_update_all()
                doc.flush()
            elif action == "stats":
                pass
            elif action == "close_active":
                doc = dia.active_display().diagram
                if doc.modified:
                    doc.save(str(root / "close-active.dia"))
                for display in doc.displays:
                    display.close()
            elif action == "dynamic_ports":
                obj = state["objects"][0]
                obj.properties["attributes"] = [
                    ("first", "int", "", "", 0, False, False),
                    ("second", "str", "", "", 0, False, False),
                ]
                state["doc"].add_update_all()
                state["doc"].flush()
            elif action == "hold_dispatch":
                from dia_mcp.live.plugin import _listener

                # Invoked only after a real socket handshake. Keep its idle
                # source queued until trusted shutdown can test cancellation.
                state["dispatch_original"] = _listener._dispatch
                _listener._dispatch = lambda: True
            elif action == "resume_dispatch":
                from dia_mcp.live.plugin import _listener

                if _listener.idle is not None:
                    GLib.source_remove(_listener.idle)
                    _listener.idle = None
                _listener._dispatch = state.pop("dispatch_original")
                if _listener.queue:
                    _listener.idle = GLib.idle_add(_listener._dispatch)
            elif action == "stop_listener":
                from dia_mcp.live.plugin import _listener

                _listener.stop()
            elif action == "move":
                state["objects"][0].move(12, 9)
                state["doc"].add_update_all()
                state["doc"].flush()
            elif action == "property":
                state["objects"][0].properties["name"] = "Changed from GUI side"
                state["doc"].add_update_all()
            elif action == "select":
                doc = state["doc"]
                for obj in doc.selected:
                    doc.unselect(obj)
                doc.select(state["objects"][1])
            elif action == "duplicate":
                state["doc"].active_layer.add_object(state["objects"][0].copy())
            elif action == "delete":
                state["doc"].unselect(state["objects"][0])
                state["doc"].active_layer.remove_object(state["objects"][0])
                # Keep it alive, as native undo does, then restore in another action.
            elif action == "restore":
                state["doc"].active_layer.add_object(state["objects"][0])
            elif action == "group":
                doc = state["doc"]
                for obj in doc.selected:
                    doc.unselect(obj)
                doc.select(state["objects"][1])
                doc.select(state["objects"][2])
                doc.group_selected()
            elif action == "layer":
                layer = state["doc"].add_layer("Extra", 0)
                state["doc"].set_active_layer(layer)
            elif action == "native_delete":
                doc = state["doc"]
                for obj in doc.selected:
                    doc.unselect(obj)
                doc.select(state["objects"][0])
                activate("EditDelete")
            elif action == "undo":
                activate("EditUndo")
            elif action == "redo":
                activate("EditRedo")
            elif action == "close":
                doc = state.pop("doc")
                doc.save(str(root / "saved.dia"))
                for display in doc.displays:
                    display.close()
                state.pop("objects", None)
                state.pop("line", None)
            elif action == "open":
                state["doc"] = dia.load(str(root / "saved.dia"))
                state["doc"].display()
            elif action == "quit":
                for index, doc in enumerate(dia.diagrams()):
                    if doc.modified:
                        doc.save(str(root / f"quit-{index}.dia"))

                activate("FileQuit")
            elif action != "status":
                raise ValueError("Unknown fixture command")
            result = {
                "ok": True,
                "listener": listener_stats(),
                "ticks": state["ticks"],
                "thread": threading.get_ident(),
                "display": Gdk.Display.get_default().__class__.__name__,
            }
            if "receipt_id" in request:
                from dia_mcp.live.plugin import _listener

                result["receipt"] = _listener.registry.receipts.status(request["receipt_id"])
        except Exception:
            result = {"ok": False, "error": traceback.format_exc()}
        (root / "reply.json").write_text(json.dumps(result))
        return action != "quit"

    GLib.timeout_add(50, poll)
