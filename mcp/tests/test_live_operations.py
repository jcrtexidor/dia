"""Mutation fencing, receipts and bounded command validation."""

import pytest

from dia_mcp.errors import DiaError
from dia_mcp.live.operations import Receipts
from dia_mcp.live.protocol import validate, validate_commands
from dia_mcp.live.registry import Registry


def test_receipts_replay_exact_result_without_reexecution():
    receipts = Receipts("session")
    ticket = receipts.prepare()["request_id"]
    request = {"request_id": ticket, "value": 1}
    calls = []
    result = receipts.run(request, lambda: calls.append(1) or {"committed": True})
    assert receipts.run(request, lambda: pytest.fail("must not repeat")) == result
    assert len(calls) == 1
    assert receipts.status(ticket)["status"] == "succeeded"
    with pytest.raises(DiaError, match="different input"):
        receipts.run({**request, "value": 2}, lambda: None)


def test_eviction_and_expiry_never_authorize_replay():
    receipts = Receipts("session", capacity=1)
    first = receipts.prepare()["request_id"]
    second = receipts.prepare()["request_id"]
    with pytest.raises(DiaError) as exc:
        receipts.run({"request_id": first}, lambda: pytest.fail("evicted operation ran"))
    assert exc.value.code == "UNKNOWN_OPERATION"
    assert exc.value.outcome == "uncertain"
    receipts.entries[second]["created"] -= 1801
    with pytest.raises(DiaError):
        receipts.status(second)


def test_failed_and_uncertain_receipts_are_not_reexecuted():
    receipts = Receipts("session")
    for error, status in [
        (DiaError("CONFLICT", "changed", outcome="not_started"), "failed"),
        (RuntimeError("after commit"), "uncertain"),
    ]:
        ticket = receipts.prepare()["request_id"]

        def fail():
            raise error

        with pytest.raises(DiaError):
            receipts.run({"request_id": ticket}, fail)
        assert receipts.status(ticket)["status"] == status
        with pytest.raises(DiaError):
            receipts.run({"request_id": ticket}, lambda: pytest.fail("repeat"))


@pytest.mark.parametrize(
    "commands",
    [
        [],
        [{"op": "eval"}],
        [{"op": "move", "object_id": "x", "x": 10**400, "y": 0}],
        [{"op": []}],
        [{"op": "move", "object_id": "x", "x": True, "y": 2}],
        [{"op": "move", "object_id": "x", "x": float("inf"), "y": 2}],
        [{"op": "create", "type": "T", "x": 0, "y": 0, "properties": {"a": []}}],
        [{"op": "layout", "object_ids": ["x", "x"], "mode": "left"}],
        [{"op": "disconnect", "object_id": "x", "handle": -1}],
        [{"op": "create", "type": "T", "x": 0, "y": 0, "extra": True}],
    ],
)
def test_invalid_commands(commands):
    with pytest.raises(DiaError):
        validate_commands(commands)


def test_write_gate_precedes_native_access():
    registry = Registry(None)
    with pytest.raises(DiaError) as exc:
        registry.dispatch({"action": "prepare_operation"})
    assert exc.value.code == "LIVE_WRITE_DISABLED"
    with pytest.raises(DiaError):
        validate(
            {
                "protocol_version": 1,
                "action": "history",
                "document_id": "d",
                "request_id": "r",
                "expected_generation": True,
                "direction": "undo",
            }
        )


def test_analysis_domain_rejects_non_string():
    with pytest.raises(DiaError):
        validate(
            {"protocol_version": 1, "action": "analyze_document", "document_id": "d", "domain": []}
        )
