"""Bounded JSON metadata at the native integration boundary; no native pointers."""

from typing import Annotated, Literal

from pydantic import Field

from .models import Contract

Metadata = Annotated[str, Field(max_length=4096)]
Offset = Annotated[int, Field(ge=0, strict=True)]
PageSize = Annotated[int, Field(ge=1, le=100, strict=True)]


class SheetEntry(Contract):
    type: Metadata | None
    description: Metadata


class Sheet(Contract):
    name: Metadata
    description: Metadata
    user: bool
    objects: list[SheetEntry] = Field(max_length=10000)


class ObjectType(Contract):
    name: Metadata
    version: int


class Catalog(Contract):
    api_version: Literal["1"]
    sheets: list[Sheet] = Field(max_length=1000)
    object_types: list[ObjectType] = Field(max_length=10000)
