"""Allowlisted native factories shared with the stdlib-only embedded worker."""

from typing import Literal

NodeType = Literal[
    "Flowchart - Box",
    "Flowchart - Ellipse",
    "Flowchart - Diamond",
    "UML - Class",
    "Electric - contact_o",
    "Electric - contact_f",
    "Electric - relay",
    "Electric - lamp",
    "Electric - connpoint",
    "Pneum - DEJack",
    "Pneum - dist52",
    "Pneum - presspn",
    "Pneum - drain",
]
ConnectionType = Literal[
    "Standard - Line", "Standard - ZigZagLine", "UML - Generalization", "UML - Association"
]
Port = Literal["auto", "north", "east", "south", "west", "center"]


def xml_text(value):
    if not isinstance(value, str) or any(
        ord(c) < 32
        and c not in "\t\n\r"
        or 0xD800 <= ord(c) <= 0xDFFF
        or ord(c) in (0xFFFE, 0xFFFF)
        for c in value
    ):
        raise ValueError("text must contain valid XML 1.0 characters")
    return value


def validate_uml(properties):
    """Mirror the typed public contract before entering native tuple setters."""
    if properties is None:
        return
    if not isinstance(properties, dict) or set(properties) - {
        "stereotype",
        "abstract",
        "attributes",
        "operations",
    }:
        raise ValueError("invalid UML properties")
    if len(xml_text(properties.get("stereotype", ""))) > 200:
        raise ValueError("invalid stereotype")
    if type(properties.get("abstract", False)) is not bool:
        raise ValueError("invalid abstract flag")
    for field in ("attributes", "operations"):
        members = properties.get(field, [])
        if not isinstance(members, list) or len(members) > 30:
            raise ValueError("invalid UML members")
        allowed = {"name", "type", "visibility", "class_scope"}
        if field == "attributes":
            allowed.add("value")
        else:
            allowed.update(("inheritance", "parameters"))
        for member in members:
            if not isinstance(member, dict) or set(member) - allowed or "name" not in member:
                raise ValueError("invalid UML member")
            for key in allowed - {"visibility", "class_scope", "inheritance", "parameters"}:
                if len(xml_text(member.get(key, ""))) > 200:
                    raise ValueError("invalid UML member text")
            if member.get("visibility", "public") not in (
                "public",
                "private",
                "protected",
                "package",
            ):
                raise ValueError("invalid visibility")
            if type(member.get("class_scope", False)) is not bool:
                raise ValueError("invalid class_scope")
            if field == "operations":
                if member.get("inheritance", "leaf") not in ("abstract", "polymorphic", "leaf"):
                    raise ValueError("invalid inheritance")
                parameters = member.get("parameters", [])
                if not isinstance(parameters, list) or len(parameters) > 20:
                    raise ValueError("invalid parameters")
                for param in parameters:
                    if (
                        not isinstance(param, dict)
                        or set(param) - {"name", "type", "value", "kind"}
                        or "name" not in param
                    ):
                        raise ValueError("invalid parameter")
                    for key in ("name", "type", "value"):
                        if len(xml_text(param.get(key, ""))) > 200:
                            raise ValueError("invalid parameter text")
                    if param.get("kind", "unspecified") not in (
                        "unspecified",
                        "in",
                        "out",
                        "inout",
                    ):
                        raise ValueError("invalid parameter kind")
