"""Private disposable homes only; no workstation configuration is touched."""

import json
import os
import stat

import pytest

from dia_mcp.config import (
    ConfigError,
    config_path,
    defaults,
    effective_config,
    load_config,
    save_config,
)
from dia_mcp.config_ui import main, status


@pytest.fixture
def env(tmp_path, monkeypatch):
    values = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "config")}
    for name in ("DIA_MCP_LIVE", "DIA_MCP_WRITE", "DIA_MCP_FILES_ROOT", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_default_off_without_creating_config_or_importing_native(env):
    assert load_config(env=env) == defaults()
    assert effective_config(env)["mode"] == "off"
    assert not config_path(env).exists()
    from dia_mcp.live.plugin import enable

    enable()  # portable process has no dia or gi module
    assert not config_path(env).exists()


def test_atomic_private_round_trip_and_explicit_root(env, tmp_path):
    wanted = {"schema_version": 1, "mode": "read-write", "files_root": str(tmp_path)}
    save_config(wanted, env=env)
    path = config_path(env)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert load_config(env=env) == wanted
    before = path.stat().st_ino
    save_config({**wanted, "mode": "off"}, env=env)
    assert path.stat().st_ino != before
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("mode", "write"),
        ("mode", []),
        ("files_root", "relative"),
        ("files_root", "/not-existing-dia-mcp-root"),
    ],
)
def test_invalid_configuration_cannot_be_saved(env, field, value):
    with pytest.raises(ConfigError):
        save_config({**defaults(), field: value}, env=env)
    assert not config_path(env).exists()


def test_symlink_roots_and_parent_traversal_are_rejected(env, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    for root in (str(link), str(tmp_path / "child/..")):
        with pytest.raises(ConfigError):
            save_config({**defaults(), "files_root": root}, env=env)


def test_config_file_symlink_cannot_be_read_or_replaced(env, tmp_path):
    save_config(defaults(), env=env)
    path = config_path(env)
    path.unlink()
    target = tmp_path / "do-not-modify"
    target.write_text("original")
    path.symlink_to(target)
    with pytest.raises(ConfigError):
        load_config(env=env)
    with pytest.raises(ConfigError):
        save_config(defaults(), env=env)
    assert target.read_text() == "original" and path.is_symlink()


def test_symlink_directory_and_public_permissions_fail_closed(env, tmp_path):
    save_config(defaults(), env=env)
    path = config_path(env)
    path.chmod(0o644)
    with pytest.raises(ConfigError, match="0600"):
        load_config(env=env)
    path.chmod(0o600)
    path.parent.chmod(0o755)
    with pytest.raises(ConfigError, match="0700"):
        load_config(env=env)
    path.parent.chmod(0o700)
    moved = path.parent.with_name("moved")
    path.parent.rename(moved)
    path.parent.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ConfigError):
        load_config(env=env)


@pytest.mark.parametrize(
    "payload",
    [
        "not JSON",
        '{"schema_version":1,"mode":"off","mode":"read-write","files_root":null}',
        '{"schema_version":1,"mode":"off","files_root":null,"extra":true}',
        "x" * 16385,
        "[" * 2000 + "]" * 2000,
    ],
)
def test_malformed_config_is_explicit_and_never_enables_plugin(env, capsys, payload):
    save_config(defaults(), env=env)
    config_path(env).write_text(payload)
    with pytest.raises(ConfigError):
        effective_config(env)
    from dia_mcp.live.plugin import enable

    enable()
    assert "integration disabled" in capsys.readouterr().err


def test_environment_disable_is_authoritative_even_over_bad_config(env):
    save_config(defaults(), env=env)
    config_path(env).write_text("broken")
    assert effective_config({**env, "DIA_MCP_LIVE": "0", "DIA_MCP_WRITE": "1"})["mode"] == "off"


@pytest.mark.parametrize(
    "stored,override,expected",
    [
        ("off", {"DIA_MCP_WRITE": "1"}, "off"),
        ("off", {"DIA_MCP_LIVE": "1"}, "read-only"),
        ("off", {"DIA_MCP_LIVE": "1", "DIA_MCP_WRITE": "1"}, "read-write"),
        ("read-write", {}, "read-write"),
        ("read-write", {"DIA_MCP_WRITE": "0"}, "read-only"),
        ("read-write", {"DIA_MCP_LIVE": "1"}, "read-only"),
        ("read-only", {"DIA_MCP_WRITE": "1"}, "read-write"),
        ("read-write", {"DIA_MCP_LIVE": "0"}, "off"),
    ],
)
def test_legacy_environment_precedence(env, stored, override, expected):
    save_config({**defaults(), "mode": stored}, env=env)
    assert effective_config({**env, **override})["mode"] == expected


def test_invalid_env_and_explicit_cleared_root(env, tmp_path):
    save_config({**defaults(), "files_root": str(tmp_path)}, env=env)
    assert effective_config({**env, "DIA_MCP_FILES_ROOT": ""})["files_root"] is None
    with pytest.raises(ConfigError):
        effective_config({**env, "DIA_MCP_WRITE": "yes"})
    with pytest.raises(ConfigError):
        config_path({"XDG_CONFIG_HOME": "relative"})


def test_failed_atomic_publication_preserves_old_config_and_cleans_temporary(env, monkeypatch):
    save_config(defaults(), env=env)
    path = config_path(env)
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("injected before publication")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ConfigError):
        save_config({**defaults(), "mode": "read-write"}, env=env)
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_cli_persists_then_reports_restart_without_starting_a_process(env, tmp_path, capsys):
    assert main(["--mode", "read-only", "--files-root", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["desired"]["mode"] == "read-only"
    assert output["effective"]["files_root"] == str(tmp_path)
    assert output["restart_required"] and output["running"]["endpoints"] == []
    assert main(["--mode", "off", "--clear-files-root"]) == 0
    assert load_config(env=env) == defaults()
    capsys.readouterr()
    before = config_path(env).read_bytes()
    assert main(["--status"]) == 0
    assert config_path(env).read_bytes() == before


def test_status_uses_observed_config_not_just_socket_existence(env, monkeypatch):
    save_config({**defaults(), "mode": "read-write"}, env=env)
    observed = {
        "endpoints": [
            {
                "path": "/private/live-1.sock",
                "status": "running",
                "mode": "read-only",
                "files_root": None,
                "files_root_known": True,
            }
        ],
        "truncated": False,
    }
    monkeypatch.setattr("dia_mcp.config_ui.running_status", lambda _: observed)
    assert status(env)["restart_required"]
    observed["endpoints"][0]["mode"] = "read-write"
    assert not status(env)["restart_required"]


def test_cli_bad_config_reports_error_and_does_not_mutate(env, capsys):
    save_config(defaults(), env=env)
    config_path(env).write_text("malformed")
    assert main(["--status"]) == 2
    assert json.loads(capsys.readouterr().err)["settings_published"] is False
    assert config_path(env).read_text() == "malformed"


def test_non_utf8_configuration_and_surrogate_paths_fail_closed(env):
    save_config(defaults(), env=env)
    config_path(env).write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(ConfigError):
        load_config(env=env)
    with pytest.raises(ConfigError, match="UTF-8"):
        save_config({**defaults(), "files_root": "/tmp/bad\ud800"}, env=env)
    with pytest.raises(ConfigError, match="UTF-8"):
        config_path({"XDG_CONFIG_HOME": "/tmp/bad\ud800"})


def test_rejected_configuration_does_not_claim_previous_write_mode_is_off(env, capsys):
    save_config({**defaults(), "mode": "read-write"}, env=env)
    assert main(["--mode", "read-only", "--files-root", "/missing-dia-config-root"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "effective_mode" not in error
    assert load_config(env=env)["mode"] == "read-write"


def test_postpublication_sync_error_reports_saved_configuration(env, monkeypatch, capsys):
    save_config(defaults(), env=env)
    original = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory sync failure")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    assert main(["--mode", "read-write"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["settings_published"] is True
    assert error["running_sessions_changed"] is False
    assert "effective_mode" not in error
    assert load_config(env=env)["mode"] == "read-write"
