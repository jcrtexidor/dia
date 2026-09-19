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
    """Compatibility entrypoint for the snapshot validation contract."""
    if __package__:
        from .uml import validate_uml as validate
    else:
        from uml import validate_uml as validate
    return validate(properties, xml_text)
