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
