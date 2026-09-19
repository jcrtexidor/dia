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
                "ticks": state["ticks"],
                "thread": threading.get_ident(),
                "display": Gdk.Display.get_default().__class__.__name__,
            }
        except Exception:
            result = {"ok": False, "error": traceback.format_exc()}
        (root / "reply.json").write_text(json.dumps(result))
        return action != "quit"

    GLib.timeout_add(50, poll)
