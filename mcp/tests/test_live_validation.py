"""Static previews must never instantiate factories, fetch values, or mutate."""

import copy
from types import SimpleNamespace

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.protocol import Limits
from dia_mcp.live.validation import validate_batch


class Object:
    def __init__(self, descriptors=(), truncated=False):
        self.descriptors = list(descriptors)
        self.truncated = truncated
        self.reads = 0
        self.handles = [SimpleNamespace(connect_type=1, connected_to=None)]
        self.connections = [SimpleNamespace(connected=[])]
        self.parent = None
        self.children = []

    def property_descriptors(self, limit):
        assert limit == 256
        self.reads += 1
        return {
            "items": self.descriptors[:limit],
            "truncated": self.truncated,
            "total": len(self.descriptors) + (1 if self.truncated else 0),
        }

    @property
    def properties(self):
        pytest.fail("Property values must not be fetched during static validation")

    def move(self, *args):
        pytest.fail("Static validation must not execute moves")


class Native:
    def __init__(self, types):
        self.types = dict.fromkeys(types, self)

    def registered_types(self):
        return self.types

    def create(self, *args):
        pytest.fail("Static validation must not instantiate a factory")

    def get_object_type(self, *args):
        pytest.fail("Use the read-only registry; never request an executable factory")

    def live_apply(self, *args):
        pytest.fail("Static validation must not probe native transactions")

    def live_history(self, *args):
        pytest.fail("Static validation must not use rollback as a probe")


class Registry:
    def __init__(self):
        self.dia = Native([f"Installed - Type {i:03}" for i in range(30)])
        self.limits = Limits()
        self.main_checked = False

    def _assert_main(self):
        self.main_checked = True

    def _check_session(self, reference):
        if not reference.startswith("live:s:"):
            raise DiaError("WRONG_SESSION", "Reference belongs to another session")

    def _layer_id(self, did, layer):
        return f"{did}:layer:{layer.name}"


def descriptor(name, kind="string", visible=True, load_only=False):
    return {"name": name, "type": kind, "visible": visible, "load_only": load_only}


@pytest.fixture
def scene():
    registry = Registry()
    layer = SimpleNamespace(name="main")
    doc = SimpleNamespace(layers=[layer], filename="fixture.dia", modified=True)
    did = "live:s:doc"
    objects = {f"{did}:object:{i}": (Object(), layer, None) for i in range(20)}
    return registry, doc, did, objects


def run(scene, commands):
    registry, doc, did, objects = scene
    snapshot = (doc.filename, doc.modified, tuple(objects), tuple(registry.dia.types))
    before = copy.deepcopy(commands)
    result = validate_batch(*scene, commands)
    assert commands == before
    assert snapshot == (doc.filename, doc.modified, tuple(objects), tuple(registry.dia.types))
    assert registry.main_checked
    return result


def oid(scene, index=0):
    return f"{scene[2]}:object:{index}"


def test_move_is_static_and_native_callback_is_deferred(scene):
    result = run(scene, [{"op": "move", "object_id": oid(scene), "x": 2, "y": 3}])
    assert result["valid"] and not result["complete"]
    assert result["issue_count"] == 0 and result["deferred_count"] == 1
    assert result["native_authority"]


@pytest.mark.parametrize(
    "reference,code",
    [
        ("old-session-object", "WRONG_SESSION"),
        ("live:s:otherdoc:object:0", "STALE_OBJECT_REFERENCE"),
    ],
)
def test_references_include_bounded_exact_alternatives(scene, reference, code):
    result = run(scene, [{"op": "move", "object_id": reference, "x": 0, "y": 0}])
    issue = result["issues"][0]
    assert not result["valid"] and issue["code"] == code
    assert len(issue["alternatives"]) == 12
    assert issue["alternatives_total"] == 20 and issue["alternatives_truncated"]


def test_group_member_is_rejected(scene):
    obj, layer, _ = scene[3][oid(scene)]
    scene[3][oid(scene)] = (obj, layer, "group")
    result = run(scene, [{"op": "move", "object_id": oid(scene), "x": 0, "y": 0}])
    assert result["issues"][0]["code"] == "UNSUPPORTED_OPERATION"
    assert result["issues"][0]["alternatives_total"] == 19


def test_factory_is_only_catalog_checked(scene):
    result = run(
        scene,
        [
            {
                "op": "create",
                "type": "Installed - Type 000",
                "x": 1,
                "y": 2,
                "properties": {"unknown": "not probed"},
            }
        ],
    )
    assert result["valid"] and not result["complete"]
    result = run(
        scene,
        [
            {
                "op": "create",
                "type": "missing",
                "x": 1,
                "y": 2,
                "layer_id": "live:s:doc:layer:missing",
            }
        ],
    )
    assert result["issue_count"] == 2
    assert result["issues"][0]["alternatives_total"] == 30
    assert len(result["issues"][0]["alternatives"]) == 12
    assert result["issues"][1]["alternatives"] == ["live:s:doc:layer:main"]


@pytest.mark.parametrize(
    "name,value,code",
    [
        ("missing", "x", "UNKNOWN_PROPERTY"),
        ("file", "x", "UNSUPPORTED_PROPERTY"),
        ("readonly", "x", "UNSUPPORTED_PROPERTY"),
        ("hidden", "x", "UNSUPPORTED_PROPERTY"),
        ("boolean", 1, "INVALID_PROPERTY_VALUE"),
        ("integer", True, "INVALID_PROPERTY_VALUE"),
        ("integer", 2**40, "INVALID_PROPERTY_VALUE"),
        ("number", 1000001, "INVALID_PROPERTY_VALUE"),
        ("name", 1, "INVALID_PROPERTY_VALUE"),
    ],
)
def test_descriptor_only_property_checks(scene, name, value, code):
    obj = scene[3][oid(scene)][0]
    obj.descriptors = [
        descriptor("name"),
        descriptor("boolean", "bool"),
        descriptor("integer", "int"),
        descriptor("number", "real"),
        descriptor("file", "file"),
        descriptor("readonly", load_only=True),
        descriptor("hidden", visible=False),
    ]
    result = run(
        scene, [{"op": "set_properties", "object_id": oid(scene), "properties": {name: value}}]
    )
    assert not result["valid"] and result["issues"][0]["code"] == code
    assert obj.reads == 1
    assert result["issues"][0]["alternatives_total"] == 4


@pytest.mark.parametrize(
    "kind,value", [("int", 3), ("enum", 4), ("real", 1.5), ("length", 3), ("fontsize", 1.0)]
)
def test_native_property_ranges_are_deferred(scene, kind, value):
    obj = scene[3][oid(scene)][0]
    obj.descriptors = [descriptor("value", kind)]
    result = run(
        scene, [{"op": "set_properties", "object_id": oid(scene), "properties": {"value": value}}]
    )
    assert result["valid"] and not result["complete"]
    assert "range" in result["deferred"][0]["reason"]


def test_hidden_text_is_eligible_but_setter_is_deferred(scene):
    scene[3][oid(scene)][0].descriptors = [descriptor("text", "text", visible=False)]
    result = run(
        scene, [{"op": "set_properties", "object_id": oid(scene), "properties": {"text": "hello"}}]
    )
    assert result["valid"] and not result["complete"]


def test_descriptor_truncation_never_claims_missing_property(scene):
    scene[3][oid(scene)][0].truncated = True
    result = run(
        scene,
        [{"op": "set_properties", "object_id": oid(scene), "properties": {"beyond_limit": "x"}}],
    )
    assert result["valid"] and not result["complete"]
    assert result["issues"] == []


@pytest.mark.parametrize(
    "handle,point,code",
    [
        (1, 0, "INVALID_HANDLE"),
        (0, 1, "INVALID_CONNECTION_POINT"),
    ],
)
def test_port_indices_checked_against_actual_object(scene, handle, point, code):
    result = run(
        scene,
        [
            {
                "op": "connect",
                "object_id": oid(scene),
                "handle": handle,
                "target_id": oid(scene, 1),
                "point": point,
            }
        ],
    )
    assert not result["valid"] and result["issues"][0]["code"] == code
    assert result["issues"][0]["alternatives"] == [0]


def test_zero_port_nonconnectable_and_self_connections(scene):
    scene[3][oid(scene)][0].handles[0].connect_type = 0
    scene[3][oid(scene, 1)][0].connections = []
    result = run(
        scene,
        [
            {
                "op": "connect",
                "object_id": oid(scene),
                "handle": 0,
                "target_id": oid(scene, 1),
                "point": 0,
            }
        ],
    )
    assert {i["code"] for i in result["issues"]} == {
        "NONCONNECTABLE_HANDLE",
        "INVALID_CONNECTION_POINT",
    }
    result = run(
        scene,
        [
            {
                "op": "connect",
                "object_id": oid(scene),
                "handle": 0,
                "target_id": oid(scene),
                "point": 0,
            }
        ],
    )
    assert result["issues"][0]["code"] == "SELF_CONNECTION"


def test_delete_parent_and_attachments_rejected(scene):
    obj = scene[3][oid(scene)][0]
    obj.parent = object()
    obj.handles[0].connected_to = object()
    obj.connections[0].connected = [object()]
    result = run(scene, [{"op": "delete", "object_id": oid(scene)}])
    assert not result["valid"] and result["issue_count"] == 3


def test_intermediate_topology_is_deferred_not_simulated(scene):
    obj = scene[3][oid(scene)][0]
    attached = object()
    obj.handles[0].connected_to = attached
    result = run(
        scene,
        [
            {"op": "disconnect", "object_id": oid(scene), "handle": 0},
            {"op": "delete", "object_id": oid(scene)},
        ],
    )
    assert result["valid"] and not result["complete"]
    assert obj.handles[0].connected_to is attached
    assert result["deferred_count"] == 2


def test_deleted_reference_is_rejected_even_when_batch_state_deferred(scene):
    result = run(
        scene,
        [
            {"op": "delete", "object_id": oid(scene)},
            {"op": "move", "object_id": oid(scene), "x": 0, "y": 0},
        ],
    )
    assert not result["valid"]
    assert result["issues"][0]["code"] == "REFERENCE_AFTER_DELETE"


def test_layout_modes_and_duplicate_ids(scene):
    result = run(
        scene, [{"op": "layout", "object_ids": [oid(scene), oid(scene, 1)], "mode": "unknown"}]
    )
    assert result["issues"][0]["code"] == "INVALID_LAYOUT_MODE"
    assert result["issues"][0]["alternatives_total"] == 8
    result = run(scene, [{"op": "layout", "object_ids": [oid(scene), oid(scene)], "mode": "left"}])
    assert result["issues"][0]["code"] == "INVALID_ARGUMENT"


def test_issue_output_is_bounded_but_total_is_exact(scene):
    commands = [
        {
            "op": "layout",
            "object_ids": [f"live:s:missing:{i}", f"live:s:absent:{i}"],
            "mode": "unknown",
        }
        for i in range(64)
    ]
    result = run(scene, commands)
    assert not result["valid"] and not result["complete"]
    assert result["issue_count"] == 192 and len(result["issues"]) == 64
    assert result["issues_truncated"] and result["deferred_count"] == 64
    assert all(len(i["alternatives"]) <= 12 for i in result["issues"])


@pytest.mark.parametrize("commands", [[], [None], [{"op": "unknown"}], [1] * 65])
def test_malformed_batch_is_reported_without_native_actions(scene, commands):
    result = run(scene, commands)
    assert not result["valid"] and result["issues"][0]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("name,value", [("name\0alias", "x"), ("name", "\ud800")])
def test_invalid_c_strings_are_rejected(scene, name, value):
    result = run(
        scene, [{"op": "set_properties", "object_id": oid(scene), "properties": {name: value}}]
    )
    assert not result["valid"] and result["issues"][0]["code"] == "INVALID_ARGUMENT"


def test_unavailable_inspection_is_explicitly_incomplete(scene, monkeypatch):
    def unavailable(limit):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(scene[3][oid(scene)][0], "property_descriptors", unavailable)
    result = run(
        scene, [{"op": "set_properties", "object_id": oid(scene), "properties": {"name": "x"}}]
    )
    assert result["valid"] and not result["complete"]
    assert result["deferred"][0]["field"] == "inspection"


def test_truncated_descriptor_alternatives_have_explicit_scope(scene):
    obj = scene[3][oid(scene)][0]
    obj.descriptors = [descriptor("editable"), descriptor("file", "file")]
    obj.truncated = True
    result = run(
        scene, [{"op": "set_properties", "object_id": oid(scene), "properties": {"file": "x"}}]
    )
    issue = result["issues"][0]
    assert issue["alternatives"] == ["editable"]
    assert issue["alternatives_total"] == 1  # exact inspected eligible count
    assert issue["alternatives_truncated"]
    assert not issue["alternatives_source_complete"]


def test_oversized_native_port_list_is_deferred(scene):
    obj = scene[3][oid(scene)][0]
    obj.handles = [SimpleNamespace(connect_type=1, connected_to=None)] * 257
    result = run(scene, [{"op": "disconnect", "object_id": oid(scene), "handle": 0}])
    assert result["valid"] and not result["complete"]
    assert "budget" in result["deferred"][0]["reason"]
