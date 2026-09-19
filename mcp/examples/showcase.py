"""Generate three editable examples through the same public API exposed by MCP."""

import argparse
import json
import time
from pathlib import Path

from dia_mcp.backend import NativeBackend
from dia_mcp.service import Operations

BOX = "Flowchart - Box"
ELLIPSE = "Flowchart - Ellipse"
DIAMOND = "Flowchart - Diamond"


def architecture():
    nodes = [
        ("web", "Web", 0, 8, ELLIPSE),
        ("mobile", "App móvil", 0, 23, ELLIPSE),
        ("partners", "Partners", 0, 38, ELLIPSE),
        ("gateway", "API Gateway\nLímite de tráfico", 11, 23, BOX),
        ("identity", "Identidad\nOAuth / roles", 11, 8, BOX),
    ]
    services = [
        ("catalog", "Catálogo", "cache", "Caché\nproductos"),
        ("search", "Búsqueda", "index", "Índice\nde búsqueda"),
        ("orders", "Pedidos", "orders_db", "Pedidos DB\nOutbox"),
        ("payments", "Pagos", "provider", "Pasarela\nexterna"),
        ("accounts", "Cuentas", "accounts_db", "Clientes DB"),
        ("inventory", "Inventario", "stock_db", "Stock DB\nOutbox"),
    ]
    edges = [(client, "gateway") for client in ("web", "mobile", "partners")]
    edges.append(("gateway", "identity"))
    for row, (key, label, store, store_label) in enumerate(services):
        nodes.extend([(key, label, 23, row * 10, BOX), (store, store_label, 35, row * 10, BOX)])
        edges.extend([("gateway", key), (key, store)])
    nodes.append(("events", "Bus de eventos\nEntrega durable", 47, 23, BOX))
    for source in ("orders_db", "provider", "stock_db"):
        edges.append((source, "events"))
    consumers = [
        ("mail", "Notificaciones", "email", "Email / SMS"),
        ("shipping", "Logística", "carrier", "Transportista"),
        ("analytics", "Analítica", "warehouse", "Data warehouse"),
        ("audit", "Auditoría", "archive", "Archivo\nhistórico"),
    ]
    for row, (key, label, sink, sink_label) in enumerate(consumers):
        nodes.extend([(key, label, 59, row * 15, BOX), (sink, sink_label, 71, row * 15, BOX)])
        edges.extend([("events", key), (key, sink)])
    edges.extend([("events", "cache"), ("events", "index")])
    return "01-servicios", "Arquitectura de comercio y eventos", nodes, edges


def order_process():
    nodes = [
        ("start", "Inicio", 15, 0, ELLIPSE),
        ("form", "Capturar\npedido", 15, 6, BOX),
        ("valid", "¿Datos\nválidos?", 15, 12, DIAMOND),
        ("fix", "No: corregir\ndatos", 0, 12, BOX),
        ("stock", "Sí: ¿hay\nstock?", 15, 20, DIAMOND),
        ("reserve", "No: pedido\npendiente", 30, 20, BOX),
        ("wait", "Esperar\nreposición", 30, 27, BOX),
        ("charge", "Sí: preparar\ncobro", 15, 28, BOX),
        ("risk", "¿Riesgo\naceptable?", 15, 35, DIAMOND),
        ("manual", "No: revisión\nmanual", 0, 35, BOX),
        ("approve", "¿Revisión\naprobada?", 0, 43, DIAMOND),
        ("reject", "No: rechazar\npedido", 0, 51, ELLIPSE),
        ("authorize", "Autorizar\npago", 15, 44, BOX),
        ("paid", "¿Pago\nconfirmado?", 15, 51, DIAMOND),
        ("retry", "No: registrar\nfallo", 30, 51, BOX),
        ("attempts", "¿Quedan\nintentos?", 30, 59, DIAMOND),
        ("cancel", "No: cancelar", 45, 59, ELLIPSE),
        ("prepare", "Sí: preparar\npaquete", 15, 60, BOX),
        ("quality", "¿Control\ncorrecto?", 15, 68, DIAMOND),
        ("repack", "No: rehacer\npaquete", 30, 68, BOX),
        ("label", "Sí: emitir\netiqueta", 15, 76, BOX),
        ("dispatch", "Despachar\npedido", 15, 83, BOX),
        ("delivered", "¿Entrega\nconfirmada?", 15, 90, DIAMOND),
        ("incident", "No: gestionar\nincidencia", 0, 90, BOX),
        ("reschedule", "Reprogramar\nentrega", 0, 98, BOX),
        ("finish", "Pedido\ncompletado", 15, 99, ELLIPSE),
    ]
    edges = [
        ("start", "form"),
        ("form", "valid"),
        ("valid", "fix"),
        ("fix", "form"),
        ("valid", "stock"),
        ("stock", "reserve"),
        ("reserve", "wait"),
        ("wait", "stock"),
        ("stock", "charge"),
        ("charge", "risk"),
        ("risk", "manual"),
        ("manual", "approve"),
        ("approve", "reject"),
        ("approve", "authorize"),
        ("risk", "authorize"),
        ("authorize", "paid"),
        ("paid", "retry"),
        ("retry", "attempts"),
        ("attempts", "authorize"),
        ("attempts", "cancel"),
        ("paid", "prepare"),
        ("prepare", "quality"),
        ("quality", "repack"),
        ("repack", "prepare"),
        ("quality", "label"),
        ("label", "dispatch"),
        ("dispatch", "delivered"),
        ("delivered", "incident"),
        ("incident", "reschedule"),
        ("reschedule", "dispatch"),
        ("delivered", "finish"),
    ]
    return "02-pedidos", "Pedidos: decisiones, excepciones y reintentos", nodes, edges


def mesh():
    nodes, edges = [], []
    for row in range(10):
        for col in range(10):
            key = f"r{row}c{col}"
            type = ELLIPSE if col == 0 else (DIAMOND if col == 9 else BOX)
            nodes.append((key, f"Zona {row + 1:02d}\nNodo {col + 1:02d}", col * 11, row * 7, type))
            if col:
                edges.append((f"r{row}c{col - 1}", key))
            if row:
                edges.append((f"r{row - 1}c{col}", key))
    # 90 horizontal + 90 vertical + 20 diagonal connections = the advertised limit.
    for row in (1, 3, 5, 7, 8):
        for col in (1, 3, 5, 7):
            edges.append((f"r{row}c{col}", f"r{row + 1}c{col + 1}"))
    return "03-malla-100", "Malla: 100 nodos y 200 conexiones", nodes, edges


def build(api, definition):
    slug, name, nodes, edges = definition
    started = time.monotonic()
    doc_id = api.create_document(name)["document"]["id"]
    ids = {}
    print(f"Creating {slug}: {len(nodes)} nodes, {len(edges)} connections", flush=True)
    for key, text, x, y, type in nodes:
        ids[key] = api.create_object(doc_id, type=type, text=text, x=x, y=y, width=6.4, height=2.8)[
            "object_id"
        ]
    for index, (source, target) in enumerate(edges, 1):
        api.connect_objects(doc_id, ids[source], ids[target])
        if index % 50 == 0:
            print(f"  {slug}: {index}/{len(edges)} connections", flush=True)
    state = api.inspect_document(doc_id)
    bounds = list(state["geometry"]["nodes"].items())
    for index, (first_id, first) in enumerate(bounds):
        a = first["bounds"]
        for second_id, second in bounds[index + 1 :]:
            b = second["bounds"]
            if min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]):
                raise ValueError(f"Overlapping shapes: {first_id}, {second_id}")
    outputs = [
        api.export_diagram(doc_id, f"{slug}.{format}", format) for format in ("dia", "svg", "png")
    ]
    (api.workspace / f"{slug}.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    api.close_document(doc_id)
    return {
        "name": name,
        "slug": slug,
        "nodes": len(nodes),
        "connections": len(edges),
        "native_objects": len(nodes) + len(edges),
        "seconds": round(time.monotonic() - started, 2),
        "outputs": outputs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--only", choices=("services", "orders", "mesh"))
    args = parser.parse_args()
    api = Operations(NativeBackend(), args.workspace)
    definitions = {"services": architecture, "orders": order_process, "mesh": mesh}
    selected = [args.only] if args.only else list(definitions)
    report = [build(api, definitions[key]()) for key in selected]
    manifest = "manifest.json" if args.only is None else f"manifest-{args.only}.json"
    (api.workspace / manifest).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
