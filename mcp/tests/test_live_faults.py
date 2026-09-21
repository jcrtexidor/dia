"""Real local files plus injected boundary failures; no native runtime required."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.files import NativeFiles
from dia_mcp.live.operations import Receipts


class Native:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []

    def live_file(self, action, doc, physical, fmt, logical):
        self.calls.append(action)
        if action == "stage":
            Path(physical).write_bytes(b"new native content")
            Path(physical + "~").write_bytes(b"native temporary backup")
            if self.failure == "serialize":
                raise OSError("injected serializer failure")
        elif action == "commit":
            if self.failure == "commit_before":
                raise OSError("injected commit failure before state update")
            doc.filename, doc.modified = logical, False
            if self.failure == "commit_after":
                raise RuntimeError("injected commit failure after state update")


def operation(tmp_path, failure=None, overwrite=True, exporting=False):
    native = Native(failure)
    doc = SimpleNamespace(filename="original.dia", modified=True)
    files = NativeFiles(native, tmp_path)
    receipts = Receipts("files-test")
    request = {
        "action": "export_document" if exporting else "save_document_as",
        "path": "target.dia",
        "overwrite": overwrite,
        "request_id": receipts.prepare()["request_id"],
    }
    return native, doc, receipts, request, lambda: files.write(doc, request)


def assert_no_replay(receipts, request, execute, native, *, error=None):
    before = list(native.calls)
    if error is None:
        result = receipts.run(request, execute)
        assert result == receipts.status(request["request_id"])["result"]
    else:
        with pytest.raises(DiaError) as repeated:
            receipts.run(request, execute)
        assert repeated.value.record() == error.record()
    assert native.calls == before


@pytest.mark.parametrize("boundary", ["serialize", "stage_sync", "replace", "link"])
def test_prepublication_failure_preserves_bytes_and_editor(tmp_path, monkeypatch, boundary):
    overwrite = boundary != "link"
    target = tmp_path / "target.dia"
    if overwrite:
        target.write_bytes(b"existing content")
    native, doc, receipts, request, execute = operation(tmp_path, boundary, overwrite)
    original_fsync = os.fsync
    if boundary == "stage_sync":

        def fsync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("injected stage sync failure")
            return original_fsync(fd)

        monkeypatch.setattr(os, "fsync", fsync)
    if boundary in {"replace", "link"}:

        def fail(*args, **kwargs):
            raise OSError("injected publication failure")

        monkeypatch.setattr(os, boundary, fail)
    with pytest.raises(DiaError) as error:
        receipts.run(request, execute)
    assert error.value.outcome == "not_started"
    assert error.value.details["published"] is False
    assert error.value.details["saved"] is False
    assert doc.filename == "original.dia" and doc.modified
    if overwrite:
        assert target.read_bytes() == b"existing content"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".dia-live-*"))
    assert "commit" not in native.calls
    receipt = receipts.status(request["request_id"])
    assert receipt["state"] == "failed" and receipt["outcome"] == "not_started"
    assert receipt["error"]["details"] == error.value.details
    assert_no_replay(receipts, request, execute, native, error=error.value)


@pytest.mark.parametrize("boundary", ["commit_before", "commit_after"])
def test_postpublication_commit_failure_is_uncertain(tmp_path, boundary):
    target = tmp_path / "target.dia"
    target.write_bytes(b"existing content")
    native, doc, receipts, request, execute = operation(tmp_path, boundary)
    with pytest.raises(DiaError) as error:
        receipts.run(request, execute)
    assert error.value.code == "FILE_POSTCOMMIT_UNCERTAIN"
    assert error.value.outcome == "uncertain"
    details = error.value.details
    assert details["published"] and details["saved"] is None
    assert details["phase"] == "commit"
    assert details["cleanup_complete"] and details["directory_synced"]
    assert target.read_bytes() == b"new native content"
    if boundary == "commit_before":
        assert doc.filename == "original.dia" and doc.modified
    else:
        assert doc.filename == str(target) and not doc.modified
    assert not list(tmp_path.glob(".dia-live-*"))
    receipt = receipts.status(request["request_id"])
    assert receipt["state"] == "uncertain" and receipt["outcome"] == "uncertain"
    assert receipt["error"]["details"] == details
    assert_no_replay(receipts, request, execute, native, error=error.value)


@pytest.mark.parametrize("exporting", [False, True])
@pytest.mark.parametrize("boundary", ["cleanup", "directory_sync"])
def test_confirmed_publication_keeps_success_with_explicit_warning(
    tmp_path, monkeypatch, exporting, boundary
):
    native, doc, receipts, request, execute = operation(
        tmp_path, overwrite=False, exporting=exporting
    )
    original_fsync, original_unlink = os.fsync, os.unlink
    if boundary == "cleanup":

        def unlink(path, *args, **kwargs):
            if str(path).startswith(".dia-live-"):
                raise PermissionError("injected cleanup failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", unlink)
    else:

        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected directory sync failure")
            return original_fsync(fd)

        monkeypatch.setattr(os, "fsync", fsync)
    result = receipts.run(request, execute)
    assert result["published"] and result["saved"] is (not exporting)
    assert any(warning["phase"] == boundary for warning in result["warnings"])
    assert result["cleanup_complete"] is (boundary != "cleanup")
    assert result["directory_synced"] is (boundary != "directory_sync")
    assert (tmp_path / "target.dia").read_bytes() == b"new native content"
    if exporting:
        assert doc.filename == "original.dia" and doc.modified
    else:
        assert doc.filename == str(tmp_path / "target.dia") and not doc.modified
    leftovers = list(tmp_path.glob(".dia-live-*"))
    assert bool(leftovers) is (boundary == "cleanup")
    receipt = receipts.status(request["request_id"])
    assert receipt["state"] == "committed" and receipt["outcome"] == "committed"
    assert_no_replay(receipts, request, execute, native)
    # Retained stage names are reported; remove only these test-owned artifacts.
    for leftover in leftovers:
        original_unlink(leftover)


def test_cleanup_does_not_mask_prepublication_error(tmp_path, monkeypatch):
    target = tmp_path / "target.dia"
    target.write_bytes(b"existing content")
    native, doc, receipts, request, execute = operation(tmp_path, "serialize")
    original_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        if str(path).startswith(".dia-live-"):
            raise PermissionError("injected cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(DiaError, match="serializer failure") as error:
        receipts.run(request, execute)
    assert error.value.outcome == "not_started"
    assert not error.value.details["published"]
    assert not error.value.details["cleanup_complete"]
    assert error.value.details["warnings"]
    assert target.read_bytes() == b"existing content"
    assert doc.filename == "original.dia" and doc.modified
    assert receipts.status(request["request_id"])["state"] == "failed"
    for leftover in tmp_path.glob(".dia-live-*"):
        original_unlink(leftover)


def test_combined_postpublication_faults_retain_all_known_facts(tmp_path, monkeypatch):
    native, doc, receipts, request, execute = operation(tmp_path, "commit_after")
    original_fsync, original_unlink = os.fsync, os.unlink

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory sync failure")
        return original_fsync(fd)

    def unlink(path, *args, **kwargs):
        if str(path).startswith(".dia-live-"):
            raise PermissionError("injected cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(DiaError) as error:
        receipts.run(request, execute)
    details = error.value.details
    assert error.value.outcome == "uncertain"
    assert details["published"] and details["saved"] is None
    assert not details["cleanup_complete"] and not details["directory_synced"]
    assert {warning["phase"] for warning in details["warnings"]} == {"cleanup", "directory_sync"}
    assert (tmp_path / "target.dia").read_bytes() == b"new native content"
    assert doc.filename == str(tmp_path / "target.dia") and not doc.modified
    assert_no_replay(receipts, request, execute, native, error=error.value)
    for leftover in tmp_path.glob(".dia-live-*"):
        original_unlink(leftover)


def test_directory_close_failure_does_not_reclassify_committed_save(tmp_path, monkeypatch):
    native, doc, receipts, request, execute = operation(tmp_path)
    original_close = os.close
    injected = []

    def close(fd):
        final_directory = (
            "commit" in native.calls
            and stat.S_ISDIR(os.fstat(fd).st_mode)
            and os.readlink(f"/proc/self/fd/{fd}") == str(tmp_path)
        )
        original_close(fd)
        if final_directory:
            injected.append(fd)
            raise OSError("injected directory close failure")

    monkeypatch.setattr(os, "close", close)
    result = receipts.run(request, execute)
    assert injected
    assert result["published"] and result["saved"] and result["directory_synced"]
    assert result["warnings"][0]["phase"] == "directory_close"
    assert (tmp_path / "target.dia").read_bytes() == b"new native content"
    assert doc.filename == str(tmp_path / "target.dia") and not doc.modified
    assert receipts.status(request["request_id"])["state"] == "committed"
    assert_no_replay(receipts, request, execute, native)
