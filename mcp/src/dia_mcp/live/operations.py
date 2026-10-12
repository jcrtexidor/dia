"""Bounded local receipts. No native wrappers or unbounded expiry tombstones."""

import hashlib
import json
import time
from collections import OrderedDict
from uuid import uuid4

from ..errors import DiaError


class Receipts:
    def __init__(self, session, capacity=256, lifetime=1800):
        self.session, self.capacity, self.lifetime = session, capacity, lifetime
        self.entries = OrderedDict()

    def _expire(self):
        now = time.monotonic()
        for key in list(self.entries):
            entry = self.entries[key]
            if (
                entry["state"] not in {"queued", "executing"}
                and now - entry["created"] > self.lifetime
            ):
                del self.entries[key]

    def prepare(self):
        self._expire()
        if len(self.entries) >= self.capacity:
            victim = next(
                (
                    key
                    for key, entry in self.entries.items()
                    if entry["state"] not in {"queued", "executing"}
                ),
                None,
            )
            if victim is None:
                raise DiaError(
                    "LIVE_QUEUE_FULL", "All receipt slots are in use", outcome="not_started"
                )
            del self.entries[victim]
        key = f"{self.session}:{uuid4().hex}"
        self.entries[key] = {"created": time.monotonic(), "status": "prepared", "state": "prepared"}
        return {
            "request_id": key,
            "status": "prepared",
            "state": "prepared",
            "expires_after_seconds": self.lifetime,
            "capacity": self.capacity,
        }

    def get(self, key):
        self._expire()
        if key not in self.entries:
            raise DiaError(
                "UNKNOWN_OPERATION",
                "Receipt expired, evicted, or from another session; "
                "inspect state before preparing a new operation",
                outcome="uncertain",
            )
        return self.entries[key]

    def status(self, key):
        return {
            "request_id": key,
            **{k: v for k, v in self.get(key).items() if k not in {"created", "fingerprint"}},
        }

    def _match(self, request):
        entry = self.get(request["request_id"])
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        if "fingerprint" in entry and entry["fingerprint"] != fingerprint:
            raise DiaError(
                "OPERATION_CONFLICT",
                "A request ID cannot be reused for different input",
                outcome="not_started",
            )
        entry["fingerprint"] = fingerprint
        return entry

    def queued(self, request):
        entry = self._match(request)
        if entry["state"] in {"queued", "executing"}:
            raise DiaError(
                "OPERATION_IN_PROGRESS",
                "Query this receipt after the pending request",
                outcome="not_started",
            )
        if entry["state"] == "prepared":
            entry.update(state="queued", status="queued")

    def cancel(self, request, code="REQUEST_CANCELLED"):
        # Called only for this connection's removed queue entry, never executing work.
        entry = self.entries.get(request["request_id"])
        if entry and entry["state"] == "queued":
            error = DiaError(
                code, "Request left the queue before native execution", outcome="not_started"
            )
            entry.update(
                state="failed", status="failed", outcome="not_started", error=error.record()
            )

    def run(self, request, execute):
        entry = self._match(request)
        if entry["state"] in {"failed", "rolled_back", "uncertain"}:
            raise DiaError(**entry["error"])
        if entry["state"] == "committed":
            return entry["result"]
        if entry["state"] == "executing":
            raise DiaError("OPERATION_IN_PROGRESS", "Operation is executing", outcome="not_started")
        entry.update(status="executing", state="executing")
        start = time.monotonic()
        try:
            result = execute()
            result.update(
                request_id=request["request_id"],
                elapsed_ms=round((time.monotonic() - start) * 1000, 3),
            )
        except Exception as exc:
            if not isinstance(exc, DiaError):
                exc = DiaError(
                    "OPERATION_UNCERTAIN",
                    "Inspect state and receipt before further changes",
                    outcome="uncertain",
                )
            outcome = exc.outcome or "uncertain"
            exc.outcome = outcome
            state = {"not_started": "failed", "rolled_back": "rolled_back"}.get(
                outcome, "uncertain"
            )
            entry.update(
                state=state,
                status="failed" if state != "uncertain" else "uncertain",
                outcome=outcome,
                error=exc.record(),
            )
            raise exc from None
        entry.update(status="succeeded", state="committed", outcome="committed", result=result)
        return result
