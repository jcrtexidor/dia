"""Fail-closed descriptor policy for the existing scalar live property surface.

This module performs no native calls. 'Safe' means a reviewed serialization/type
path exists, not that an arbitrary plugin cannot fail. Native descriptor ranges,
flags, enum membership and transaction validation remain authoritative.
"""

SCALAR_TYPES = frozenset({"bool", "int", "enum", "real", "length", "fontsize", "string", "text"})
CLASSIFICATIONS = frozenset(
    {
        "safe_read_write",
        "safe_read_only",
        "unsupported",
        "requires_domain_codec",
        "requires_resource_policy",
        "unknown",
    }
)
DOMAIN_TYPES = frozenset(
    {
        "intarray",
        "enumarray",
        "stringlist",
        "point",
        "pointarray",
        "bezpoint",
        "bezpointarray",
        "rect",
        "endpoints",
        "connpoint_line",
        "linestyle",
        "arrow",
        "colour",
        "sarray",
        "darray",
        "dict",
        "matrix",
    }
)
RESOURCE_TYPES = frozenset({"font", "file", "pixbuf", "pattern", "object", "objectref", "image"})
UNSUPPORTED_TYPES = frozenset(
    {
        "invalid",
        "noop",
        "unimplemented",
        "char",
        "multistring",
        "static",
        "button",
        "nb_begin",
        "nb_end",
        "nb_page",
        "mc_begin",
        "mc_end",
        "mc_col",
        "f_begin",
        "f_end",
        "list",
    }
)


_SOURCE_GROUPS = {
    "lib/prop_inttypes.c": {"char", "bool", "int", "intarray", "enum", "enumarray"},
    "lib/prop_text.c": {"string", "stringlist", "multistring", "file", "text"},
    "lib/prop_geomtypes.c": {
        "real",
        "length",
        "fontsize",
        "point",
        "pointarray",
        "bezpoint",
        "bezpointarray",
        "rect",
        "endpoints",
        "connpoint_line",
    },
    "lib/prop_attr.c": {"linestyle", "arrow", "colour", "font"},
    "lib/prop_sdarray.c": {"sarray", "darray"},
    "lib/prop_dict.c": {"dict"},
    "lib/prop_matrix.c": {"matrix"},
    "lib/prop_pixbuf.c": {"pixbuf"},
    "lib/prop_pattern.c": {"pattern"},
    "lib/prop_basic.c": {"invalid", "noop", "unimplemented"},
    "lib/prop_widgets.c": {
        "static",
        "button",
        "nb_begin",
        "nb_end",
        "nb_page",
        "mc_begin",
        "mc_end",
        "mc_col",
        "f_begin",
        "f_end",
        "list",
    },
}
_NATIVE_SOURCE = {kind: path for path, kinds in _SOURCE_GROUPS.items() for kind in kinds}


def classify_property(descriptor):
    """Classify a native descriptor without fetching its value.

    Missing/invalid flags never grant read or write access. ``editable`` is a
    descriptor-level candidate, not a guarantee: enum/range checks run natively.
    ``load_only`` currently combines native LOAD_ONLY and WIDGET_ONLY flags.
    """
    kind = descriptor.get("type")
    visible = descriptor.get("visible")
    load_only = descriptor.get("load_only")
    flags_valid = type(visible) is bool and type(load_only) is bool
    known_type = isinstance(kind, str)
    readable = known_type and kind in SCALAR_TYPES and flags_valid and not load_only
    editable = readable and (visible or kind == "text")
    if not known_type or not flags_valid:
        category, reason = "unknown", "Missing or invalid descriptor type/flags; access denied."
    elif load_only:
        category, reason = (
            "unsupported",
            "Native load-only or widget-only descriptor; access denied.",
        )
    elif kind in SCALAR_TYPES:
        category = "safe_read_write" if editable else "safe_read_only"
        reason = "Reviewed scalar codec; native enum/range and transaction validation still apply."
    elif kind in DOMAIN_TYPES:
        category = "requires_domain_codec"
        reason = (
            "Requires bounded structured codec and object-specific invariants; values not fetched."
        )
    elif kind in RESOURCE_TYPES:
        category = "requires_resource_policy"
        reason = "Requires resource ownership/path/reference policy; values not fetched."
    elif kind in UNSUPPORTED_TYPES:
        category, reason = "unsupported", "No enabled live codec for this native kind."
    else:
        category, reason = "unknown", "Unrecognized native kind; values not fetched."
    return {
        "classification": category,
        "readable": readable,
        "editable": editable,
        "reason": reason,
        "evidence": {
            "basis": "native_descriptor_and_reviewed_source",
            "native_implementation": _NATIVE_SOURCE.get(kind) if known_type else None,
            "live_gate": "plug-ins/python/pydia-live.c:set_properties",
            "legacy_conversion": "plug-ins/python/pydia-property.c:prop_type_map",
            "descriptor_flags_complete": flags_valid,
            "native_value_tested": False,
            "native_write_tested": False,
            "enum_values_exposed": False,
            "numeric_range_exposed": False,
        },
    }
