"""Explicit CLI/GTK settings, separate from Dia's editor and native preferences."""

import argparse
import json
import os
import re
import stat
import sys
import threading
from itertools import islice
from pathlib import Path

from .config import (
    MODES,
    ConfigError,
    _directory,
    config_path,
    defaults,
    effective_config,
    load_config,
    save_config,
)


def running_status(env=None):
    """Read-only bounded handshakes with this user's private advertised endpoints."""
    env = os.environ if env is None else env
    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime:
        return {"endpoints": [], "truncated": False, "discovery": "XDG_RUNTIME_DIR is not set"}
    from .live.client import LiveClient

    directory = Path(runtime) / "dia-mcp"
    fd = None
    try:
        runtime_fd = _directory(Path(runtime), private=True)
        os.close(runtime_fd)
        fd = _directory(directory, private=True)
        with os.scandir(fd) as entries:
            names = [entry.name for entry in islice(entries, 257)]
        candidates = sorted(name for name in names[:256] if re.fullmatch(r"live-\d+\.sock", name))
        reports = []
        for name in candidates[:16]:
            path = directory / name
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (
                    not stat.S_ISSOCK(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                ):
                    raise ConfigError("Endpoint must be a private socket owned by this user")
                handshake = LiveClient(path, timeout=0.25).request("handshake")
                reports.append(
                    {
                        "path": str(path),
                        "status": "running",
                        "mode": handshake.get(
                            "integration_mode",
                            "read-write" if handshake.get("writable") else "read-only",
                        ),
                        "files_root": handshake.get("files_root"),
                        "files_root_known": "files_root" in handshake,
                        "capabilities": handshake.get("capabilities", []),
                        "session_id": handshake.get("session_id"),
                    }
                )
            except Exception as exc:
                reports.append(
                    {"path": str(path), "status": "unavailable", "error": str(exc)[:512]}
                )
        return {
            "endpoints": reports,
            "truncated": len(names) > 256 or len(candidates) > 16,
            "discovery": "private per-user sockets; handshake only",
        }
    except FileNotFoundError:
        return {"endpoints": [], "truncated": False, "discovery": "No live endpoint directory"}
    except (OSError, ConfigError) as exc:
        return {"endpoints": [], "truncated": False, "discovery_error": str(exc)}
    finally:
        if fd is not None:
            os.close(fd)


def status(env=None):
    env = os.environ if env is None else env
    desired, effective = load_config(env=env), effective_config(env=env)
    running = running_status(env)
    endpoints = running["endpoints"]
    current = [item for item in endpoints if item["status"] == "running"]
    mismatch = any(
        item["mode"] != effective["mode"]
        or not item["files_root_known"]
        or item["files_root"] != effective["files_root"]
        for item in current
    )
    return {
        "config_path": str(config_path(env)),
        "desired": desired,
        "effective": effective,
        "running": running,
        "restart_required": mismatch or (not current and effective["mode"] != "off"),
        "status_incomplete": running["truncated"]
        or "discovery_error" in running
        or any(item["status"] != "running" for item in endpoints),
        "application": "Settings affect the next Dia startup; existing processes are not changed.",
    }


def create_window():
    """Construct the optional GTK3 UI. Importing config/CLI does not require GTK."""
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    window = Gtk.Window(title="Dia MCP settings")
    window.set_default_size(680, 600)
    window.set_border_width(24)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    window.add(body)
    title = Gtk.Label(xalign=0)
    title.set_markup('<span size="x-large" weight="bold">Dia integration</span>')
    body.pack_start(title, False, False, 0)
    description = Gtk.Label(
        label="Choose access for the next Dia startup. Existing windows keep "
        "their current settings.",
        xalign=0,
    )
    description.set_line_wrap(True)
    body.pack_start(description, False, False, 0)
    config_error = None
    try:
        saved = load_config()
    except ConfigError as exc:
        saved, config_error = defaults(), str(exc)
    radios, group = {}, None
    for mode, label in (
        ("off", "Off — no live endpoint"),
        ("read-only", "Read only — inspect open diagrams"),
        ("read-write", "Read and write — edit through native undo history"),
    ):
        radio = Gtk.RadioButton.new_with_label_from_widget(group, label)
        if group is None:
            group = radio
        radio.set_active(saved["mode"] == mode)
        radios[mode] = radio
        body.pack_start(radio, False, False, 0)
    body.pack_start(
        Gtk.Label(label="Optional directory for native file operations", xalign=0), False, False, 0
    )
    root = Gtk.Entry()
    root.set_placeholder_text("Existing absolute directory; leave empty to disable file operations")
    root.set_text(saved["files_root"] or "")
    root_row = Gtk.Box(spacing=10)
    root_row.pack_start(root, True, True, 0)
    choose = Gtk.Button(label="Choose folder…")
    root_row.pack_end(choose, False, False, 0)
    body.pack_start(root_row, False, False, 0)

    def choose_folder(*_args):
        chooser = Gtk.FileChooserDialog(
            title="Choose directory for Dia file operations",
            transient_for=window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Choose", Gtk.ResponseType.ACCEPT)
        chooser.set_create_folders(False)
        if root.get_text() and os.path.isdir(root.get_text()):
            chooser.set_filename(root.get_text())
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            root.set_text(chooser.get_filename())
        chooser.destroy()

    choose.connect("clicked", choose_folder)
    notice = Gtk.Label(
        label="Configuration error: " + config_error if config_error else "", xalign=0
    )
    notice.set_line_wrap(True)
    notice.set_selectable(True)
    body.pack_start(notice, False, False, 0)
    observed = Gtk.Label(label="Checking running sessions…", xalign=0)
    observed.set_line_wrap(True)
    observed.set_selectable(True)
    observed.set_max_width_chars(68)
    observed.set_width_chars(55)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_min_content_height(180)
    scroller.add(observed)
    body.pack_start(scroller, True, True, 0)
    actions = Gtk.Box(spacing=10)
    refresh = Gtk.Button(label="Refresh status")
    save = Gtk.Button(label="Save for next startup")
    actions.pack_start(refresh, False, False, 0)
    actions.pack_end(save, False, False, 0)
    body.pack_end(actions, False, False, 0)
    alive = [True]

    def show_report(report, error):
        if not alive[0]:
            return False
        refresh.set_sensitive(True)
        if error:
            observed.set_text(
                "Cannot read next-start configuration: "
                + error
                + ". Existing sessions retain their current settings."
            )
            return False
        lines = [
            "Saved mode: " + report["desired"]["mode"],
            "Effective next-start mode: "
            + report["effective"]["mode"]
            + " ("
            + report["effective"]["source"]
            + ")",
        ]
        for endpoint in report["running"]["endpoints"]:
            lines.append(endpoint["path"] + " — " + endpoint.get("mode", endpoint["status"]))
        if not report["running"]["endpoints"]:
            lines.append("No running live endpoint detected.")
        if report["status_incomplete"]:
            lines.append(
                "Status is incomplete; inspect endpoint/configuration errors with --status."
            )
        if report["restart_required"]:
            lines.append("Start or restart Dia to apply the effective configuration.")
        lines.append("Configuration: " + report["config_path"])
        observed.set_text("\n".join(lines))
        return False

    def refresh_status(*_args):
        refresh.set_sensitive(False)

        def probe():
            try:
                report, error = status(), None
            except Exception as exc:
                report, error = None, str(exc)
            GLib.idle_add(show_report, report, error)

        threading.Thread(target=probe, daemon=True).start()

    def save_settings(*_args):
        try:
            mode = next(mode for mode, radio in radios.items() if radio.get_active())
            save_config({"schema_version": 1, "mode": mode, "files_root": root.get_text() or None})
            notice.set_text("Saved. Existing Dia processes were not changed.")
            refresh_status()
        except ConfigError as exc:
            notice.set_text(
                ("Publication warning: " if exc.published else "Not saved: ") + str(exc)
            )

    def closed(*_args):
        alive[0] = False
        Gtk.main_quit()

    save.connect("clicked", save_settings)
    refresh.connect("clicked", refresh_status)
    window.connect("destroy", closed)
    refresh_status()
    return window


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES)
    roots = parser.add_mutually_exclusive_group()
    roots.add_argument("--files-root")
    roots.add_argument("--clear-files-root", action="store_true")
    parser.add_argument(
        "--status", action="store_true", help="Print JSON desired/effective/running status"
    )
    parser.add_argument("--gui", action="store_true", help="Open separate GTK3 settings window")
    args = parser.parse_args(argv)
    if args.gui and (
        args.mode or args.files_root is not None or args.clear_files_root or args.status
    ):
        parser.error("--gui cannot be combined with CLI configuration/status options")
    saved = False
    try:
        if args.gui:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk

            window = create_window()
            window.show_all()
            Gtk.main()
            return 0
        if args.mode or args.files_root is not None or args.clear_files_root:
            config = load_config()
            if args.mode:
                config["mode"] = args.mode
            if args.files_root is not None or args.clear_files_root:
                config["files_root"] = None if args.clear_files_root else args.files_root
            save_config(config)
            saved = True
        print(json.dumps(status(), ensure_ascii=False))
        return 0
    except (ConfigError, ImportError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "settings_published": saved or getattr(exc, "published", False),
                    "running_sessions_changed": False,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
