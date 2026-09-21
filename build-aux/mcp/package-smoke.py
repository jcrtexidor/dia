#!/usr/bin/env python3
"""Installed-package acceptance in a clean account, without pytest or checkout.

GTK selection/history actions are exercised by an explicit temporary test plugin;
these automated checks do not claim human visual acceptance.
"""

import argparse
import asyncio
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dia_mcp.errors import DiaError
from dia_mcp.live.client import LiveClient

DRIVER = """import json
import os
from pathlib import Path
import dia
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk
root = Path(os.environ["HOME"])
def activate(name):
    seen = set()
    def visit(widget):
        if widget in seen: return False
        seen.add(widget)
        if isinstance(widget, Gtk.Activatable):
            action = widget.get_related_action()
            if action and action.get_name() == name:
                action.activate()
                return True
        children = widget.get_children() if isinstance(widget, Gtk.Container) else []
        if isinstance(widget, Gtk.MenuItem) and widget.get_submenu():
            children.append(widget.get_submenu())
        return any(visit(child) for child in children)
    if not any(visit(window) for window in Gtk.Window.list_toplevels()):
        raise RuntimeError("GTK action unavailable: " + name)
def poll():
    command = root / "driver-command.json"
    if not command.exists(): return True
    action = json.loads(command.read_text())["action"]
    command.unlink()
    try:
        if action in {"select", "select_two"}:
            doc = dia.active_display().diagram
            for obj in doc.selected: doc.unselect(obj)
            boxes = [o for layer in doc.layers for o in layer.objects
                     if o.type.name == "Standard - Box"]
            for obj in boxes[:2 if action == "select_two" else 1]: doc.select(obj)
            doc.add_update_all()
            doc.flush()
        elif action == "undo": activate("EditUndo")
        elif action == "redo": activate("EditRedo")
        elif action == "quit":
            for index, doc in enumerate(dia.diagrams()):
                if doc.modified: doc.save(str(root / f"acceptance-quit-{index}.dia"))
            activate("FileQuit")
        else: raise ValueError("Unknown acceptance action")
        result = {"ok": True}
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    (root / "driver-result.json").write_text(json.dumps(result))
    return True
GLib.timeout_add(50, poll)
"""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def wait(predicate, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for installed GUI acceptance state")


def configure(env, *args):
    result = subprocess.run(
        ["/usr/bin/dia-mcp-config", *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return json.loads(result.stdout)


@contextmanager
def gui(root, env, mode):
    log_path = root / f"gui-{mode}.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            ["/usr/bin/dia-fork", "--nosplash"], env=env, stdout=log, stderr=log
        )
        socket = Path(env["XDG_RUNTIME_DIR"]) / "dia-mcp" / f"live-{process.pid}.sock"
        try:
            if mode == "off":
                time.sleep(1.5)
                require(process.poll() is None, "Normal installed GUI exited")
                require(not socket.exists(), "Default-off GUI unexpectedly exposed MCP")
                yield None
            else:

                def ready():
                    require(process.poll() is None, "Configured installed GUI exited")
                    return socket.exists()

                wait(ready)
                client = LiveClient(socket)
                require(
                    client.request("handshake")["integration_mode"] == mode,
                    "GUI did not read persistent mode after restart",
                )
                yield client
        finally:
            if process.poll() is None:
                try:
                    driver(Path(env["HOME"]), "quit")
                    process.wait(timeout=5)
                except Exception:
                    process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            content = log.read()
            if sys.exc_info()[0] is not None:
                print(f"GUI {mode} diagnostics: {content[-4000:]}", file=sys.stderr)
            require(
                "could not import mcp-live" not in content,
                "Installed startup import failed",
            )


def perform(client, action, did=None, **kwargs):
    kwargs["request_id"] = client.request("prepare_operation")["request_id"]
    if did is not None:
        kwargs.update(
            document_id=did,
            expected_generation=client.request("get_document", document_id=did)[
                "generation"
            ],
        )
    return client.request(action, **kwargs)


def driver(root, action):
    result = root / "driver-result.json"
    result.unlink(missing_ok=True)
    staging = root / "driver-command.tmp"
    staging.write_text(json.dumps({"action": action}))
    staging.replace(root / "driver-command.json")
    wait(result.exists)
    reply = json.loads(result.read_text())
    require(reply["ok"], f"Automated GTK action failed: {reply}")


async def stdio(env, workspace, client=None):
    args = ["--workspace", str(workspace)]
    if client:
        args += ["--live-socket", client.path]
    params = StdioServerParameters(command="/usr/bin/dia-mcp", args=args, env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            require(
                {"create_document", "live_handshake"} <= names,
                "Installed tools missing",
            )
            if client:
                result = await session.call_tool("live_handshake", {})
                require(not result.isError, "Packaged stdio-to-GUI handshake failed")
                resources = await session.list_resources()
                require(
                    any(
                        str(r.uri) == "dia://live/documents"
                        for r in resources.resources
                    ),
                    "Installed live resource missing",
                )
                prompts = await session.list_prompts()
                require(
                    any(p.name == "explain_live_diagram" for p in prompts.prompts),
                    "Installed live prompt missing",
                )
            else:
                result = await session.call_tool(
                    "create_document", {"name": "Headless package"}
                )
                require(
                    not result.isError, "Headless snapshot document creation failed"
                )
                # Native factory materialization proves automatic Xvfb and worker startup.
                document = json.loads(result.content[0].text)["document"]
                result = await session.call_tool(
                    "create_object",
                    {
                        "document_id": document["id"],
                        "type": "Flowchart - Box",
                        "text": "Installed",
                    },
                )
                require(not result.isError, "Headless native snapshot factory failed")


def acceptance(root):
    require(os.geteuid() != 0, "Run smoke as an ordinary user")
    for path in ("/src/dia", "/checkout", "/opt/dia-build"):
        require(
            not Path(path).exists(), f"Fresh runtime contains builder artifacts: {path}"
        )
    require(shutil.which("cc") is None, "Fresh runtime must not contain build tools")
    library_env = dict(os.environ, LD_LIBRARY_PATH="/opt/dia/lib")
    elf_count = 0
    for prefix in (Path("/opt/dia"), Path("/opt/dia-mcp-venv")):
        for path in prefix.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            with path.open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    continue
            linked = subprocess.run(
                ["ldd", str(path)],
                env=library_env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            require(
                linked.returncode == 0 and "not found" not in linked.stdout,
                f"Installed shared dependency unresolved: {path}: {linked.stdout}",
            )
            elf_count += 1
    require(elf_count >= 37, "Installed native plugins are missing")
    version = importlib.metadata.version("dia-operations-mcp")
    require(version == "0.3.0", "Wrong installed adapter version")
    home = root / "home"
    home.mkdir(mode=0o700)
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    files = root / "documents"
    files.mkdir()
    env = dict(
        os.environ,
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_RUNTIME_DIR=str(runtime),
    )
    for key in tuple(env):
        if key.startswith("DIA_MCP") or key in {
            "PYTHONPATH",
            "PYTHONHOME",
            "DIA_PYTHON_PATH",
            "VIRTUAL_ENV",
        }:
            env.pop(key)
    # The driver only performs explicit local GTK acceptance actions.
    plugins = home / ".dia" / "python"
    plugins.mkdir(parents=True)
    (plugins / "package_acceptance.py").write_text(DRIVER)
    checks = ["all_installed_ELF_dependencies_resolve"]
    status = configure(env, "--status")
    require(status["desired"]["mode"] == "off", "Fresh configuration is not off")
    with gui(root, env, "off"):
        checks.append("default_off_no_socket")
    configure(env, "--mode", "read-only")
    with gui(root, env, "read-only") as client:
        hello = client.request("handshake")
        require(not hello["writable"], "Read-only configuration advertised writes")
        require(
            client.request("list_documents")["items"], "Default GUI document missing"
        )
        try:
            client.request("prepare_operation")
        except DiaError as error:
            require(
                error.code in {"LIVE_WRITE_DISABLED", "UNSUPPORTED_LIVE_CAPABILITY"},
                "Unexpected read-only mutation failure",
            )
        else:
            raise AssertionError("Read-only GUI accepted mutation preparation")
        running = configure(env, "--status")["running"]["endpoints"]
        require(
            any(
                item.get("path") == client.path
                and item.get("mode") == "read-only"
                and item.get("status") == "running"
                for item in running
            ),
            "Config CLI did not discover the running read-only GUI",
        )
        checks.append("persistent_read_only_after_restart")
    configure(env, "--mode", "read-write", "--files-root", str(files))
    with gui(root, env, "read-write") as client:
        hello = client.request("handshake")
        require(hello["writable"], "Read-write configuration not active")
        require(
            hello["files_root"] == str(files), "Configured files root was not applied"
        )
        running = configure(env, "--status")["running"]["endpoints"]
        require(
            any(
                item.get("path") == client.path
                and item.get("mode") == "read-write"
                and item.get("files_root") == str(files)
                and item.get("status") == "running"
                for item in running
            ),
            "Config CLI did not discover the writable GUI/root",
        )
        did = client.request("get_active_document")["document"]["document_id"]
        created = perform(
            client,
            "apply_commands",
            did,
            commands=[
                {"op": "create", "type": "Standard - Box", "x": 1, "y": 1},
                {"op": "create", "type": "Standard - Box", "x": 10, "y": 4},
                {"op": "create", "type": "Standard - Line", "x": 1, "y": 1},
                {"op": "create", "type": "Flowchart - Box", "x": 1, "y": 12},
                {"op": "create", "type": "UML - Class", "x": 10, "y": 12},
            ],
        )["created"]
        perform(
            client,
            "apply_commands",
            did,
            commands=[
                {
                    "op": "connect",
                    "object_id": created[2],
                    "handle": 0,
                    "target_id": created[0],
                    "point": 0,
                },
                {
                    "op": "connect",
                    "object_id": created[2],
                    "handle": 1,
                    "target_id": created[1],
                    "point": 0,
                },
            ],
        )
        driver(home, "select_two")
        context = client.request("get_current_context")
        require(
            context["document"]["document_id"] == did
            and context["selection"]["total"] == 2,
            "Multiple GUI selection was not reflected in compact context",
        )
        before_layout = {
            item["object_id"]: item["position"]
            for item in client.request("get_selection", document_id=did)["items"]
        }
        plan = client.request(
            "plan_selection", document_id=did, intent="layout", options={"mode": "left"}
        )
        checked = client.request(
            "validate_commands",
            document_id=did,
            expected_generation=plan["generation"],
            commands=plan["commands"],
        )
        require(
            checked["valid"] and not checked["mutates"],
            "Installed layout preview rejected",
        )
        require(
            client.request("get_document", document_id=did)["generation"]
            == plan["generation"],
            "Planning/validation changed the document",
        )
        client.request(
            "apply_commands",
            document_id=did,
            expected_generation=plan["generation"],
            request_id=client.request("prepare_operation")["request_id"],
            commands=plan["commands"],
        )
        aligned = client.request("get_selection", document_id=did)["items"]
        require(
            len({item["position"]["x"] for item in aligned}) == 1,
            "Installed layout did not align selected objects",
        )
        driver(home, "undo")
        restored_layout = {
            item["object_id"]: item["position"]
            for item in client.request("get_selection", document_id=did)["items"]
        }
        require(
            restored_layout == before_layout, "GUI Undo did not restore reviewed layout"
        )
        checks.append("multiple_selection_context_plan_validate_align_GUI_undo")
        driver(home, "select")
        selected = client.request("get_selection", document_id=did)["items"]
        require(len(selected) == 1, "Automated GUI selection not visible through MCP")
        moved_id = selected[0]["object_id"]
        before = client.request("get_object", document_id=did, object_id=moved_id)[
            "object"
        ]["position"]
        perform(
            client,
            "apply_commands",
            did,
            commands=[
                {"op": "move", "object_id": moved_id, "x": 4, "y": 5},
            ],
        )
        driver(home, "undo")
        after = client.request("get_object", document_id=did, object_id=moved_id)[
            "object"
        ]["position"]
        require(after == before, "Native GTK Undo did not restore the MCP move")
        driver(home, "redo")
        restored = client.request("get_object", document_id=did, object_id=moved_id)[
            "object"
        ]["position"]
        require(
            restored == {"x": 4.0, "y": 5.0}, "Native GTK Redo did not restore the move"
        )
        checks.append("automated_GTK_selection_undo_redo_not_human_visual_review")
        target = files / "package.dia"
        perform(client, "save_document_as", did, path=str(target))
        for fmt in ("svg", "png"):
            exported = files / f"package.{fmt}"
            perform(client, "export_document", did, path=str(exported), format=fmt)
            require(exported.stat().st_size > 0, f"Empty installed {fmt} export")
        reopened = perform(client, "open_document", path=str(target))["document"][
            "document_id"
        ]
        require(
            client.request("list_objects", document_id=reopened)["total"] == 5,
            "Native save/open lost objects",
        )
        require(
            len(client.request("list_documents")["items"]) >= 2,
            "Opening another document replaced the original",
        )
        require(
            client.request("list_objects", document_id=did)["total"] == 5,
            "Original document was lost while opening another document",
        )
        checks.append("native_create_connect_save_reopen_svg_png_multiple_documents")
        asyncio.run(stdio(env, root / "live-workspace", client))
        checks.append("installed_stdio_live_tools_resources_prompts")
    with gui(root, env, "read-write") as restarted:
        restarted_hello = restarted.request("handshake")
        require(
            restarted_hello["session_id"] != hello["session_id"],
            "GUI restart retained the old live session",
        )
        try:
            restarted.request("get_document", document_id=did)
        except DiaError as error:
            require(
                error.code == "WRONG_SESSION", "Old document reference was not fenced"
            )
        else:
            raise AssertionError("Restarted GUI accepted the old document reference")
        reopened = perform(restarted, "open_document", path=str(target))["document"][
            "document_id"
        ]
        require(
            restarted.request("list_objects", document_id=reopened)["total"] == 5,
            "Reopen after GUI restart lost native objects",
        )
        require(
            restarted.request("get_current_context")["document"]["document_id"]
            == reopened,
            "Restarted GUI context did not point to the reopened document",
        )
        asyncio.run(stdio(env, root / "restarted-workspace", restarted))
        checks.append("GUI_restart_reopen_old_session_rejected")
    headless = {
        key: value
        for key, value in env.items()
        if key not in {"DISPLAY", "WAYLAND_DISPLAY"}
    }
    asyncio.run(stdio(headless, root / "snapshot-workspace"))
    checks.append("headless_snapshot_auto_xvfb")
    configure(env, "--mode", "off")
    with gui(root, env, "off"):
        checks.append("persistent_disable_after_restart")
    return {
        "status": "passed",
        "versions": {
            "native": hello["dia_version"],
            "adapter": version,
            "live": hello["integration_api_version"],
            "snapshot": "1",
            "package": subprocess.check_output(
                ["dpkg-query", "-W", "-f=${Version}", "dia-mcp-fork"], text=True
            ),
        },
        "checks": [{"name": name, "status": "passed"} for name in checks],
        "user_uid": os.getuid(),
        "configuration": "persistent CLI; no live environment flags",
        "gui_acceptance": "automated GTK plugin actions, not human visual acceptance",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"status": "failed"}
    try:
        with tempfile.TemporaryDirectory(prefix="dia-package-smoke-") as folder:
            report = acceptance(Path(folder))
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Installed package smoke: PASS")


if __name__ == "__main__":
    main()
