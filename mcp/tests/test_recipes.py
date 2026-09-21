import pytest

from dia_mcp.live.protocol import validate_commands
from dia_mcp.recipes import plan_native
from dia_mcp.semantics import analyze_graph


@pytest.mark.parametrize(
    "domain,kind,prop",
    [
        ("flowchart", "Flowchart - Box", "text"),
        ("uml", "UML - Class", "name"),
        ("database", "Database - Table", "name"),
        ("network", "Network - Base Station", "text"),
    ],
)
def test_plan_is_generic_transaction_input(domain, kind, prop):
    nodes = [{"x": 1, "y": 2, "label": "á"}]
    result = plan_native(domain, nodes)
    assert result["mutates"] is False
    assert result["commands"] == [
        {"op": "create", "type": kind, "x": 1, "y": 2, "properties": {prop: "á"}}
    ]
    validate_commands(result["commands"])
    assert nodes == [{"x": 1, "y": 2, "label": "á"}]
    assert any("indices" in text for text in result["followup"])


@pytest.mark.parametrize(
    "node",
    [
        {"x": True, "y": 2},
        {"x": float("nan"), "y": 2},
        {"x": 0, "y": 1e7},
        {"x": 0, "y": 2, "type": "Custom - Box"},
        {"x": 0, "y": 2, "type": "Database - Table"},
        {"x": 0, "y": 2, "label": "bad\0"},
        {"x": 0, "y": 2, "label": "x" * 2049},
        {"x": 0, "y": 2, "ports": [0]},
        {"x": 0},
    ],
)
def test_plan_rejects_unverified_or_unbounded_input(node):
    with pytest.raises(ValueError):
        plan_native("flowchart", [node])


def test_recipe_limits_and_native_type_variants():
    with pytest.raises(ValueError):
        plan_native("network", [])
    with pytest.raises(ValueError):
        plan_native("network", [{"x": 0, "y": 0}] * 65)
    with pytest.raises(ValueError):
        plan_native("electrical", [{"x": 0, "y": 0}])
    result = plan_native("flowchart", [{"type": "Flowchart - Diamond", "x": 0, "y": 0}])
    assert result["commands"][0]["type"] == "Flowchart - Diamond"


def test_circuit_and_pneumatic_native_families_are_explicit_evidence():
    result = analyze_graph(
        [
            {"object_id": "a", "type": "Circuit - Resistor"},
            {"object_id": "b", "type": "Pneum - DEJack"},
        ],
        {},
    )
    assert result["classification"] == "mixed"
    assert result["domains"] == ["electrical", "pneumatic"]


def test_recipe_plan_metadata_declares_creation_without_attachments():
    plan = plan_native("network", [{"x": 1, "y": 2, "label": "Base"}])
    assert plan["affected_existing"] == []
    assert len(plan["objects_to_create"]) == 1
    assert plan["expected_structural_effect"]["created_objects"] == 1
    assert plan["expected_structural_effect"]["explicit_attachment_changes"] == 0
    assert plan["assumptions"] and plan["unsupported_semantics"]
