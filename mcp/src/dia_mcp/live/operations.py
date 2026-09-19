"""Bounded, one-use operation receipts; no native objects are retained here."""

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
            if now - self.entries[key]["created"] > self.lifetime:
                del self.entries[key]

    def prepare(self):
        self._expire()
        while len(self.entries) >= self.capacity:
            self.entries.popitem(last=False)
        key = f"{self.session}:{uuid4().hex}"
        self.entries[key] = {"created": time.monotonic(), "status": "prepared"}
        return {
            "request_id": key,
            "status": "prepared",
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
            )
        return self.entries[key]

    def status(self, key):
        return {
            "request_id": key,
            **{k: v for k, v in self.get(key).items() if k not in {"created", "fingerprint"}},
        }

    def run(self, request, execute):
        key = request["request_id"]
        entry = self.get(key)
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        if "fingerprint" in entry:
            if entry["fingerprint"] != fingerprint:
                raise DiaError(
                    "OPERATION_CONFLICT", "A request ID cannot be reused for different input"
                )
            if entry["status"] == "failed":
                raise DiaError(**entry["error"])
            if entry["status"] == "uncertain":
                raise DiaError(
                    "OPERATION_UNCERTAIN",
                    "Inspect document and files; this operation will not be repeated",
                )
            return entry["result"]
        entry.update(fingerprint=fingerprint, status="uncertain")
        start = time.monotonic()
        try:
            result = execute()
        except DiaError as exc:
            entry.update(status="failed", error={"code": exc.code, "message": str(exc)})
            raise
        except Exception as exc:
            # A native failure normally rolls back. An unexpected postcommit error
            # cannot be advertised as a safe retry: leave an uncertain receipt.
            raise DiaError(
                "OPERATION_UNCERTAIN", "Inspect state and receipt before further changes"
            ) from exc
        result.update(request_id=key, elapsed_ms=round((time.monotonic() - start) * 1000, 3))
        entry.update(status="succeeded", result=result)
        return result
