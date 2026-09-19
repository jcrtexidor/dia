"""Native file adapter. Called synchronously on the GTK thread.

The configured root is a local operator trust boundary. Symlinks in requested
paths are refused. Atomic publication uses pinned directory descriptors on Linux.
Native open uses the logical path after validation: concurrent hostile directory
renames during import are outside this local trusted-root guarantee.
Native importers may read diagram-referenced resources; dependencies report that
fact conservatively and do not claim a sandbox for arbitrary native plugins.
"""

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from ..errors import DiaError


class NativeFiles:
    def __init__(self, dia, root=None):
        self.dia = dia
        configured = root if root is not None else os.environ.get("DIA_MCP_FILES_ROOT")
        self.root = Path(os.path.abspath(configured)) if configured else None

    @contextmanager
    def _parent(self, path):
        if self.root is None:
            raise DiaError("LIVE_FILES_DISABLED", "Configure DIA_MCP_FILES_ROOT locally")
        candidate = Path(path)
        if ".." in candidate.parts:
            raise DiaError("INVALID_PATH", "Parent traversal is not allowed")
        candidate = candidate if candidate.is_absolute() else self.root / candidate
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            raise DiaError("INVALID_PATH", "Path is outside the configured root") from None
        if not relative.parts:
            raise DiaError("INVALID_PATH", "A file name is required")
        # Walk even the configured root without following links.
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in candidate.parent.parts[1:]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            try:
                info = os.stat(candidate.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                info = None
            if info is not None and not stat.S_ISREG(info.st_mode):
                raise DiaError("INVALID_PATH", "Target must be a regular file, not a link")
            yield fd, candidate, info
        except OSError as exc:
            raise DiaError("FILE_IO_ERROR", str(exc)) from exc
        finally:
            os.close(fd)

    def open(self, request):
        with self._parent(request["path"]) as (_, path, info):
            if info is None:
                raise DiaError("FILE_NOT_FOUND", "Diagram does not exist")
            if path.suffix.lower() != ".dia":
                raise DiaError("INVALID_PATH", "Native open requires a .dia file")
            return self.dia.live_file("open", None, str(path), "dia", str(path))

    def write(self, doc, request):
        action = request["action"]
        exporting = action == "export_document"
        fmt = request.get("format", "dia") if exporting else "dia"
        if fmt not in {"dia", "svg", "png"}:
            raise DiaError("INVALID_FORMAT", "Supported formats are dia, svg, png")
        path = doc.filename if action == "save_document" else request["path"]
        overwrite = request.get("overwrite", False)
        if type(overwrite) is not bool:
            raise DiaError("INVALID_ARGUMENT", "overwrite must be a boolean")
        with self._parent(path) as (fd, destination, info):
            if destination.suffix.lower() != f".{fmt}":
                raise DiaError("INVALID_PATH", "File extension must match format")
            if info is not None and not overwrite:
                raise DiaError("FILE_EXISTS", "Explicit overwrite=true is required")
            temporary = f".dia-live-{uuid4().hex}.{fmt}"
            stage = f"/proc/self/fd/{fd}/{temporary}"
            stage_fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=fd)
            os.close(stage_fd)
            try:
                self.dia.live_file("stage", doc, stage, fmt, str(destination))
                stage_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    staged = os.fstat(stage_fd)
                    if not stat.S_ISREG(staged.st_mode) or staged.st_size == 0:
                        raise DiaError(
                            "FILE_IO_ERROR", "Serializer did not produce a nonempty file"
                        )
                    os.fsync(stage_fd)
                finally:
                    os.close(stage_fd)
                if overwrite:
                    os.replace(temporary, destination.name, src_dir_fd=fd, dst_dir_fd=fd)
                else:
                    # link publication fails atomically if another writer won the name.
                    os.link(
                        temporary,
                        destination.name,
                        src_dir_fd=fd,
                        dst_dir_fd=fd,
                        follow_symlinks=False,
                    )
            finally:
                for leftover in (temporary, temporary + "~"):
                    try:
                        os.unlink(leftover, dir_fd=fd)
                    except OSError:
                        # Cleanup cannot turn a published file into a failed save.
                        pass
            # Publication is complete: only now change filename/undo saved marker.
            if not exporting:
                self.dia.live_file("commit", doc, str(destination), fmt, str(destination))
            durable = True
            try:
                os.fsync(fd)
            except OSError:
                durable = False
            return {
                "path": str(destination),
                "format": fmt,
                "published": True,
                "directory_synced": durable,
                "saved": not exporting,
            }

    def dependencies(self, objects, limit=256):
        items = []
        truncated = False
        for oid, entry in objects.items():
            obj = entry[0]
            for descriptor in obj.property_descriptors(256)["items"]:
                if descriptor["type"] != "file":
                    continue
                if len(items) >= limit:
                    truncated = True
                    break
                try:
                    value = obj.properties[descriptor["name"]].value
                except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
                    continue
                if isinstance(value, str) and value:
                    # Metadata only; never open or stat arbitrary external resources.
                    items.append(
                        {
                            "object_id": oid,
                            "property": descriptor["name"],
                            "path": value[:2048],
                            "exists": None,
                        }
                    )
        return {
            "items": items,
            "truncated": truncated,
            "complete": False,
            "semantics": (
                "Declared file properties only; existence not probed; "
                "native plugins may have other dependencies"
            ),
        }
