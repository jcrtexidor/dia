from pathlib import Path
from types import SimpleNamespace

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.files import NativeFiles


class Native:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def live_file(self, action, doc, physical, fmt, logical):
        self.calls.append((action, logical))
        if action == "stage":
            Path(physical).write_bytes(b"native graph: opaque objects/groups/connections")
            if self.fail:
                raise OSError("serializer failed")
        if action == "commit":
            doc.filename, doc.modified = logical, False
        if action == "open":
            return SimpleNamespace(filename=logical)


def test_failed_serializer_preserves_target_and_document(tmp_path):
    target = tmp_path / "old.dia"
    target.write_bytes(b"old")
    native = Native(fail=True)
    doc = SimpleNamespace(filename="original.dia", modified=True)
    with pytest.raises(DiaError, match="serializer failed"):
        NativeFiles(native, tmp_path).write(
            doc, {"action": "save_document_as", "path": str(target), "overwrite": True}
        )
    assert target.read_bytes() == b"old"
    assert doc.modified and doc.filename == "original.dia"
    assert list(tmp_path.iterdir()) == [target]
    assert [c[0] for c in native.calls] == ["stage"]


def test_save_as_and_export(tmp_path):
    native = Native()
    files = NativeFiles(native, tmp_path)
    doc = SimpleNamespace(filename="original.dia", modified=True)
    result = files.write(doc, {"action": "save_document_as", "path": "new.dia"})
    assert result["published"] and result["saved"]
    assert doc.filename == str(tmp_path / "new.dia") and not doc.modified
    doc.modified = True
    result = files.write(doc, {"action": "export_document", "path": "drawing.svg", "format": "svg"})
    assert result["published"] and not result["saved"] and doc.modified
    assert [c[0] for c in native.calls] == ["stage", "commit", "stage"]


def test_overwrite_is_explicit(tmp_path):
    target = tmp_path / "a.dia"
    target.touch()
    native = Native()
    doc = SimpleNamespace(filename=str(target), modified=True)
    with pytest.raises(DiaError) as error:
        NativeFiles(native, tmp_path).write(doc, {"action": "save_document"})
    assert error.value.code == "FILE_EXISTS"
    assert not native.calls


@pytest.mark.parametrize("path", ["../escape.dia", "link/a.dia", "linked.dia"])
def test_reject_traversal_and_symlinks(tmp_path, path):
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "real.dia").touch()
    (tmp_path / "linked.dia").symlink_to(tmp_path / "real.dia")
    native = Native()
    with pytest.raises(DiaError):
        NativeFiles(native, tmp_path).open({"path": path})
    assert not native.calls


def test_no_clobber_race(tmp_path):
    class Racing(Native):
        def live_file(self, action, doc, physical, fmt, logical):
            super().live_file(action, doc, physical, fmt, logical)
            if action == "stage":
                Path(logical).write_bytes(b"concurrent writer")

    doc = SimpleNamespace(filename="before.dia", modified=True)
    with pytest.raises(DiaError):
        NativeFiles(Racing(), tmp_path).write(
            doc, {"action": "save_document_as", "path": "race.dia"}
        )
    assert (tmp_path / "race.dia").read_bytes() == b"concurrent writer"
    assert doc.modified and doc.filename == "before.dia"
    assert len(list(tmp_path.iterdir())) == 1


def test_disabled_without_local_configuration(monkeypatch):
    monkeypatch.delenv("DIA_MCP_FILES_ROOT", raising=False)
    with pytest.raises(DiaError) as error:
        NativeFiles(Native()).open({"path": "a.dia"})
    assert error.value.code == "LIVE_FILES_DISABLED"


def test_empty_successful_serializer_does_not_publish(tmp_path):
    class Empty(Native):
        def live_file(self, *args):
            pass

    doc = SimpleNamespace(filename="before.dia", modified=True)
    with pytest.raises(DiaError, match="nonempty"):
        NativeFiles(Empty(), tmp_path).write(
            doc, {"action": "save_document_as", "path": "empty.dia"}
        )
    assert not list(tmp_path.iterdir())
    assert doc.modified and doc.filename == "before.dia"
