"""UML native tuple and endpoint policy; no Dia import required."""


def validate_uml(properties, xml_text):
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


def configure_class(obj, node):
    settings = node.get("properties") or {}
    visibility = {"public": 0, "private": 1, "protected": 2, "package": 3}
    obj.properties["name"] = node["text"]
    obj.properties["stereotype"] = settings.get("stereotype", "")
    obj.properties["abstract"] = settings.get("abstract", False)
    obj.properties["attributes"] = [
        (
            a["name"],
            a.get("type", ""),
            a.get("value", ""),
            "",
            visibility[a.get("visibility", "private")],
            False,
            a.get("class_scope", False),
        )
        for a in settings.get("attributes", [])
    ]
    obj.properties["operations"] = [
        (
            o["name"],
            o.get("type", ""),
            "",
            "",
            visibility[o.get("visibility", "public")],
            {"abstract": 0, "polymorphic": 1, "leaf": 2}[o.get("inheritance", "leaf")],
            False,
            o.get("class_scope", False),
            [
                (
                    p["name"],
                    p.get("type", ""),
                    p.get("value", ""),
                    "",
                    {"unspecified": 0, "in": 1, "out": 2, "inout": 3}[p.get("kind", "unspecified")],
                )
                for p in o.get("parameters", [])
            ],
        )
        for o in settings.get("operations", [])
    ]
    obj.properties["allow_resizing"] = True
    obj.properties["elem_width"] = node["width"]


def superclass_endpoints(handles):
    """Dia generalization draws its triangle at STARTPOINT (handle id 8)."""
    ends = {}
    for handle in handles:
        if handle.get("id") in (8, 9) and handle.get("attached_to"):
            key = handle["id"]
            if key in ends:
                return None
            ends[key] = handle["attached_to"].get("object_id")
    if ends.get(8) and ends.get(9):
        return {"superclass": ends[8], "subclass": ends[9]}
    return None
