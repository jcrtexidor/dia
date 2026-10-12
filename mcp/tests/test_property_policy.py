"""Portable policy regressions: no Dia imports, object instances or value access."""

import re
from pathlib import Path

import pytest

from dia_mcp.property_policy import (
    CLASSIFICATIONS,
    DOMAIN_TYPES,
    RESOURCE_TYPES,
    SCALAR_TYPES,
    UNSUPPORTED_TYPES,
    classify_property,
)


def descriptor(kind, visible=True, load_only=False):
    return {"name": "fixture", "type": kind, "visible": visible, "load_only": load_only}


@pytest.mark.parametrize("kind", sorted(SCALAR_TYPES))
def test_exact_existing_scalar_surface(kind):
    policy = classify_property(descriptor(kind))
    assert policy["classification"] == "safe_read_write"
    assert policy["readable"] and policy["editable"]
    assert not policy["evidence"]["native_value_tested"]
    assert not policy["evidence"]["native_write_tested"]
    assert not policy["evidence"]["enum_values_exposed"]


@pytest.mark.parametrize("kind", sorted(SCALAR_TYPES - {"text"}))
def test_nonvisible_scalar_read_only(kind):
    policy = classify_property(descriptor(kind, visible=False))
    assert policy["classification"] == "safe_read_only"
    assert policy["readable"] and not policy["editable"]


def test_text_is_native_nonvisible_exception():
    assert classify_property(descriptor("text", visible=False))["editable"]


@pytest.mark.parametrize("kind", sorted(SCALAR_TYPES | DOMAIN_TYPES | RESOURCE_TYPES))
def test_load_or_widget_only_never_fetches_values(kind):
    policy = classify_property(descriptor(kind, load_only=True))
    assert policy["classification"] == "unsupported"
    assert not policy["readable"] and not policy["editable"]


@pytest.mark.parametrize("kind", sorted(DOMAIN_TYPES))
def test_compound_and_geometry_require_bounded_codecs(kind):
    policy = classify_property(descriptor(kind))
    assert policy["classification"] == "requires_domain_codec"
    assert not policy["readable"] and not policy["editable"]


@pytest.mark.parametrize("kind", sorted(RESOURCE_TYPES))
def test_resources_are_not_scalar_strings_or_arrays(kind):
    policy = classify_property(descriptor(kind))
    assert policy["classification"] == "requires_resource_policy"
    assert not policy["readable"] and not policy["editable"]


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"type": "string"},
        {"type": "string", "visible": True},
        {"type": "string", "visible": 1, "load_only": False},
        {"type": "string", "visible": True, "load_only": "false"},
        {"type": [], "visible": True, "load_only": False},
        descriptor("future_plugin_pointer"),
    ],
)
def test_unknown_missing_or_invalid_descriptors_fail_closed(item):
    policy = classify_property(item)
    assert policy["classification"] == "unknown"
    assert not policy["readable"] and not policy["editable"]


def test_every_native_defined_kind_has_an_explicit_policy():
    root = Path(__file__).resolve().parents[2]
    header = (root / "lib/properties.h").read_text()
    kinds = set(re.findall(r'^#define PROP_TYPE_\w+ "([^"]+)"', header, re.M))
    known = SCALAR_TYPES | DOMAIN_TYPES | RESOURCE_TYPES | UNSUPPORTED_TYPES
    assert kinds <= known
    for kind in kinds:
        assert classify_property(descriptor(kind))["classification"] in CLASSIFICATIONS


def test_descriptor_and_input_are_not_mutated():
    item = descriptor("enum")
    original = item.copy()
    classify_property(item)
    assert item == original
