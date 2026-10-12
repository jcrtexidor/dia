"""External transport client. Never imports Dia or GTK."""

import socket
import time
from pathlib import Path

from ..errors import DiaError
from .protocol import MUTATIONS, REQUIRED_CAPABILITY, VERSION, Limits, decode, encode, validate


class LiveClient:
    def __init__(self, path: Path, timeout: float = 5):
        self.path = str(path)
        self.limits = Limits(timeout=timeout)

    def request(self, action: str, **params) -> dict:
        request = validate({"protocol_version": VERSION, "action": action, **params}, self.limits)
        deadline = time.monotonic() + self.limits.timeout
        mutation_sent = False

        def transport_error(code, message):
            if action in MUTATIONS:
                return DiaError(
                    code,
                    message,
                    outcome="uncertain" if mutation_sent else "not_started",
                    details={
                        "request_id": params["request_id"],
                        "recovery": "Query receipt; do not repeat with a new ID",
                    },
                )
            return DiaError(code, message)

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.limits.timeout)
                sock.connect(self.path)
                buffer = bytearray()

                def remaining():
                    value = deadline - time.monotonic()
                    if value <= 0:
                        raise TimeoutError("Live deadline expired")
                    return value

                def exchange(value):
                    nonlocal mutation_sent
                    sock.settimeout(remaining())
                    payload = encode(value, self.limits.request_bytes)
                    if value["action"] in MUTATIONS:
                        mutation_sent = True  # sendall can fail after a partial write
                    sock.sendall(payload)
                    while b"\n" not in buffer:
                        if len(buffer) >= self.limits.response_bytes:
                            raise DiaError(
                                "LIVE_LIMIT_EXCEEDED", "Live response exceeds byte limit"
                            )
                        sock.settimeout(remaining())
                        chunk = sock.recv(min(8192, self.limits.response_bytes - len(buffer)))
                        if not chunk:
                            raise DiaError(
                                "LIVE_BACKEND_UNAVAILABLE", "Dia closed the live connection"
                            )
                        buffer.extend(chunk)
                    line, _, rest = buffer.partition(b"\n")
                    buffer[:] = rest
                    result = decode(line, self.limits.response_bytes)
                    if (
                        type(result.get("protocol_version")) is not int
                        or result["protocol_version"] != VERSION
                    ):
                        raise DiaError("LIVE_PROTOCOL_MISMATCH", "Incompatible live response")
                    if "error" in result:
                        error = result["error"]
                        if not isinstance(error, dict) or not all(
                            isinstance(error.get(k), str) for k in ("code", "message")
                        ):
                            raise DiaError("LIVE_INVALID_RESPONSE", "Malformed live error")
                        raise DiaError(
                            error["code"],
                            error["message"],
                            outcome=error.get("outcome"),
                            details=error.get("details"),
                        )
                    if not isinstance(result.get("result"), dict):
                        raise DiaError("LIVE_INVALID_RESPONSE", "Malformed live result")
                    return result["result"]

                handshake = exchange({"protocol_version": VERSION, "action": "handshake"})
                if (
                    type(handshake.get("integration_api_version")) is not int
                    or handshake["integration_api_version"] != VERSION
                ):
                    raise DiaError("LIVE_PROTOCOL_MISMATCH", "Incompatible live integration API")
                if action == "handshake":
                    return handshake
                required = REQUIRED_CAPABILITY.get(action)
                capabilities = handshake.get("capabilities")
                if not isinstance(capabilities, list) or any(
                    not isinstance(c, str) for c in capabilities
                ):
                    raise DiaError(
                        "LIVE_INVALID_RESPONSE", "Malformed live capability advertisement"
                    )
                if required and required not in capabilities:
                    raise DiaError(
                        "UNSUPPORTED_LIVE_CAPABILITY",
                        f"GUI does not advertise {required}",
                        outcome="not_started",
                        details={"required_capability": required},
                    )
                return exchange(request)
        except DiaError as exc:
            if action in MUTATIONS and exc.outcome is None:
                raise transport_error(exc.code, str(exc)) from exc
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise transport_error("REQUEST_TIMEOUT", "Live request timed out") from exc
        except OSError as exc:
            raise transport_error(
                "LIVE_BACKEND_UNAVAILABLE", "Cannot connect to the configured Dia socket"
            ) from exc
