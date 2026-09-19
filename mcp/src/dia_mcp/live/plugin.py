"""Installed GUI startup hook; enabling it never changes the snapshot startup."""

import os
import sys

_listener = None


def enable():
    if os.environ.get("DIA_MCP_LIVE") != "1":
        return
    import dia
    from gi.repository import GLib

    from .listener import Listener
    from .registry import Registry

    def start():
        global _listener
        try:
            if not hasattr(dia, "application_version") or not hasattr(dia.Diagram, "live_state"):
                raise RuntimeError("This Dia build lacks the M2 native lifetime hooks")
            _listener = Listener(GLib, Registry(dia))
            dia.register_shutdown(_listener.stop)
            print(f"Dia live read socket: {_listener.path}", file=sys.stderr)
        except Exception as exc:
            print(f"Dia live integration unavailable: {exc}", file=sys.stderr)
        return False

    # Plugin loading precedes sheet loading and the GTK loop. Defer startup.
    GLib.idle_add(start)
