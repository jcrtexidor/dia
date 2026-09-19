"""Run inside the documented Ubuntu container or a configured native installation."""

import argparse
import json
from pathlib import Path

from dia_mcp.backend import NativeBackend
from dia_mcp.service import Operations

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, default=Path("exports"))
args = parser.parse_args()
api = Operations(NativeBackend(), args.workspace)
doc = api.create_document("Flujo de contribución")["document"]["id"]
nodes = []
for x, text, type in [
    (1, "Crear", "Flowchart - Ellipse"),
    (8, "Conectar", "Flowchart - Box"),
    (15, "Exportar", "Flowchart - Ellipse"),
]:
    nodes.append(
        api.create_object(doc, type=type, x=x, y=2, width=4, height=2, text=text)["object_id"]
    )
for source, target in zip(nodes, nodes[1:]):
    api.connect_objects(doc, source, target)
for format in ("dia", "svg", "png"):
    print(json.dumps(api.export_diagram(doc, f"workflow.{format}", format), ensure_ascii=False))
