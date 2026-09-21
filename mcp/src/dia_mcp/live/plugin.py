"""Installed GUI startup hook; enabling it never changes the snapshot startup."""

import sys

_listener = None


def enable():
    from ..config import ConfigError, effective_config

    try:
        config = effective_config()
    except ConfigError as exc:
        print(f"Dia live configuration error (integration disabled): {exc}", file=sys.stderr)
        return
    if config["mode"] == "off":
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
            _listener = Listener(
                GLib,
                Registry(
                    dia,
                    writable=config["mode"] == "read-write",
                    files_root=config["files_root"] or "",
                ),
            )
            dia.register_shutdown(_listener.stop)
            print(f"Dia live socket: {_listener.path}", file=sys.stderr)
        except Exception as exc:
            print(f"Dia live integration unavailable: {exc}", file=sys.stderr)
        return False

    # Plugin loading precedes sheet loading and the GTK loop. Defer startup.
    GLib.idle_add(start)
