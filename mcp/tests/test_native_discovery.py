"""Catalog integration with loaded plugins, multiple domains and an unknown custom shape."""

import os
from pathlib import Path

import pytest

from dia_mcp.backend import NativeBackend
from dia_mcp.service import Operations

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(os.environ.get("DIA_MCP_NATIVE") != "1", reason="requires native Dia"),
]


def test_native_catalog_and_custom_sheet(tmp_path, monkeypatch):
    backend = NativeBackend(os.environ.get("DIA_BINARY", "dia"))
    api = Operations(backend, tmp_path / "workspace")
    doc = api.create_document()["document"]["id"]
    before = api.inspect_document(doc)
    sheets = api.list_sheets()
    assert {"UML", "Flowchart", "Database", "ER", "Network", "Electric"} <= {
        sheet["name"] for sheet in sheets["items"]
    }
    for sheet in ("UML", "Flowchart", "Database", "ER", "Network", "Electric"):
        assert api.list_object_types(sheet=sheet)["total"] > 0
    all_types = []
    offset = 0
    while offset is not None:
        page = api.list_object_types(offset=offset)
        all_types.extend(page["items"])
        offset = page["next_offset"]
    assert len(all_types) == page["total"]
    assert len({kind["name"] for kind in all_types}) == page["total"]
    assert any(kind["name"] == "Standard - Box" and not kind["sheet_entries"] for kind in all_types)

    shapes, sheets_dir = tmp_path / "shapes", tmp_path / "sheets"
    shapes.mkdir()
    sheets_dir.mkdir()
    (shapes / "probe.shape").write_text("""<?xml version="1.0"?>
<shape xmlns="http://www.daa.com.au/~james/dia-shape-ns"
       xmlns:svg="http://www.w3.org/2000/svg">
  <name>Audit - Unknown Symbol</name><icon>probe.png</icon>
  <connections><point x="0" y="0"/></connections>
  <aspectratio type="free"/>
  <svg:svg><svg:rect x="0" y="0" width="2" height="1"/></svg:svg>
</shape>""")
    (sheets_dir / "probe.sheet").write_text("""<?xml version="1.0"?>
<sheet xmlns="http://www.lysator.liu.se/~alla/dia/dia-sheet-ns">
  <name>Audit custom sheet</name><description>Unknown technical symbols</description>
  <contents><object name="Audit - Unknown Symbol">
    <description>Custom fixture</description></object></contents>
</sheet>""")
    installed_data = Path(backend.executable).resolve().parent.parent / "share" / "dia"
    monkeypatch.setenv("DIA_SHAPE_PATH", f"{installed_data / 'shapes'}:{shapes}")
    monkeypatch.setenv("DIA_SHEET_PATH", f"{installed_data / 'sheets'}:{sheets_dir}")
    custom = api.list_object_types(sheet="Audit custom sheet")
    assert custom["total"] == 1
    assert custom["items"][0]["name"] == "Audit - Unknown Symbol"
    assert custom["items"][0]["creatable_as"] is None
    assert custom["items"][0]["sheet_entries"] == [
        {"sheet": "Audit custom sheet", "description": "Custom fixture"}
    ]
    # Fresh discovery observes changes, without stale metadata cached by the MCP server.
    (sheets_dir / "probe.sheet").unlink()
    assert "Audit custom sheet" not in {s["name"] for s in api.list_sheets()["items"]}
    assert api.inspect_document(doc) == before
    assert list(api.workspace.iterdir()) == []
