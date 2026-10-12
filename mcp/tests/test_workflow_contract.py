"""Workflow bounds, encoding and optional-domain independence."""

import subprocess
import sys

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.protocol import validate, validate_commands
from dia_mcp.live.registry import Registry


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "Standard - Box\0extra"),
        ("type", "\ud800"),
        ("property", "name\0extra"),
        ("property", "\ud800"),
        ("value", "\ud800"),
    ],
)
def test_native_strings_cannot_alias_c_names(field, value):
    command = {"op": "create", "type": "Standard - Box", "x": 1, "y": 1}
    if field == "property":
        command["properties"] = {value: "x"}
    elif field == "value":
        command["properties"] = {"name": value}
    else:
        command[field] = value
    with pytest.raises(DiaError):
        validate_commands([command])


@pytest.mark.parametrize("action", ["inspect_selection", "inspect_object_neighborhood"])
def test_compact_page_limit(action):
    request = {"protocol_version": 1, "action": action, "document_id": "d", "limit": 8}
    if action == "inspect_object_neighborhood":
        request["object_id"] = "o"
    assert validate(request) is request
    with pytest.raises(DiaError):
        validate({**request, "limit": 9})


def test_context_without_active_document():
    class Dia:
        @staticmethod
        def diagrams():
            return []

        @staticmethod
        def active_display():
            return None

    result = Registry(Dia).dispatch({"action": "get_current_context"})
    assert result["document"] is None
    assert result["selection"]["total"] == 0


def test_generic_imports_do_not_require_optional_analysis_or_recipes():
    script = """
import sys
from importlib.abc import MetaPathFinder
class Block(MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname in {"dia_mcp.semantics", "dia_mcp.recipes"}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, Block())
from dia_mcp.live.registry import Registry
from dia_mcp.live.planning import plan_selection
from dia_mcp.server import build_server
build_server(None)
from types import SimpleNamespace
hello = Registry(SimpleNamespace(application_version="test")).dispatch({"action": "handshake"})
assert "semantics.read" not in hello["capabilities"]
assert "objects.read" in hello["capabilities"]
assert plan_selection([{"object_id": "o", "position": {"x": 1, "y": 2}}],
                      "move", {"dx": 2, "dy": 0})["commands"][0]["x"] == 3
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
