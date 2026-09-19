"""One serialized snapshot per native Dia process; no GTK objects escape."""

import gzip
import json
import os
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .discovery import Catalog
from .errors import DiaError
from .models import Document, ExportFormat

FILTERS = {"dia": "dia", "svg": "svg", "png": "cairo-png"}


def validate_png(payload: bytes) -> None:
    """Check chunk CRCs and complete noninterlaced Cairo image data."""
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG signature")
    offset, chunks = 8, []
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        kind = payload[offset + 4 : offset + 8]
        data = payload[offset + 8 : offset + 8 + length]
        checksum = struct.unpack(">I", payload[offset + 8 + length : offset + 12 + length])[0]
        if zlib.crc32(kind + data) != checksum:
            raise ValueError("PNG checksum mismatch")
        chunks.append((kind, data))
        offset += length + 12
    if not chunks or chunks[0][0] != b"IHDR" or chunks[-1] != (b"IEND", b""):
        raise ValueError("incomplete PNG chunks")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    if not width or not height or width * height > 20_000_000:
        raise ValueError("PNG exceeds pixel limit")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if not channels or depth not in (1, 2, 4, 8, 16) or compression or filtering or interlace:
        raise ValueError("unsupported PNG encoding")
    row_size = (width * channels * depth + 7) // 8 + 1
    expected = row_size * height
    inflater = zlib.decompressobj()
    data = inflater.decompress(
        b"".join(data for kind, data in chunks if kind == b"IDAT"), expected + 1
    )
    if not inflater.eof or inflater.unused_data or len(data) != expected:
        raise ValueError("incomplete PNG image data")
    if any(data[i] > 4 for i in range(0, len(data), row_size)):
        raise ValueError("invalid PNG row filter")


class Backend(Protocol):
    def discover(self) -> Catalog: ...

    def render(self, document: Document, destination: Path, format: ExportFormat) -> dict: ...


def validate_artifact(path: Path, format: ExportFormat) -> None:
    """Validate new output, independently of Dia's process exit status."""
    try:
        payload = path.read_bytes()
        if not payload:
            raise ValueError("empty file")
        if format == "png":
            validate_png(payload)
        else:
            if payload[:2] == b"\x1f\x8b":
                payload = gzip.decompress(payload)
            root = ET.fromstring(payload)
            expected = (
                "{http://www.lysator.liu.se/~alla/dia/}diagram"
                if format == "dia"
                else "{http://www.w3.org/2000/svg}svg"
            )
            if root.tag != expected:
                raise ValueError("unexpected XML root")
    except (OSError, ValueError, ET.ParseError, EOFError, struct.error, zlib.error) as exc:
        raise DiaError(
            "EXPORT_FAILED", f"Dia did not produce a valid {format} file: {exc}"
        ) from exc


class NativeBackend:
    def __init__(self, executable: str = "dia", timeout: float = 30):
        self.executable = shutil.which(executable)
        if not self.executable:
            raise DiaError("BACKEND_UNAVAILABLE", f"Dia executable not found: {executable}")
        self.timeout = timeout

    def render(self, document: Document, destination: Path, format: ExportFormat) -> dict:
        with tempfile.TemporaryDirectory(prefix="dia-mcp-") as folder:
            job = Path(folder)
            request = job / "snapshot.diacmd"
            response = job / "response.json"
            output = job / f"output.{format}"
            request.write_text(document.model_dump_json(), encoding="utf-8")
            report = self._run(request, output, response, format)
            validate_artifact(output, format)
            shutil.copyfile(output, destination)
            return report["geometry"]

    def discover(self) -> Catalog:
        try:
            with tempfile.TemporaryDirectory(prefix="dia-mcp-catalog-") as folder:
                job = Path(folder)
                request = job / "request.diacatalog"
                request.write_text('{"api_version": "1"}', encoding="utf-8")
                report = self._run(request, job / "empty.dia", job / "response.json", "dia")
                try:
                    return Catalog.model_validate(report.get("catalog"))
                except ValidationError as exc:
                    raise DiaError("BACKEND_FAILED", "Invalid native catalog") from exc
        except OSError as exc:
            raise DiaError("IO_ERROR", str(exc)) from exc

    def _run(self, request: Path, output: Path, response: Path, format: ExportFormat) -> dict:
        env = os.environ.copy()
        # The embedded interpreter must not inherit the MCP virtualenv's modules.
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(key, None)
        env.update(
            {
                "DIA_PYTHON_PATH": str(Path(__file__).parent / "native"),
                "DIA_MCP_RESPONSE": str(response),
                "DIA_MCP_FORMAT": format,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "GSETTINGS_BACKEND": "memory",
            }
        )
        try:
            process = subprocess.run(
                [
                    self.executable,
                    "--export",
                    str(output),
                    "--filter",
                    FILTERS[format],
                    str(request),
                ],
                env=env,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DiaError("BACKEND_TIMEOUT", "Dia exceeded the operation timeout") from exc
        except OSError as exc:
            raise DiaError("BACKEND_UNAVAILABLE", str(exc)) from exc
        try:
            with response.open("rb") as stream:
                payload = stream.read(8 * 1024 * 1024 + 1)
            if len(payload) > 8 * 1024 * 1024:
                raise ValueError("native response exceeds 8 MiB")
            report = json.loads(payload)
            if not isinstance(report, dict) or type(report.get("ok")) is not bool:
                raise ValueError("invalid native response envelope")
        except OSError as exc:
            detail = process.stderr.decode("utf-8", errors="replace")[-2000:]
            raise DiaError("BACKEND_FAILED", f"Missing native response: {detail}") from exc
        except ValueError as exc:
            raise DiaError("BACKEND_FAILED", "Invalid or oversized native response") from exc
        if not report["ok"]:
            raise DiaError("BACKEND_FAILED", str(report.get("error", "Native import failed")))
        if process.returncode:
            detail = process.stderr.decode("utf-8", errors="replace")[-2000:]
            raise DiaError("EXPORT_FAILED", f"Dia exited {process.returncode}: {detail}")
        return report
