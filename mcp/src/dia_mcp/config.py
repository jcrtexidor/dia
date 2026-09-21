"""Private per-user configuration; importing this module starts no integration."""

import json
import os
import stat
from pathlib import Path
from uuid import uuid4

MODES = ("off", "read-only", "read-write")
MAX_CONFIG_BYTES = 16384


class ConfigError(ValueError):
    """Invalid or unsafe local configuration; callers must fail closed."""

    def __init__(self, message, *, published=False):
        super().__init__(message)
        self.published = published


def defaults():
    return {"schema_version": 1, "mode": "off", "files_root": None}


def config_path(env=None):
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    try:
        str(base).encode("utf-8")
    except UnicodeError as exc:
        raise ConfigError("Configuration path must be valid UTF-8") from exc
    if not Path(base).is_absolute():
        raise ConfigError("XDG_CONFIG_HOME must be an absolute path")
    return Path(base) / "dia-mcp" / "config.json"


def _directory(path, create=False, private=False):
    path = Path(path)
    try:
        str(path).encode("utf-8")
    except UnicodeError as exc:
        raise ConfigError("Directory paths must be valid UTF-8") from exc
    if not path.is_absolute() or ".." in path.parts:
        raise ConfigError("Configuration and resource directories must be absolute without '..'")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if private:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ConfigError(
                    "Configuration directory must be owned by this user with mode 0700"
                )
        return fd
    except BaseException:
        os.close(fd)
        raise


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "mode", "files_root"}:
        raise ConfigError("Configuration requires schema_version, mode and files_root only")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ConfigError("Unsupported configuration schema_version")
    if not isinstance(value["mode"], str) or value["mode"] not in MODES:
        raise ConfigError("Mode must be off, read-only or read-write")
    root = value["files_root"]
    if root is not None:
        if not isinstance(root, str) or not root or len(root) > 4096 or "\0" in root:
            raise ConfigError("files_root must be an existing absolute directory or null")
        try:
            fd = _directory(root)
            os.close(fd)
        except OSError as exc:
            raise ConfigError("files_root must exist and must not traverse symlinks") from exc
    return dict(value)


def _check_file(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ConfigError("Configuration must be a regular file owned by this user with mode 0600")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("Duplicate configuration field: " + key)
        result[key] = value
    return result


def load_config(path=None, *, env=None):
    path = config_path(env) if path is None else Path(path)
    try:
        try:
            directory = _directory(path.parent, private=True)
        except FileNotFoundError:
            return defaults()
        try:
            try:
                fd = os.open(
                    path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
            except FileNotFoundError:
                return defaults()
            with os.fdopen(fd, "rb") as stream:
                _check_file(os.fstat(stream.fileno()))
                data = stream.read(MAX_CONFIG_BYTES + 1)
        finally:
            os.close(directory)
        if len(data) > MAX_CONFIG_BYTES:
            raise ConfigError("Configuration exceeds 16384 bytes")
        return validate_config(json.loads(data, object_pairs_hook=_unique_object))
    except ConfigError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise ConfigError("Cannot read private configuration: " + str(exc)) from exc


def save_config(value, path=None, *, env=None):
    value = validate_config(value)
    path = config_path(env) if path is None else Path(path)
    directory, temporary = None, ".config-" + uuid4().hex + ".tmp"
    published = False
    try:
        directory = _directory(path.parent, create=True, private=True)
        try:
            _check_file(os.stat(path.name, dir_fd=directory, follow_symlinks=False))
        except FileNotFoundError:
            pass
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        published = True
        os.fsync(directory)
    except ConfigError:
        raise
    except OSError as exc:
        message = (
            "Configuration published, but directory sync failed; inspect --status: "
            if published
            else "Cannot save private configuration: "
        )
        raise ConfigError(message + str(exc), published=published) from exc
    finally:
        if directory is not None:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)
    return value


def effective_config(env=None, path=None):
    """Legacy explicit disable wins; WRITE alone cannot activate an off installation."""
    env = os.environ if env is None else env
    if env.get("DIA_MCP_LIVE") == "0":
        return {**defaults(), "source": "environment_disable"}
    config = load_config(path, env=env)
    live, write = env.get("DIA_MCP_LIVE"), env.get("DIA_MCP_WRITE")
    if live not in (None, "0", "1") or write not in (None, "0", "1"):
        raise ConfigError("DIA_MCP_LIVE and DIA_MCP_WRITE must be 0 or 1 when set")
    if live == "1":
        config["mode"] = "read-write" if write == "1" else "read-only"
    elif config["mode"] != "off" and write is not None:
        config["mode"] = "read-write" if write == "1" else "read-only"
    if "DIA_MCP_FILES_ROOT" in env:
        config["files_root"] = env["DIA_MCP_FILES_ROOT"] or None
    config = validate_config(config)
    config["source"] = (
        "environment"
        if any(name in env for name in ("DIA_MCP_LIVE", "DIA_MCP_WRITE", "DIA_MCP_FILES_ROOT"))
        else "configuration"
    )
    return config
