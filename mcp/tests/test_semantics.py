import pytest

from dia_mcp.native.catalog import validate_uml
from dia_mcp.native.uml import configure_class
from dia_mcp.semantics import analyze_graph


def test_mixed_custom_sheet_is_not_exclusive_domain():
    result = analyze_graph(
        [
            {"object_id": "a", "type": "Flowchart - Box"},
            {"object_id": "b", "type": "UML - Class"},
            {"object_id": "c", "type": "Custom box", "sheet_entries": ["UML"]},
        ],
        {},
    )
    assert result["classification"] == "mixed"
    assert result["unknown_objects"] == ["c"]
    assert result["coverage"]["missing_connections"] == ["a", "b", "c"]
    assert result["components"] == [["a"], ["b"], ["c"]]


def test_native_generalization_start_is_superclass_not_handle_list_order():
    objects = [{"object_id": x, "type": "UML - Class"} for x in ("base", "child")]
    objects.append({"object_id": "edge", "type": "UML - Generalization"})
    connections = {
        "edge": {
            "handles": [
                {"id": 9, "attached_to": {"object_id": "child"}},
                {"id": 8, "attached_to": {"object_id": "base"}},
            ]
        }
    }
    result = analyze_graph(objects, connections)
    assert result["components"] == [["base", "child", "edge"]]
    assert result["findings"][0]["superclass"] == "base"
    assert result["findings"][0]["subclass"] == "child"
    objects[-1]["type"] = "Custom - Generalization"
    assert analyze_graph(objects, connections)["findings"] == []


def test_visual_touching_and_arbitrary_sheet_do_not_connect():
    objects = [{"object_id": x, "type": "Network - Router", "position": [0, 0]} for x in ("a", "b")]
    result = analyze_graph(objects, {"a": {}, "b": {}})
    assert result["isolated_objects"] == ["a", "b"]
    assert result["findings"] == []


def test_connection_points_and_external_coverage():
    result = analyze_graph(
        [{"object_id": "a", "type": "Database - Table"}],
        {"a": {"connection_points": [{"connected_objects": ["outside"]}]}},
    )
    assert result["coverage"]["external_objects"] == ["outside"]
    assert any("primary-key" in text for text in result["limitations"])
    assert result["findings"] == []


def test_analysis_budgets_and_duplicate_ids():
    with pytest.raises(ValueError, match="unique"):
        analyze_graph([{"object_id": "a"}] * 2, {})
    with pytest.raises(ValueError, match="500"):
        analyze_graph([{}] * 501, {})
    with pytest.raises(ValueError, match="domain"):
        analyze_graph([], {}, "invented")


def test_extracted_uml_tuple_contract_and_validation():
    class Object:
        properties = {}

    obj = Object()
    node = {
        "text": "Class",
        "width": 4,
        "properties": {
            "attributes": [{"name": "id"}],
            "operations": [{"name": "run", "parameters": [{"name": "arg"}]}],
        },
    }
    validate_uml(node["properties"])
    configure_class(obj, node)
    assert obj.properties["attributes"] == [("id", "", "", "", 1, False, False)]
    assert obj.properties["operations"] == [
        ("run", "", "", "", 0, 2, False, False, [("arg", "", "", "", 0)])
    ]
    with pytest.raises(ValueError, match="invalid abstract flag"):
        validate_uml({"abstract": 1})


def test_native_connection_point_incidence_is_undirected_evidence():
    objects = [{"object_id": x, "type": "Flowchart - Box"} for x in ("a", "b")]
    result = analyze_graph(
        objects, {"a": {"connection_points": [{"connected_objects": ["b"]}]}, "b": {}}
    )
    assert result["components"] == [["a", "b"]]
    assert result["isolated_objects"] == []
    assert result["findings"] == []
    assert any("flow direction" in text for text in result["limitations"])


def test_partial_or_ambiguous_generalization_cannot_prove_relationship():
    objects = [{"object_id": x, "type": "UML - Class"} for x in ("a", "b")]
    objects.append({"object_id": "edge", "type": "UML - Generalization"})
    start = {"id": 8, "attached_to": {"object_id": "a"}}
    end = {"id": 9, "attached_to": {"object_id": "b"}}
    for handles in ([start], [start, start, end]):
        assert analyze_graph(objects, {"edge": {"handles": handles}})["findings"] == []


def test_evidence_separates_native_group_facts_overlap_and_attachment_hints():
    objects = [
        {
            "object_id": "a",
            "type": "Custom",
            "layer_id": "l",
            "group_id": "g",
            "bounds": {"left": 0, "top": 0, "right": 2, "bottom": 2},
        },
        {
            "object_id": "b",
            "type": "Custom",
            "layer_id": "l",
            "group_id": None,
            "bounds": {"left": 1, "top": 1, "right": 3, "bottom": 3},
        },
    ]
    connections = {
        "a": {
            "handles": [
                {"index": 7, "id": 200, "connect_type": 1, "attached_to": None},
                {"index": 8, "id": 201, "connect_type": 0, "attached_to": None},
                {"index": 9, "id": 202, "connect_type": 1},
            ]
        }
    }
    result = analyze_graph(objects, connections)
    levels = result["evidence_levels"]
    assert levels["native_facts"]["layer_object_counts"] == {"l": 2}
    assert levels["native_facts"]["group_member_counts"] == {"g": 1}
    assert levels["derived_structure"]["component_count"] == 2
    assert levels["heuristics"]["bbox_overlaps"]["items"][0]["object_ids"] == ["a", "b"]
    assert levels["heuristics"]["unattached_connectable_handles"]["items"] == [
        {"object_id": "a", "handle_index": 7, "handle_id": 200}
    ]
    assert result["findings"] == []  # no missing connector or collision claim


def test_heuristic_evidence_has_explicit_budgets_and_coverage():
    objects = [
        {
            "object_id": str(i),
            "type": "Custom",
            "bounds": {"left": 0, "top": 0, "right": 1, "bottom": 1},
        }
        for i in range(14)
    ]
    connections = {
        "0": {"handles": [{"index": i, "connect_type": 2, "attached_to": None} for i in range(70)]}
    }
    heuristics = analyze_graph(objects, connections)["evidence_levels"]["heuristics"]
    overlap = heuristics["bbox_overlaps"]
    assert len(overlap["items"]) == 64 and overlap["total"] == 91 and overlap["truncated"]
    handles = heuristics["unattached_connectable_handles"]
    assert len(handles["items"]) == 64 and handles["total"] == 70 and handles["truncated"]


def test_touching_or_invalid_bounds_are_not_reported_as_positive_overlap():
    objects = [
        {"object_id": "a", "bounds": {"left": 0, "top": 0, "right": 1, "bottom": 1}},
        {"object_id": "b", "bounds": {"left": 1, "top": 0, "right": 2, "bottom": 1}},
        {"object_id": "c", "bounds": {"left": float("nan"), "top": 0, "right": 1, "bottom": 1}},
    ]
    overlap = analyze_graph(objects, {})["evidence_levels"]["heuristics"]["bbox_overlaps"]
    assert overlap["items"] == [] and overlap["total"] == 0
    assert overlap["missing_or_invalid_bounds"] == ["c"]
