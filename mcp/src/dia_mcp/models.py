"""The GTK-independent, JSON-serializable v1 document contract."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .native.catalog import ConnectionType, NodeType, Port, xml_text

ExportFormat = Literal["dia", "svg", "png"]
Coordinate = Annotated[float, Field(ge=-1000, le=1000, allow_inf_nan=False)]
Dimension = Annotated[float, Field(ge=0.1, le=100, allow_inf_nan=False)]
Text = Annotated[str, Field(max_length=2000), AfterValidator(xml_text)]
ShortText = Annotated[str, Field(max_length=200), AfterValidator(xml_text)]
Visibility = Literal["public", "private", "protected", "package"]
ConnectionIndex = Annotated[int, Field(ge=0, le=1023, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class UMLAttribute(Contract):
    name: ShortText
    type: ShortText = ""
    value: ShortText = ""
    visibility: Visibility = "private"
    class_scope: bool = False


class UMLParameter(Contract):
    name: ShortText
    type: ShortText = ""
    value: ShortText = ""
    kind: Literal["unspecified", "in", "out", "inout"] = "unspecified"


class UMLOperation(Contract):
    name: ShortText
    type: ShortText = ""
    visibility: Visibility = "public"
    class_scope: bool = False
    inheritance: Literal["abstract", "polymorphic", "leaf"] = "leaf"
    parameters: list[UMLParameter] = Field(default_factory=list, max_length=20)


class UMLClassProperties(Contract):
    stereotype: ShortText = ""
    abstract: bool = False
    attributes: list[UMLAttribute] = Field(default_factory=list, max_length=30)
    operations: list[UMLOperation] = Field(default_factory=list, max_length=30)


class Node(Contract):
    id: str
    type: NodeType = "Flowchart - Box"
    x: Coordinate
    y: Coordinate
    width: Dimension = 4.0
    height: Dimension = 2.0
    text: Text = ""
    properties: UMLClassProperties | None = None
    flip_horizontal: bool = False
    flip_vertical: bool = False

    @model_validator(mode="after")
    def applicable_properties(self):
        if self.properties is not None and self.type != "UML - Class":
            raise ValueError("properties are only supported for UML - Class")
        if (self.flip_horizontal or self.flip_vertical) and not self.type.startswith(
            ("Electric - ", "Pneum - ")
        ):
            raise ValueError("flips require a technical symbol")
        return self


class Edge(Contract):
    id: str
    source: str
    target: str
    source_port: Port = "auto"
    target_port: Port = "auto"
    arrow: bool = True
    type: ConnectionType = "Standard - Line"
    source_connection: ConnectionIndex | None = None
    target_connection: ConnectionIndex | None = None
    label: ShortText = ""

    @model_validator(mode="after")
    def applicable_label(self):
        if self.label and not self.type.startswith("UML - "):
            raise ValueError("connection labels are supported only for UML connectors")
        return self


class Document(Contract):
    api_version: Literal["1"] = "1"
    id: str
    name: str = Field(min_length=1, max_length=200)
    revision: int = 0
    nodes: list[Node] = Field(default_factory=list, max_length=100)
    edges: list[Edge] = Field(default_factory=list, max_length=200)
