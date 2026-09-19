"""Nonblocking Unix IPC, bounded queue, and GLib main-context dispatch.

The I/O callbacks ONLY handle bytes and validated messages. Native reads happen
in a separate idle callback, one request per turn. No worker threads or locks.
"""

import atexit
import errno
import fcntl
import os
import socket
import stat
import struct
import time
from collections import deque
from pathlib import Path

from ..errors import DiaError
from .protocol import VERSION, Limits, decode, encode, validate


def runtime_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise DiaError(
            "LIVE_BACKEND_UNAVAILABLE", "XDG_RUNTIME_DIR is required for live integration"
        )
    private_directory(Path(runtime))
    directory = Path(runtime) / "dia-mcp"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / f"live-{os.getpid()}.sock"


def private_directory(directory):
    # Reject symlinks in every component, including the runtime directory itself.
    for part in (directory, *directory.parents):
        if part.is_symlink():
            raise DiaError(
                "LIVE_BACKEND_UNAVAILABLE", "Live socket directory must not use symlinks"
            )
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise DiaError("LIVE_BACKEND_UNAVAILABLE", "Live socket directory must be private (0700)")


class Listener:
    def __init__(self, glib, registry, path=None, limits=Limits()):
        self.glib, self.registry, self.limits = glib, registry, limits
        self.path = Path(path) if path is not None else runtime_path()
        private_directory(self.path.parent)
        self.clients = set()
        self.queue = deque()
        self.idle = None
        self.closed = False
        self.lock = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.sock = None
        self.inode = None
        self.source = self.timer = None
        try:
            info = os.fstat(self.lock)
            if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise DiaError("LIVE_BACKEND_UNAVAILABLE", "Unsafe live lock file")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists() or self.path.is_symlink():
                info = self.path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise DiaError(
                        "LIVE_BACKEND_UNAVAILABLE", "Refusing to remove non-socket endpoint"
                    )
                # An existing listener without our lock must also be preserved.
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(0.1)
                    try:
                        probe.connect(str(self.path))
                    except OSError as exc:
                        if exc.errno != errno.ECONNREFUSED:
                            raise
                    else:
                        raise DiaError(
                            "LIVE_BACKEND_UNAVAILABLE", "Live endpoint is already in use"
                        )
                self.path.unlink()
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.setblocking(False)
            self.sock.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self.inode = self.path.stat().st_ino
            self.sock.listen(limits.clients)
            self.source = glib.io_add_watch(self.sock.fileno(), glib.IO_IN, self._accept)
            self.timer = glib.timeout_add(100, self._expire)
            atexit.register(self.stop)
        except BaseException:
            self.stop()
            raise

    def _accept(self, fd, condition):
        try:
            sock, _ = self.sock.accept()
        except BlockingIOError:
            return True
        credentials = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", credentials)
        if uid != os.getuid() or len(self.clients) >= self.limits.clients:
            sock.close()
        else:
            self.clients.add(Connection(self, sock))
        return True

    def submit(self, client, request):
        if len(self.queue) >= self.limits.queue:
            client.respond(error=DiaError("LIVE_QUEUE_FULL", "Live read queue is full"))
            return
        self.queue.append((client, request, time.monotonic() + self.limits.timeout))
        if self.idle is None:
            self.idle = self.glib.idle_add(self._dispatch)

    def _dispatch(self):
        self.idle = None
        if self.closed or not self.queue:
            return False
        client, request, deadline = self.queue.popleft()
        if not client.closed:
            if time.monotonic() > deadline:
                client.respond(error=DiaError("REQUEST_TIMEOUT", "Queued live read expired"))
            else:
                try:
                    result = self.registry.dispatch(request)
                    if time.monotonic() > deadline:
                        raise DiaError("REQUEST_TIMEOUT", "Live read exceeded deadline")
                    client.respond(result=result)
                except DiaError as exc:
                    client.respond(error=exc)
                except Exception:
                    # Do not serialize native reprs or user data in error messages.
                    client.respond(
                        error=DiaError("LIVE_READ_FAILED", "Dia could not inspect this state")
                    )
        if self.queue and not self.closed:
            self.idle = self.glib.idle_add(self._dispatch)
        return False

    def _expire(self):
        now = time.monotonic()
        for client in tuple(self.clients):
            if now > client.deadline:
                client.close()
        return not self.closed

    def stop(self):
        if self.closed:
            return
        self.closed = True
        for source in (self.source, self.timer, self.idle):
            if source is not None:
                self.glib.source_remove(source)
        for client in tuple(self.clients):
            client.close()
        self.queue.clear()
        if self.sock:
            self.sock.close()
        if self.inode is not None:
            try:
                if self.path.lstat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
        os.close(self.lock)
        # Leave lock inode in place: unlinking it permits two simultaneous owners.
        atexit.unregister(self.stop)


class Connection:
    def __init__(self, server, sock):
        self.server, self.sock = server, sock
        self.sock.setblocking(False)
        self.input = bytearray()
        self.output = b""
        self.handshake = False
        self.pending = False
        self.closed = False
        self.close_after_write = False
        self.deadline = time.monotonic() + server.limits.timeout
        self.source = None
        self.watch(server.glib.IO_IN)

    def watch(self, condition):
        if self.source is not None:
            self.server.glib.source_remove(self.source)
        glib = self.server.glib
        self.source = glib.io_add_watch(
            self.sock.fileno(), condition | glib.IO_HUP | glib.IO_ERR, self.io
        )

    def io(self, fd, condition):
        glib = self.server.glib
        if condition & (glib.IO_HUP | glib.IO_ERR):
            self.close()
            return False
        try:
            if condition & glib.IO_OUT:
                sent = self.sock.send(self.output)
                self.output = self.output[sent:]
                if not self.output:
                    if self.close_after_write:
                        self.close()
                    else:
                        self.pending = False
                        self.deadline = time.monotonic() + self.server.limits.timeout
                        self.watch(glib.IO_IN)
                    return False
            elif condition & glib.IO_IN:
                chunk = self.sock.recv(8192)
                if not chunk:
                    self.close()
                    return False
                if self.pending:
                    self.close()  # pipelining is deliberately unsupported
                    return False
                self.input.extend(chunk)
                if len(self.input) > self.server.limits.request_bytes:
                    raise DiaError("LIVE_LIMIT_EXCEEDED", "Live request exceeds byte limit")
                if b"\n" in self.input:
                    line, _, extra = self.input.partition(b"\n")
                    self.input.clear()
                    if extra:
                        raise DiaError("INVALID_ARGUMENT", "Only one request may be outstanding")
                    request = validate(
                        decode(line, self.server.limits.request_bytes), self.server.limits
                    )
                    if not self.handshake and request["action"] != "handshake":
                        raise DiaError(
                            "LIVE_PROTOCOL_MISMATCH", "Handshake required before live reads"
                        )
                    self.handshake = True
                    self.pending = True
                    self.server.submit(self, request)
            return not self.closed
        except BlockingIOError:
            return True
        except DiaError as exc:
            self.close_after_write = True
            self.respond(error=exc)
            return False
        except OSError:
            self.close()
            return False

    def respond(self, result=None, error=None):
        if self.closed:
            return
        value = {"protocol_version": VERSION}
        if error:
            value["error"] = {"code": error.code, "message": str(error)}
        else:
            value["result"] = result
        try:
            self.output = encode(value, self.server.limits.response_bytes)
        except DiaError as exc:
            self.output = encode(
                {"protocol_version": VERSION, "error": {"code": exc.code, "message": str(exc)}},
                1024,
            )
        self.watch(self.server.glib.IO_OUT)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.source is not None:
            self.server.glib.source_remove(self.source)
            self.source = None
        self.sock.close()
        self.server.clients.discard(self)
        self.server.queue = deque(item for item in self.server.queue if item[0] is not self)
