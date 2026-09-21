"""Fault injection at real listener/receipt boundaries without exposing test wire commands."""

import socket
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.client import LiveClient
from dia_mcp.live.listener import Listener
from dia_mcp.live.operations import Receipts
from dia_mcp.live.protocol import VERSION, decode, encode, validate


def operation(receipts):
    return {
        "action": "history",
        "request_id": receipts.prepare()["request_id"],
        "document_id": "d",
        "expected_generation": 1,
        "direction": "undo",
    }


def test_queued_receipts_pinned_and_cancelled_without_native_execution():
    receipts = Receipts("s", capacity=1, lifetime=1)
    request = operation(receipts)
    receipts.queued(request)
    receipts.entries[request["request_id"]]["created"] -= 100
    assert receipts.status(request["request_id"])["state"] == "queued"
    with pytest.raises(DiaError, match="in use"):
        receipts.prepare()
    with pytest.raises(DiaError) as error:
        receipts.queued(request)
    assert error.value.code == "OPERATION_IN_PROGRESS"
    # Reset timestamp so this test can inspect the cancellation before expiry.
    receipts.entries[request["request_id"]]["created"] = time.monotonic()
    receipts.cancel(request)
    assert receipts.status(request["request_id"])["outcome"] == "not_started"
    with pytest.raises(DiaError):
        receipts.run(request, lambda: pytest.fail("cancelled work must not run"))


@pytest.mark.parametrize("boundary", ["before", "after", "disconnect"])
def test_listener_deadline_and_disconnect_do_not_relabel_commit(boundary):
    receipts = Receipts("s")
    request = operation(receipts)
    receipts.queued(request)
    state = []
    replies = []
    client = SimpleNamespace(closed=False, respond=lambda **kw: replies.append(kw))
    server = object.__new__(Listener)
    server.closed, server.idle, server.executing = False, None, False
    server.queue = deque(
        [(client, request, time.monotonic() + (0.001 if boundary != "before" else -1))]
    )

    def execute():
        assert receipts.status(request["request_id"])["state"] == "executing"
        time.sleep(0.003)
        state.append("committed")
        if boundary == "disconnect":
            client.closed = True
        return {"committed": True}

    server.registry = SimpleNamespace(
        receipts=receipts, dispatch=lambda r: receipts.run(r, execute)
    )
    server._dispatch()
    receipt = receipts.status(request["request_id"])
    if boundary == "before":
        assert state == [] and receipt["outcome"] == "not_started"
        assert replies[0]["error"].code == "REQUEST_TIMEOUT"
    else:
        assert state == ["committed"] and receipt["state"] == "committed"
        assert replies[0]["result"]["committed"]
        assert receipts.run(request, lambda: pytest.fail("duplicate"))["committed"]


def test_known_rollback_unknown_failure_and_postcommit_serialization():
    for error, expected in [
        (DiaError("NATIVE_COMMAND_FAILED", "setter", outcome="rolled_back"), "rolled_back"),
        (DiaError("NEW_UNCLASSIFIED_ERROR", "unknown"), "uncertain"),
    ]:
        receipts = Receipts("s")
        request = operation(receipts)

        def execute():
            raise error

        with pytest.raises(DiaError):
            receipts.run(request, execute)
        assert receipts.status(request["request_id"])["state"] == expected
        with pytest.raises(DiaError):
            receipts.run(request, lambda: pytest.fail("retry"))
    # A post-native result-construction failure must not claim a rollback.
    receipts = Receipts("s")
    request = operation(receipts)
    with pytest.raises(DiaError):
        receipts.run(request, lambda: None)
    assert receipts.status(request["request_id"])["state"] == "uncertain"


@pytest.mark.parametrize("version", [0, 2, None, True])
def test_protocol_versions_fail_explicitly(version):
    with pytest.raises(DiaError) as error:
        validate({"protocol_version": version, "action": "handshake"})
    assert error.value.code == "LIVE_PROTOCOL_MISMATCH"


@pytest.mark.parametrize(
    "capabilities,expected",
    [
        ([], "UNSUPPORTED_LIVE_CAPABILITY"),
        (["documents.read", "future.optional"], None),
        (None, "LIVE_INVALID_RESPONSE"),
    ],
)
def test_capability_negotiation_before_sending_action(tmp_path, capabilities, expected):
    path = tmp_path / "socket"
    observed = []
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen()

        def peer():
            conn, _ = listener.accept()
            with conn, conn.makefile("rb") as stream:
                observed.append(decode(stream.readline(), 16384)["action"])
                conn.sendall(
                    encode(
                        {
                            "protocol_version": VERSION,
                            "result": {
                                "integration_api_version": VERSION,
                                "capabilities": capabilities,
                            },
                        },
                        16384,
                    )
                )
                data = stream.readline()
                if data:
                    observed.append(decode(data, 16384)["action"])
                    conn.sendall(
                        encode({"protocol_version": VERSION, "result": {"items": []}}, 16384)
                    )

        thread = threading.Thread(target=peer)
        thread.start()
        try:
            if expected:
                with pytest.raises(DiaError) as error:
                    LiveClient(path).request("list_documents")
                assert error.value.code == expected
            else:
                assert LiveClient(path).request("list_documents") == {"items": []}
        finally:
            thread.join(timeout=3)
        assert not thread.is_alive()
    assert observed == (["handshake"] if expected else ["handshake", "list_documents"])


def test_transport_loss_after_mutation_send_has_receipt_recovery(tmp_path):
    path = tmp_path / "lost-response"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen()

        def peer():
            conn, _ = listener.accept()
            with conn, conn.makefile("rb") as stream:
                stream.readline()
                conn.sendall(
                    encode(
                        {
                            "protocol_version": 1,
                            "result": {
                                "integration_api_version": 1,
                                "capabilities": ["history.write"],
                            },
                        },
                        16384,
                    )
                )
                assert decode(stream.readline(), 16384)["request_id"] == "ticket"
                # Native result may already have committed: deliberately lose reply.

        thread = threading.Thread(target=peer)
        thread.start()
        with pytest.raises(DiaError) as error:
            LiveClient(path).request(
                "history",
                document_id="d",
                request_id="ticket",
                expected_generation=1,
                direction="undo",
            )
        thread.join(timeout=3)
        assert error.value.outcome == "uncertain"
        assert error.value.details["request_id"] == "ticket"
    with pytest.raises(DiaError) as error:
        LiveClient(tmp_path / "missing").request(
            "history", document_id="d", request_id="ticket", expected_generation=1, direction="undo"
        )
    assert error.value.outcome == "not_started"


def test_unclassified_native_exception_after_commit_cannot_claim_rollback():
    from dia_mcp.live.registry import Registry

    changed = []

    def apply(doc, commands):
        changed.append("committed")
        raise RuntimeError("lost return after native commit")

    registry = Registry(SimpleNamespace(live_apply=apply), writable=True)
    request = operation(registry.receipts)
    request["commands"] = [{"op": "create", "type": "Standard - Box", "x": 0, "y": 0}]
    with pytest.raises(DiaError) as error:
        registry.receipts.run(request, lambda: registry._apply(None, "d", {}, request, {}))
    assert changed == ["committed"] and error.value.outcome == "uncertain"
    assert registry.receipts.status(request["request_id"])["state"] == "uncertain"


def test_certificate_is_required_for_confirmed_native_rollback():
    from dia_mcp.live.registry import Registry

    class Certificate(RuntimeError):
        pass

    def apply(doc, commands):
        raise Certificate("fully reversed")

    registry = Registry(
        SimpleNamespace(live_apply=apply, LiveRollbackError=Certificate), writable=True
    )
    request = operation(registry.receipts)
    request["commands"] = [{"op": "create", "type": "Standard - Box", "x": 0, "y": 0}]
    with pytest.raises(DiaError) as error:
        registry.receipts.run(request, lambda: registry._apply(None, "d", {}, request, {}))
    assert error.value.outcome == "rolled_back"
    assert registry.receipts.status(request["request_id"])["state"] == "rolled_back"


@pytest.mark.parametrize("boundary", ["success", "error", "shutdown", "base_exception"])
def test_nested_gtk_loop_cannot_reenter_native_dispatch(boundary):
    from dia_mcp.live.protocol import Limits

    class Scheduler:
        def __init__(self):
            self.callbacks = []
            self.scheduled = 0

        def idle_add(self, callback):
            self.callbacks.append(callback)
            self.scheduled += 1
            return self.scheduled

        def run_one(self):
            return self.callbacks.pop(0)()

    class NativeAbort(BaseException):
        pass

    events, replies = [], []
    server = object.__new__(Listener)
    server.glib = Scheduler()
    server.limits = Limits()
    server.queue = deque()
    server.closed, server.idle, server.executing = False, None, False
    client = SimpleNamespace(closed=False, respond=lambda **kw: replies.append(kw))

    def dispatch(request):
        events.append((request["number"], "start"))
        assert server.executing
        if request["number"] == 1:
            server.submit(client, {"action": "get_document", "number": 2})
            server.submit(client, {"action": "get_document", "number": 3})
            # Pump the adversarial nested main loop. The buggy listener creates
            # an idle source here, allowing request 2 inside native request 1.
            while server.glib.callbacks:
                server.glib.run_one()
            assert events == [(1, "start")]
            assert len(server.queue) == 2
            assert server.idle is None
            # Defensive direct callback reentry must not dequeue or clear flags.
            assert server._dispatch() is False
            assert server.executing and len(server.queue) == 2
            if boundary == "shutdown":
                server.closed = True  # stop() also closes clients and clears queue
                server.queue.clear()
            if boundary == "error":
                raise RuntimeError("plugin failed after nested GTK loop")
            if boundary == "base_exception":
                raise NativeAbort()
        events.append((request["number"], "end"))
        return {"number": request["number"]}

    server.registry = SimpleNamespace(dispatch=dispatch)
    server.submit(client, {"action": "get_document", "number": 1})
    if boundary == "base_exception":
        with pytest.raises(NativeAbort):
            server.glib.run_one()
    else:
        assert server.glib.run_one() is False
    assert not server.executing
    if boundary == "shutdown":
        assert server.idle is None and not server.glib.callbacks
        assert server.glib.scheduled == 1
        return
    assert len(server.glib.callbacks) == 1  # exactly one deferred successor
    server.glib.run_one()
    assert len(server.glib.callbacks) == 1
    server.glib.run_one()
    assert not server.glib.callbacks and not server.queue and server.idle is None
    assert not server.executing
    assert events[-4:] == [(2, "start"), (2, "end"), (3, "start"), (3, "end")]
    assert server.glib.scheduled == 3
    if boundary == "error":
        assert replies[0]["error"].code == "LIVE_READ_FAILED"
