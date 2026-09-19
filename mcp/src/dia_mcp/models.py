"""The GTK-independent, JSON-serializable v1 document contract."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NodeType = Literal["Flowchart - Box", "Flowchart - Ellipse", "Flowchart - Diamond"]
Port = Literal["auto", "north", "east", "south", "west", "center"]
ExportFormat = Literal["dia", "svg", "png"]
Coordinate = Annotated[float, Field(ge=-1000, le=1000, allow_inf_nan=False)]
Dimension = Annotated[float, Field(ge=0.1, le=100, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class Node(Contract):
    id: str
    type: NodeType = "Flowchart - Box"
    x: Coordinate
    y: Coordinate
    width: Dimension = 4.0
    height: Dimension = 2.0
    text: str = Field(default="", max_length=2000)

    @field_validator("text")
    @classmethod
    def xml_text(cls, value: str) -> str:
        if any(
            ord(c) < 32
            and c not in "\t\n\r"
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) in (0xFFFE, 0xFFFF)
            for c in value
        ):
            raise ValueError("text must contain valid XML 1.0 characters")
        return value


class Edge(Contract):
    id: str
    source: str
    target: str
    source_port: Port = "auto"
    target_port: Port = "auto"
    arrow: bool = True


class Document(Contract):
    api_version: Literal["1"] = "1"
    id: str
    name: str = Field(min_length=1, max_length=200)
    revision: int = 0
    nodes: list[Node] = Field(default_factory=list, max_length=100)
    edges: list[Edge] = Field(default_factory=list, max_length=200)
