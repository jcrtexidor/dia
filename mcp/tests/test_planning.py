"""Selection plans are pure data, not native executions or receipt reservations."""

import copy

import pytest

from dia_mcp.live.planning import LAYOUT_MODES, plan_selection
from dia_mcp.live.protocol import validate_commands


def selection():
    return [
        {
            "object_id": "a",
            "position": {"x": 1, "y": 2},
            "type": "Custom - Shape",
            "group_id": None,
        },
        {"object_id": "b", "position": {"x": 8, "y": 4}, "type": "UML - Class", "group_id": None},
    ]


def test_move_resolves_delta_from_observation_without_mutation():
    objects = selection()
    before = copy.deepcopy(objects)
    result = plan_selection(objects, "move", {"dx": 3, "dy": -1})
    assert result["commands"] == [
        {"op": "move", "object_id": "a", "x": 4, "y": 1},
        {"op": "move", "object_id": "b", "x": 11, "y": 3},
    ]
    assert objects == before
    assert result["affected_existing"] == ["a", "b"]
    assert result["objects_to_create"] == [] and result["mutates"] is False
    assert result["expected_structural_effect"]["explicit_attachment_changes"] == 0
    validate_commands(result["commands"])


@pytest.mark.parametrize("mode", sorted(LAYOUT_MODES))
def test_layout_uses_native_mode_not_synthetic_geometry(mode):
    result = plan_selection(selection(), "layout", {"mode": mode})
    assert result["commands"] == [{"op": "layout", "object_ids": ["a", "b"], "mode": mode}]
    validate_commands(result["commands"])


def test_bulk_property_plan_clones_input_and_keeps_native_checks_pending():
    props = {"text": "Label"}
    result = plan_selection(selection(), "set_properties", {"properties": props})
    assert [c["properties"] for c in result["commands"]] == [props, props]
    props["text"] = "changed after planning"
    assert all(c["properties"]["text"] == "Label" for c in result["commands"])
    assert any("native validation" in text for text in result["assumptions"])
    validate_commands(result["commands"])


@pytest.mark.parametrize(
    "properties",
    [
        {"items": [{"name": "text", "editable": False}], "truncated": False},
        {"items": [], "truncated": False},
    ],
)
def test_observed_property_incompatibility_rejects_entire_plan(properties):
    objects = selection()
    objects[1]["properties"] = properties
    with pytest.raises(ValueError):
        plan_selection(objects, "set_properties", {"properties": {"text": "x"}})


def test_truncated_descriptors_do_not_prove_property_absence():
    objects = selection()
    objects[0]["properties"] = {"items": [], "truncated": True}
    result = plan_selection(objects, "set_properties", {"properties": {"text": "x"}})
    assert len(result["commands"]) == 2
    assert any("complete descriptor evidence" in text for text in result["assumptions"])


@pytest.mark.parametrize(
    "objects,intent,options",
    [
        ([], "move", {"dx": 1, "dy": 1}),
        (selection() * 33, "layout", {"mode": "left"}),
        ([selection()[0]] * 2, "layout", {"mode": "left"}),
        ([selection()[0]], "layout", {"mode": "left"}),
        (selection(), "layout", {"mode": "magic"}),
        (selection(), "layer", {"layer_id": "other"}),
        (selection(), "move", {"dx": True, "dy": 1}),
        (selection(), "move", {"dx": float("nan"), "dy": 1}),
        (selection(), "move", {"dx": 10**1000, "dy": 1}),
        (selection(), "move", {"dx": 1_000_000, "dy": 1}),
        (selection(), "move", {"dx": 1, "dy": 1, "layer_id": "other"}),
        ([{"object_id": "a"}], "move", {"dx": 1, "dy": 1}),
        (
            [{"object_id": "a", "group_id": "group"}],
            "set_properties",
            {"properties": {"text": "x"}},
        ),
        (selection(), "set_properties", {"properties": {}}),
        (selection(), "set_properties", {"properties": {"array": [1, 2]}}),
        (selection(), "set_properties", {"properties": {"text": "x\0"}}),
    ],
)
def test_invalid_or_unrepresentable_plans_fail_closed(objects, intent, options):
    with pytest.raises(ValueError):
        plan_selection(objects, intent, options)


def test_raw_descriptor_policy_does_not_require_reading_property_values():
    objects = selection()
    objects[0]["properties"] = {
        "items": [{"name": "text", "type": "text", "visible": False, "load_only": False}],
        "truncated": False,
    }
    assert plan_selection(objects, "set_properties", {"properties": {"text": "x"}})["commands"]
    objects[0]["properties"]["items"][0]["load_only"] = True
    with pytest.raises(ValueError, match="not editable"):
        plan_selection(objects, "set_properties", {"properties": {"text": "x"}})
