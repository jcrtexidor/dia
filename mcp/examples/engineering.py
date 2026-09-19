"""Native UML, electrical and pneumatic examples through the public operations API."""

import argparse
import json
from pathlib import Path

from dia_mcp.backend import NativeBackend
from dia_mcp.service import Operations


def uml(api):
    doc = api.create_document("UML: pedidos y pagos")["document"]["id"]

    def cls(name, x, y, attributes, operations=(), **extra):
        return api.create_object(
            doc,
            type="UML - Class",
            text=name,
            x=x,
            y=y,
            width=9,
            properties={
                "attributes": [{"name": n, "type": t} for n, t in attributes],
                "operations": list(operations),
                **extra,
            },
        )["object_id"]

    entity = cls("Entidad", 18, 1, [("id", "UUID")], abstract=True, stereotype="persistente")
    customer = cls("Cliente", 1, 11, [("nombre", "String"), ("email", "String")])
    order = cls(
        "Pedido",
        18,
        11,
        [("estado", "EstadoPedido"), ("fecha", "DateTime")],
        [{"name": "total", "type": "Money"}],
    )
    product = cls("Producto", 35, 11, [("sku", "String"), ("precio", "Money")])
    item = cls("LineaPedido", 26, 23, [("cantidad", "int"), ("precio", "Money")])
    payment = cls(
        "Pago",
        1,
        23,
        [("importe", "Money"), ("referencia", "String")],
        [
            {
                "name": "autorizar",
                "type": "bool",
                "parameters": [{"name": "token", "type": "String", "kind": "in"}],
            }
        ],
    )
    # Exercise editing existing structured properties before export.
    api.update_object(
        doc,
        order,
        properties={
            "attributes": [
                {"name": "estado", "type": "EstadoPedido"},
                {"name": "fecha", "type": "DateTime"},
            ],
            "operations": [
                {"name": "total", "type": "Money"},
                {"name": "confirmar", "type": "bool"},
            ],
        },
    )
    for child in (customer, order, product):
        api.connect_objects(
            doc,
            entity,
            child,
            type="UML - Generalization",
            source_port="south",
            target_port="north",
        )
    for source, target, source_port, target_port, label in [
        (customer, order, "east", "west", "realiza"),
        (order, item, "south", "north", "contiene"),
        (item, product, "east", "south", "referencia"),
        (order, payment, "south", "north", "se paga con"),
    ]:
        api.connect_objects(
            doc,
            source,
            target,
            type="UML - Association",
            source_port=source_port,
            target_port=target_port,
            label=label,
        )
    return doc


def electrical(api):
    doc = api.create_document("Mando eléctrico: marcha, paro y señalización")["document"]["id"]

    def symbol(type, text, x, y, size=2):
        return api.create_object(
            doc, type="Electric - " + type, text=text, x=x, y=y, width=size, height=size
        )["object_id"]

    supply = symbol("connpoint", "+24 V", 1, 3, 0.3)
    stop = symbol("contact_f", "S0 · Paro (NC)", 5, 2)
    start = symbol("contact_o", "S1 · Marcha (NO)", 11, 2)
    relay = symbol("relay", "K1 · Bobina", 19, 2)
    hold = symbol("contact_o", "K1 · Retención (NO)", 11, 9)
    lamp = symbol("lamp", "H1 · Marcha", 19, 15)
    ground = symbol("connpoint", "0 V", 26, 3, 0.3)
    for a, ai, b, bi in [
        (supply, 0, stop, 0),
        (stop, 1, start, 0),
        (start, 1, relay, 0),
        (stop, 1, hold, 0),
        (hold, 1, relay, 0),
        (relay, 1, ground, 0),
        (relay, 0, lamp, 0),
        (lamp, 1, ground, 0),
    ]:
        api.connect_objects(
            doc,
            a,
            b,
            type="Standard - ZigZagLine",
            arrow=False,
            source_connection=ai,
            target_connection=bi,
        )
    return doc


def pneumatic(api):
    doc = api.create_document("Neumática: cilindro de doble efecto y distribuidor 5/2")["document"][
        "id"
    ]

    def symbol(type, text, x, y, width, height, **options):
        return api.create_object(
            doc, type="Pneum - " + type, text=text, x=x, y=y, width=width, height=height, **options
        )["object_id"]

    cylinder = symbol("DEJack", "A1 · Doble efecto", 10, 1, 9, 3, flip_vertical=True)
    valve = symbol("dist52", "V1 · Distribuidor 5/2", 10, 11, 10, 5)
    pressure = symbol("presspn", "P · Aire comprimido", 1, 19, 3, 1.5)
    exhaust1 = symbol("drain", "R · Escape", 11, 25, 1.5, 1.5)
    exhaust2 = symbol("drain", "S · Escape", 23, 25, 1.5, 1.5)
    for a, ai, b, bi in [
        (valve, 0, cylinder, 0),
        (valve, 2, cylinder, 1),
        (pressure, 0, valve, 4),
        (valve, 1, exhaust1, 0),
        (valve, 3, exhaust2, 0),
    ]:
        api.connect_objects(
            doc,
            a,
            b,
            type="Standard - ZigZagLine",
            arrow=False,
            source_connection=ai,
            target_connection=bi,
        )
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--only", choices=("uml", "electrical", "pneumatic"))
    args = parser.parse_args()
    api = Operations(NativeBackend(), args.workspace)
    for key, filename, build in [
        ("uml", "04-uml-pedidos", uml),
        ("electrical", "05-mando-electrico", electrical),
        ("pneumatic", "06-circuito-neumatico", pneumatic),
    ]:
        if args.only and args.only != key:
            continue
        doc = build(api)
        state = api.inspect_document(doc)
        report = {
            "nodes": len(state["document"]["nodes"]),
            "connections": len(state["document"]["edges"]),
            "exports": [],
        }
        for format in ("dia", "svg", "png"):
            report["exports"].append(api.export_diagram(doc, f"{filename}.{format}", format))
        (args.workspace / f"{filename}.json").write_text(
            json.dumps({"state": state, "report": report}, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        api.close_document(doc)


if __name__ == "__main__":
    main()
