"""Public operations guarantees, independent of Dia/GTK and the MCP transport."""

import copy
import hashlib
from pathlib import Path

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.service import Operations


class FakeBackend:
    """A materializer that can fail after writing output or race publication."""

    payload = b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>'

    def __init__(self):
        self.calls = []
        self.fail = False
        self.after_render = None

    def render(self, document, destination: Path, format):
        self.calls.append((document.model_dump(), destination, format))
        destination.write_bytes(self.payload)
        if self.fail:
            raise DiaError("BACKEND_FAILED", "Simulated native failure after partial output")
        if self.after_render is not None:
            self.after_render()
        # A generation marker detects accidental publication of failed geometry.
        return {
            "nodes": {node.id: {"bounds": [len(self.calls), 0, 5, 5]} for node in document.nodes},
            "edges": {edge.id: {"start": [1, 2], "end": [3, 4]} for edge in document.edges},
        }


@pytest.fixture
def setup_service(tmp_path):
    backend = FakeBackend()
    operations = Operations(backend, tmp_path / "workspace")
    document_id = operations.create_document("Test")["document"]["id"]
    return operations, backend, document_id


def add_pair(operations, document_id):
    first = operations.create_object(document_id, text="Source")["object_id"]
    second = operations.create_object(document_id, x=10, text="Target")["object_id"]
    return first, second


def assert_error(code, action):
    with pytest.raises(DiaError) as caught:
        action()
    assert caught.value.code == code


def test_filesystem_failure_preserves_state_and_uses_error_contract(setup_service):
    operations, backend, document_id = setup_service
    before = operations.inspect_document(document_id)

    def disk_full():
        raise OSError("No space left on device")

    backend.after_render = disk_full
    assert_error("IO_ERROR", lambda: operations.create_object(document_id))
    assert operations.inspect_document(document_id) == before


def test_export_staging_failure_uses_error_contract(setup_service, monkeypatch):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    before = operations.inspect_document(document_id)
    calls = len(backend.calls)

    def cannot_create(**kwargs):
        raise PermissionError("Cannot create a temporary file")

    monkeypatch.setattr("dia_mcp.service.tempfile.mkstemp", cannot_create)
    assert_error("IO_ERROR", lambda: operations.export_diagram(document_id, "out.svg"))
    assert operations.inspect_document(document_id) == before
    assert len(backend.calls) == calls


@pytest.mark.parametrize("backend_failure", [False, True])
def test_cleanup_failure_does_not_hide_operation_result(
    setup_service, monkeypatch, caplog, backend_failure
):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    backend.fail = backend_failure
    original_unlink = Path.unlink

    def cannot_remove_staging(path, *args, **kwargs):
        if path.name.startswith(".dia-mcp-"):
            raise PermissionError("Simulated cleanup failure")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", cannot_remove_staging)
        if backend_failure:
            assert_error(
                "BACKEND_FAILED", lambda: operations.export_diagram(document_id, "out.svg")
            )
            assert not (operations.workspace / "out.svg").exists()
        else:
            result = operations.export_diagram(document_id, "out.svg")
            assert Path(result["path"]).read_bytes() == backend.payload
    assert "Could not remove temporary export" in caplog.text
    for staging in operations.workspace.glob(".dia-mcp-*"):
        staging.unlink()


@pytest.mark.parametrize("operation", ["create", "connect", "move"])
def test_backend_failure_preserves_revision_objects_and_geometry(setup_service, operation):
    operations, backend, document_id = setup_service
    first, second = add_pair(operations, document_id)
    operations.connect_objects(document_id, first, second)
    before = operations.inspect_document(document_id)
    backend.fail = True
    actions = {
        "create": lambda: operations.create_object(document_id, text="Not committed"),
        "connect": lambda: operations.connect_objects(document_id, second, first),
        "move": lambda: operations.move_object(document_id, first, 22, 33),
    }

    assert_error("BACKEND_FAILED", actions[operation])

    assert operations.inspect_document(document_id) == before
    assert not backend.calls[-1][1].exists(), "Failed native staging must be removed"
    backend.fail = False
    retried = operations.move_object(document_id, first, 22, 33)
    assert retried["document"]["revision"] == before["document"]["revision"] + 1
    assert retried["document"]["nodes"][0]["id"] == first
    assert (retried["document"]["nodes"][0]["x"], retried["document"]["nodes"][0]["y"]) == (22, 33)


def test_results_are_detached_from_documents_and_geometry(setup_service):
    operations, _, document_id = setup_service
    created = operations.create_object(document_id, text="Keep this text")
    expected = operations.inspect_document(document_id)

    created["document"]["nodes"][0]["text"] = "Client mutation"
    created["document"]["nodes"].clear()
    created["geometry"]["nodes"][created["object_id"]]["bounds"][0] = 999
    inspected = operations.inspect_document(document_id)
    inspected["document"]["name"] = "Client rename"
    inspected["geometry"]["nodes"].clear()

    assert operations.inspect_document(document_id) == expected


def test_ids_are_scoped_to_their_document_and_closed_ids_do_not_revive(setup_service):
    operations, backend, document_id = setup_service
    first = operations.create_object(document_id)["object_id"]
    other_id = operations.create_document("Other")["document"]["id"]
    other = operations.create_object(other_id)["object_id"]
    before = operations.inspect_document(document_id)
    calls = len(backend.calls)

    assert_error("NOT_FOUND", lambda: operations.connect_objects(document_id, first, other))
    assert_error("NOT_FOUND", lambda: operations.connect_objects(document_id, other, first))
    assert_error("NOT_FOUND", lambda: operations.move_object(document_id, other, 1, 2))
    assert len(backend.calls) == calls
    assert operations.inspect_document(document_id) == before
    operations.close_document(other_id)
    assert_error("NOT_FOUND", lambda: operations.inspect_document(other_id))
    assert_error("NOT_FOUND", lambda: operations.move_object(other_id, other, 1, 2))
    assert operations.create_document("Other")["document"]["id"] != other_id
    assert operations.inspect_document(document_id) == before


@pytest.mark.parametrize(
    "properties",
    [
        {"x": float("nan")},
        {"y": float("inf")},
        {"x": -1001},
        {"width": 0},
        {"height": 101},
        {"text": "x" * 2001},
        {"text": "bad\x00text"},
        {"text": "bad\ud800text"},
        {"type": "arbitrary code"},
    ],
)
def test_invalid_objects_never_reach_backend_or_change_state(setup_service, properties):
    operations, backend, document_id = setup_service
    before = operations.inspect_document(document_id)

    assert_error("INVALID_ARGUMENT", lambda: operations.create_object(document_id, **properties))

    assert backend.calls == []
    assert operations.inspect_document(document_id) == before


def test_partial_coordinate_assignment_is_not_committed(setup_service):
    operations, backend, document_id = setup_service
    first = operations.create_object(document_id)["object_id"]
    before = operations.inspect_document(document_id)
    calls = len(backend.calls)

    assert_error(
        "INVALID_ARGUMENT", lambda: operations.move_object(document_id, first, 12, float("inf"))
    )

    assert operations.inspect_document(document_id) == before
    assert len(backend.calls) == calls


def test_connection_constraints_are_checked_before_native_work(setup_service):
    operations, backend, document_id = setup_service
    first, second = add_pair(operations, document_id)
    before = operations.inspect_document(document_id)
    calls = len(backend.calls)

    assert_error("INVALID_ARGUMENT", lambda: operations.connect_objects(document_id, first, first))
    assert_error(
        "INVALID_ARGUMENT",
        lambda: operations.connect_objects(document_id, first, second, source_port="invalid"),
    )
    assert_error(
        "INVALID_ARGUMENT",
        lambda: operations.connect_objects(document_id, first, second, arrow="false"),
    )

    assert operations.inspect_document(document_id) == before
    assert len(backend.calls) == calls


def test_document_capacity_is_released_on_close(setup_service):
    operations, backend, document_id = setup_service
    maximum = operations.capabilities()["max_documents"]
    for index in range(maximum - 1):
        operations.create_document(f"Document {index}")
    assert_error("LIMIT_EXCEEDED", lambda: operations.create_document("Over capacity"))
    operations.close_document(document_id)
    assert operations.create_document("Replacement")["document"]["name"] == "Replacement"
    assert backend.calls == []


def test_node_and_edge_limits_preserve_last_valid_document(setup_service):
    operations, backend, document_id = setup_service
    limits = operations.capabilities()
    for _ in range(limits["max_nodes"]):
        operations.create_object(document_id)
    before = operations.inspect_document(document_id)
    calls = len(backend.calls)
    assert_error("INVALID_ARGUMENT", lambda: operations.create_object(document_id))
    assert operations.inspect_document(document_id) == before
    assert len(backend.calls) == calls

    first, second = [node["id"] for node in before["document"]["nodes"][:2]]
    for _ in range(limits["max_edges"]):
        operations.connect_objects(document_id, first, second)
    before = operations.inspect_document(document_id)
    calls = len(backend.calls)
    assert_error("INVALID_ARGUMENT", lambda: operations.connect_objects(document_id, first, second))
    assert operations.inspect_document(document_id) == before
    assert len(backend.calls) == calls


def test_export_empty_document_is_not_native_work(setup_service):
    operations, backend, document_id = setup_service
    assert_error("EMPTY_DIAGRAM", lambda: operations.export_diagram(document_id, "empty.svg"))
    assert backend.calls == []
    assert list(operations.workspace.iterdir()) == []


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.svg",
        "/tmp/escape.svg",
        "subdir/file.svg",
        "subdir\\file.svg",
        "..",
        ".hidden.svg",
        "wrong.png",
        "wrong.svg.tmp",
        "name\x00.svg",
        "a" * 121 + ".svg",
        "https://example.com/file.svg",
        "name\n.svg",
    ],
)
def test_export_rejects_paths_and_invalid_names_without_filesystem_changes(setup_service, filename):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    calls = len(backend.calls)

    assert_error("INVALID_ARGUMENT", lambda: operations.export_diagram(document_id, filename))

    assert len(backend.calls) == calls
    assert list(operations.workspace.iterdir()) == []


def test_export_does_not_overwrite_and_reports_published_bytes(setup_service):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    before = operations.inspect_document(document_id)
    destination = operations.workspace / "diagram.svg"
    destination.write_bytes(b"Keep existing bytes")
    calls = len(backend.calls)
    assert_error("ALREADY_EXISTS", lambda: operations.export_diagram(document_id, destination.name))
    assert destination.read_bytes() == b"Keep existing bytes"
    assert len(backend.calls) == calls

    result = operations.export_diagram(document_id, destination.name, overwrite=True)

    assert destination.read_bytes() == backend.payload
    assert result["bytes"] == len(backend.payload)
    assert result["sha256"] == hashlib.sha256(backend.payload).hexdigest()
    assert result["path"] == str(destination)
    assert result["revision"] == before["document"]["revision"]
    assert operations.inspect_document(document_id) == before
    assert list(operations.workspace.iterdir()) == [destination]


@pytest.mark.parametrize("existing", [False, True])
def test_failed_export_preserves_previous_file_and_cleans_staging(setup_service, existing):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    before = operations.inspect_document(document_id)
    destination = operations.workspace / "diagram.svg"
    if existing:
        destination.write_bytes(b"Earlier valid export")
    backend.fail = True

    assert_error(
        "BACKEND_FAILED",
        lambda: operations.export_diagram(document_id, destination.name, overwrite=existing),
    )

    assert operations.inspect_document(document_id) == before
    if existing:
        assert destination.read_bytes() == b"Earlier valid export"
    else:
        assert not destination.exists()
    assert not list(operations.workspace.glob(".dia-mcp-*"))


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("target_exists", [False, True])
def test_export_never_follows_existing_symlinks(setup_service, overwrite, target_exists):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    outside = operations.workspace.parent / "outside.svg"
    if target_exists:
        outside.write_bytes(b"Outside the export workspace")
    destination = operations.workspace / "diagram.svg"
    destination.symlink_to(outside)
    calls = len(backend.calls)

    assert_error(
        "ALREADY_EXISTS",
        lambda: operations.export_diagram(document_id, destination.name, overwrite=overwrite),
    )

    assert destination.is_symlink()
    assert len(backend.calls) == calls
    if target_exists:
        assert outside.read_bytes() == b"Outside the export workspace"
    else:
        assert not outside.exists()


@pytest.mark.parametrize("racing_symlink", [False, True])
def test_export_publication_race_keeps_other_writers_file(setup_service, racing_symlink):
    operations, backend, document_id = setup_service
    operations.create_object(document_id)
    before = copy.deepcopy(operations.inspect_document(document_id))
    destination = operations.workspace / "diagram.svg"
    outside = operations.workspace.parent / "other.svg"
    outside.write_bytes(b"Unrelated data")

    def race():
        if racing_symlink:
            destination.symlink_to(outside)
        else:
            destination.write_bytes(b"Other writer won")

    backend.after_render = race
    assert_error("ALREADY_EXISTS", lambda: operations.export_diagram(document_id, destination.name))

    assert outside.read_bytes() == b"Unrelated data"
    if racing_symlink:
        assert destination.is_symlink()
    else:
        assert destination.read_bytes() == b"Other writer won"
    assert operations.inspect_document(document_id) == before
    assert not list(operations.workspace.glob(".dia-mcp-*"))
