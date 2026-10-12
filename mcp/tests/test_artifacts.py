"""Reject corrupt output even when a native exporter reports success."""

import struct
import subprocess
import zlib

import pytest

from dia_mcp.backend import NativeBackend, validate_artifact
from dia_mcp.errors import DiaError
from dia_mcp.models import Document


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(image_data):
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(image_data))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    "payload", [b"", b"fake PNG", png(b""), png(b"\x05\x00\x00\x00"), png(b"\x00\x00\x00\x00")[:-1]]
)
def test_corrupt_png_rejected(tmp_path, payload):
    output = tmp_path / "corrupt.png"
    output.write_bytes(payload)
    with pytest.raises(DiaError) as caught:
        validate_artifact(output, "png")
    assert caught.value.code == "EXPORT_FAILED"


def test_complete_png_accepted_and_checksum_checked(tmp_path):
    output = tmp_path / "one-pixel.png"
    payload = bytearray(png(b"\x00\xff\xff\xff"))
    output.write_bytes(payload)
    validate_artifact(output, "png")
    payload[29] ^= 1
    output.write_bytes(payload)
    with pytest.raises(DiaError, match="checksum"):
        validate_artifact(output, "png")


@pytest.mark.parametrize("payload", [b"", b"<broken", b"<html/>"])
def test_invalid_svg_rejected(tmp_path, payload):
    output = tmp_path / "invalid.svg"
    output.write_bytes(payload)
    with pytest.raises(DiaError):
        validate_artifact(output, "svg")


def test_worker_timeout_has_stable_error_and_no_output(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("dia", 0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    backend = NativeBackend("/bin/true", timeout=0.01)
    with pytest.raises(DiaError) as caught:
        backend.render(Document(id="timeout", name="Timeout"), tmp_path / "out.dia", "dia")
    assert caught.value.code == "BACKEND_TIMEOUT"
    assert not (tmp_path / "out.dia").exists()
