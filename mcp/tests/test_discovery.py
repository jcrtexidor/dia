"""Runtime metadata is independent of the MCP creation allowlist and document state."""

from types import SimpleNamespace

import pytest

import dia_mcp.backend as backend_module
from dia_mcp.backend import NativeBackend
from dia_mcp.discovery import Catalog
from dia_mcp.errors import DiaError
from dia_mcp.native.discovery import discover
from dia_mcp.service import Operations


def native_catalog():
    kinds = {
        name: SimpleNamespace(name=name, version=0)
        for name in ("Unfamiliar - Custom", "Flowchart - Box", "Standard - Line", "Orphan")
    }
    return SimpleNamespace(
        registered_types=lambda: kinds,
        registered_sheets=lambda: [
            SimpleNamespace(
                name="Custom sheet",
                description="User symbols",
                user=1,
                objects=[
                    (kinds["Unfamiliar - Custom"], "A custom symbol", None),
                    (kinds["Unfamiliar - Custom"], "Another palette entry", None),
                    (None, "Unavailable entry", None),
                ],
            ),
            SimpleNamespace(
                name="Flowchart",
                description="Flowcharts",
                user=0,
                objects=[(kinds["Flowchart - Box"], "Process", None)],
            ),
        ],
    )


def test_discovery_paginates_runtime_types_without_creating_or_editing(tmp_path):
    catalog = Catalog.model_validate(discover(native_catalog()))
    api = Operations(SimpleNamespace(discover=lambda: catalog), tmp_path)
    doc = api.create_document()["document"]["id"]
    before = api.inspect_document(doc)
    sheets = api.list_sheets(limit=1)
    assert sheets["total"] == 2 and sheets["next_offset"] == 1
    assert sheets["items"][0] == {
        "name": "Custom sheet",
        "description": "User symbols",
        "user": True,
        "object_count": 3,
    }
    assert api.list_sheets(offset=1)["next_offset"] is None
    pages = [api.list_object_types(offset=i, limit=1) for i in range(4)]
    assert [page["next_offset"] for page in pages] == [1, 2, 3, None]
    types = {page["items"][0]["name"]: page["items"][0] for page in pages}
    assert types["Flowchart - Box"]["creatable_as"] == "object"
    assert types["Standard - Line"]["creatable_as"] == "connection"
    assert types["Unfamiliar - Custom"]["creatable_as"] is None
    assert types["Orphan"]["sheet_entries"] == []
    selected = api.list_object_types(sheet="Custom sheet")
    assert selected["total"] == 1
    assert len(selected["items"][0]["sheet_entries"]) == 2
    assert api.list_object_types(offset=100)["items"] == []
    assert api.inspect_document(doc) == before
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("offset,limit", [(-1, 10), (False, 10), (0, 0), (0, 101), (0, 1.5)])
def test_invalid_pages_do_not_launch_dia(tmp_path, offset, limit):
    api = Operations(object(), tmp_path)
    for method in (api.list_sheets, api.list_object_types):
        with pytest.raises(DiaError) as error:
            method(offset=offset, limit=limit)
        assert error.value.code == "INVALID_ARGUMENT"


def test_unknown_sheet_and_backend_without_discovery(tmp_path):
    api = Operations(object(), tmp_path)
    with pytest.raises(DiaError) as error:
        api.list_sheets()
    assert error.value.code == "UNSUPPORTED_CAPABILITY"
    api.backend = SimpleNamespace(
        discover=lambda: Catalog.model_validate(discover(native_catalog()))
    )
    with pytest.raises(DiaError) as error:
        api.list_object_types(sheet="Missing")
    assert error.value.code == "NOT_FOUND"


@pytest.mark.parametrize("catalog", [None, [], {"api_version": "2"}, {"api_version": "1"}])
def test_malformed_native_catalog_is_a_structured_error(monkeypatch, catalog):
    backend = NativeBackend.__new__(NativeBackend)
    monkeypatch.setattr(backend, "_run", lambda *args: {"ok": True, "catalog": catalog})
    with pytest.raises(DiaError) as error:
        backend.discover()
    assert error.value.code == "BACKEND_FAILED"


@pytest.mark.parametrize(
    "payload", [b"[]", b"null", b'{"ok":1}', b"invalid", b" " * (8 * 1024 * 1024 + 1)]
)
def test_invalid_worker_envelope_does_not_escape_as_python_error(tmp_path, monkeypatch, payload):
    response = tmp_path / "response.json"
    response.write_bytes(payload)
    backend = NativeBackend.__new__(NativeBackend)
    backend.executable, backend.timeout = "/unused/dia", 30
    monkeypatch.setattr(
        backend_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=b""),
    )
    with pytest.raises(DiaError) as error:
        backend._run(tmp_path / "request.diacatalog", tmp_path / "empty.dia", response, "dia")
    assert error.value.code == "BACKEND_FAILED"
