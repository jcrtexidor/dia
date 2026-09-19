"""Portable contract, dispatch, safety, and client failure tests."""

import socket
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.client import LiveClient
from dia_mcp.live.listener import Listener, private_directory
from dia_mcp.live.protocol import Limits, decode, encode, page, validate
from dia_mcp.live.registry import Registry


def request(action="handshake", **params):
    return {"protocol_version": 1, "action": action, **params}


@pytest.mark.parametrize(
    "value,code",
    [
        ({"protocol_version": 2, "action": "handshake"}, "LIVE_PROTOCOL_MISMATCH"),
        ({"protocol_version": True, "action": "handshake"}, "LIVE_PROTOCOL_MISMATCH"),
        (request("eval", code="bad"), "UNSUPPORTED_LIVE_CAPABILITY"),
        (request(extra=True), "INVALID_ARGUMENT"),
        (request("get_object", document_id="a"), "INVALID_ARGUMENT"),
        (request("list_objects", document_id="a", limit=101), "INVALID_ARGUMENT"),
        (request("list_objects", document_id="a", offset=-1), "INVALID_ARGUMENT"),
        (request("list_objects", document_id="a", limit=True), "INVALID_ARGUMENT"),
        (request("get_object", document_id="a", object_id="b", properties=1), "INVALID_ARGUMENT"),
    ],
)
def test_schema_rejects(value, code):
    with pytest.raises(DiaError) as exc:
        validate(value)
    assert exc.value.code == code


def test_wire_limits_and_pagination():
    with pytest.raises(DiaError):
        encode({"v": "x" * 100}, 30)
    with pytest.raises(DiaError):
        encode({"v": float("nan")}, 100)
    for data in (b"[]", b"{", b"\xff", b"x" * 101):
        with pytest.raises(DiaError):
            decode(data, 100)
    assert page([1, 2, 3], {"offset": 1, "limit": 1}, Limits()) == {
        "items": [2],
        "total": 3,
        "next_offset": 2,
    }
    assert page([1], {"offset": 8}, Limits())["next_offset"] is None


def test_no_native_access_from_foreign_thread():
    registry = Registry(None)
    errors = []

    def worker():
        try:
            registry.dispatch(request())
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert len(errors) == 1


def test_document_generation_and_wrong_session():
    registry = Registry(None)
    layer = SimpleNamespace(live_id="l", name="Background", visible=True)
    doc = SimpleNamespace(
        live_state=("d", 1),
        filename="test",
        modified=False,
        layers=[layer],
        active_layer=layer,
        selected=[],
    )
    did = registry._doc_id(doc)
    assert registry._generation(doc, did) == registry._generation(doc, did) == 1
    doc.live_state = ("d", 2)
    assert registry._generation(doc, did) == 2
    doc.selected = [SimpleNamespace(live_id="o")]
    assert registry._generation(doc, did) == 3
    with pytest.raises(DiaError) as exc:
        registry._check_session("snapshot-id")
    assert exc.value.code == "WRONG_SESSION"


class Scheduler:
    def __init__(self):
        self.callbacks = []

    def idle_add(self, callback):
        self.callbacks.append(callback)
        return len(self.callbacks)


def test_bounded_dispatch_timeout_disconnect_and_order():
    reads = []
    server = object.__new__(Listener)
    server.glib = Scheduler()
    server.registry = SimpleNamespace(dispatch=lambda r: reads.append(r) or {})
    server.limits = Limits(queue=1)
    server.queue = deque()
    server.idle = None
    server.closed = False
    replies = []
    client = SimpleNamespace(closed=False, respond=lambda **kw: replies.append(kw))
    server.submit(client, request())
    server.submit(client, request())
    assert replies[0]["error"].code == "LIVE_QUEUE_FULL"
    assert not reads  # receiver only queues
    server._dispatch()
    assert reads == [request()]
    server.queue.append((client, request(), time.monotonic() - 1))
    server._dispatch()
    assert replies[-1]["error"].code == "REQUEST_TIMEOUT"
    assert len(reads) == 1
    client.closed = True
    server.queue.append((client, request(), time.monotonic() + 1))
    server._dispatch()
    assert len(reads) == 1


def test_private_directory_rejects_shared_and_symlink(tmp_path):
    private_directory(tmp_path)
    other = tmp_path / "other"
    other.mkdir(mode=0o755)
    with pytest.raises(DiaError):
        private_directory(other)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DiaError):
        private_directory(link)


def test_client_unavailable_and_timeout(tmp_path):
    with pytest.raises(DiaError) as exc:
        LiveClient(tmp_path / "missing").request("handshake")
    assert exc.value.code == "LIVE_BACKEND_UNAVAILABLE"
    path = tmp_path / "listener"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen()
        with pytest.raises(DiaError) as exc:
            LiveClient(path, timeout=0.01).request("handshake")
    assert exc.value.code == "REQUEST_TIMEOUT"


def test_listener_refuses_unsafe_endpoints_and_recovers_stale_socket(tmp_path):
    from dia_mcp.live.listener import Listener

    class GLibStub:
        IO_IN = 1

        def io_add_watch(self, *args):
            return 1

        def timeout_add(self, *args):
            return 2

        def source_remove(self, source):
            return True

    path = tmp_path / "live.sock"
    path.write_text("keep this file")
    with pytest.raises(DiaError):
        Listener(GLibStub(), None, path)
    assert path.read_text() == "keep this file"
    path.unlink()
    with socket.socket(socket.AF_UNIX) as stale:
        stale.bind(str(path))
    listener = Listener(GLibStub(), None, path)
    try:
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(BlockingIOError):
            Listener(GLibStub(), None, path)
        assert path.exists()
    finally:
        listener.stop()
    assert not path.exists()


def test_registry_marks_unsupported_values_without_reading_them():
    class Object:
        @property
        def properties(self):
            raise AssertionError("Must not even construct a file-backed PyDiaProperty")

        def property_descriptors(self, limit):
            return {
                "items": [{"name": "image_file", "type": "pixbuf", "visible": True}],
                "total": 1,
                "truncated": False,
            }

    result = Registry(None)._properties(Object())
    assert result["items"][0]["supported"] is False


@pytest.mark.parametrize(
    "limits", [{"page": 1.5}, {"queue": 0}, {"timeout": 31}, {"timeout": True}]
)
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        Limits(**limits)


def test_membership_traversal_releases_wrappers_without_cyclic_gc():
    import gc
    import weakref

    refs = []

    class Object:
        live_id = "object"
        group_members = ()

    class Layer:
        @property
        def objects(self):
            wrapper = Object()
            refs.append(weakref.ref(wrapper))
            return [wrapper]

    registry = Registry(None)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        objects = registry._objects(SimpleNamespace(layers=[Layer()]), "document")
        assert refs[0]() is not None
        del objects
        assert refs[0]() is None, "No wrapper may wait for cyclic GC after a read"
    finally:
        if was_enabled:
            gc.enable()
