# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_config.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for plugin TOML configuration loading and validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from pysh.config.paths import plugin_config_dir, plugin_config_path, plugin_config_paths
from pysh.config.runtime import load_plugin_configs
from pysh.config.schema import load_plugin_config, validate_plugin_name
from pysh.core.shell import PyShell

# ---------------------------------------------------------------------------
# Plugin name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "example",
        "my-plugin",
        "my_plugin",
        "plugin.v2",
        "plugin123",
        "a",
    ],
)
def test_validate_plugin_name_accepts_safe_names(name: str) -> None:
    assert validate_plugin_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "MyPlugin",
        "UPPER",
        ".hidden",
        "-starts-dash",
        "_starts_underscore",
        "has space",
        "path/sep",
        "path\\sep",
        "../traversal",
    ],
)
def test_validate_plugin_name_rejects_unsafe_names(name: str) -> None:
    assert validate_plugin_name(name) is False


# ---------------------------------------------------------------------------
# Plugin config path resolution
# ---------------------------------------------------------------------------


def test_plugin_config_dir_uses_xdg_config_home(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    expected = tmp_path / "xdg" / "pysh" / "plugins"
    assert plugin_config_dir(environ=env) == expected


def test_plugin_config_dir_fallback_to_home(tmp_path: Path) -> None:
    expected = tmp_path / ".config" / "pysh" / "plugins"
    assert plugin_config_dir(environ={}, home=tmp_path) == expected


def test_plugin_config_path_resolver(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    expected = tmp_path / "pysh" / "plugins" / "myplugin.toml"
    assert plugin_config_path("myplugin", environ=env) == expected


def test_plugin_config_paths_missing_dir_returns_empty(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}
    assert plugin_config_paths(environ=env) == ()


def test_plugin_config_paths_lexical_order(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "beta.toml").write_text("[plugin]\nname = 'beta'\n", encoding="utf-8")
    (plugin_dir / "alpha.toml").write_text("[plugin]\nname = 'alpha'\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    paths = plugin_config_paths(environ=env)
    assert [p.name for p in paths] == ["alpha.toml", "beta.toml"]


def test_plugin_config_paths_skips_non_toml_files(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "myplugin.toml").write_text("[settings]\nfoo = 1\n", encoding="utf-8")
    (plugin_dir / "not-toml.txt").write_text("ignored\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    paths = plugin_config_paths(environ=env)
    assert len(paths) == 1
    assert paths[0].name == "myplugin.toml"


# ---------------------------------------------------------------------------
# load_plugin_config: single-file loading
# ---------------------------------------------------------------------------


def test_load_plugin_config_missing_file_returns_empty_data(tmp_path: Path) -> None:
    path = tmp_path / "nothere.toml"
    pc = load_plugin_config(path)
    assert pc is not None
    assert pc.name == "nothere"
    assert pc.data == {}
    assert pc.diagnostics == ()


def test_load_plugin_config_valid_toml_loads_as_data(tmp_path: Path) -> None:
    path = tmp_path / "example.toml"
    path.write_text(
        "[plugin]\nname = 'example'\n\n[settings]\nenabled_feature = true\nmode = 'safe'\n",
        encoding="utf-8",
    )
    pc = load_plugin_config(path)
    assert pc is not None
    assert pc.name == "example"
    assert pc.data["settings"]["enabled_feature"] is True
    assert pc.data["settings"]["mode"] == "safe"
    assert pc.diagnostics == ()


def test_load_plugin_config_no_plugin_section_loads_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "myplugin.toml"
    path.write_text("[settings]\nfoo = 42\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    assert pc.name == "myplugin"
    assert pc.data["settings"]["foo"] == 42
    assert pc.diagnostics == ()


def test_load_plugin_config_name_mismatch_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "actual.toml"
    path.write_text("[plugin]\nname = 'different'\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    reasons = [d.reason for d in pc.diagnostics]
    assert any("does not match file stem" in r for r in reasons)


def test_load_plugin_config_invalid_toml_produces_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[invalid\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    assert pc.data == {}
    assert len(pc.diagnostics) >= 1
    assert any("invalid TOML" in d.reason for d in pc.diagnostics)


def test_load_plugin_config_unsafe_name_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "UPPER.toml"
    pc = load_plugin_config(path)
    assert pc is None


def test_load_plugin_config_plugin_section_not_table_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "myplugin.toml"
    path.write_text("plugin = 'not-a-table'\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    reasons = [d.reason for d in pc.diagnostics]
    assert any("plugin section must be a table" in r for r in reasons)


def test_load_plugin_config_plugin_name_not_string_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "myplugin.toml"
    path.write_text("[plugin]\nname = 42\n", encoding="utf-8")
    pc = load_plugin_config(path)
    assert pc is not None
    reasons = [d.reason for d in pc.diagnostics]
    assert any("plugin name must be a string" in r for r in reasons)


def test_load_plugin_config_size_guard(tmp_path: Path) -> None:
    path = tmp_path / "big.toml"
    path.write_text("x = 1\n" * 100, encoding="utf-8")
    pc = load_plugin_config(path, max_bytes=10)
    assert pc is not None
    assert any("exceeds" in d.reason for d in pc.diagnostics)


# ---------------------------------------------------------------------------
# load_plugin_configs: multi-file orchestration
# ---------------------------------------------------------------------------


def test_load_plugin_configs_empty_dir_returns_empty(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "empty")}
    configs = load_plugin_configs(environ=env)
    assert configs == {}


def test_load_plugin_configs_loads_valid_files(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "alpha.toml").write_text(
        "[settings]\nmode = 'fast'\n", encoding="utf-8"
    )
    (plugin_dir / "beta.toml").write_text(
        "[settings]\nmode = 'slow'\n", encoding="utf-8"
    )
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    configs = load_plugin_configs(environ=env)
    assert "alpha" in configs
    assert "beta" in configs
    assert configs["alpha"].data["settings"]["mode"] == "fast"


def test_load_plugin_configs_skips_unsafe_filenames(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "UNSAFE.toml").write_text("[settings]\nx = 1\n", encoding="utf-8")
    (plugin_dir / "safe.toml").write_text("[settings]\nx = 2\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    configs = load_plugin_configs(environ=env)
    assert "UNSAFE" not in configs
    assert "safe" in configs
    err = capsys.readouterr().err
    assert "unsafe plugin config filename" in err


def test_load_plugin_configs_invalid_toml_does_not_crash(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "broken.toml").write_text("[invalid\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    configs = load_plugin_configs(environ=env)
    # Broken config is loaded (with diagnostics) but the shell doesn't crash
    assert "broken" in configs
    assert configs["broken"].data == {}
    err = capsys.readouterr().err
    assert "invalid TOML" in err


# ---------------------------------------------------------------------------
# PyShell.get_plugin_config
# ---------------------------------------------------------------------------


def test_pyshell_plugin_configs_defaults_empty() -> None:
    shell = PyShell()
    assert shell.plugin_configs == {}


def test_pyshell_get_plugin_config_returns_empty_for_unknown() -> None:
    shell = PyShell()
    result = shell.get_plugin_config("nonexistent")
    assert result == {}


def test_pyshell_get_plugin_config_returns_copy(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "myplugin.toml").write_text("[settings]\nfoo = 1\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from pysh.config.runtime import load_plugin_configs as _load
    shell = PyShell()
    cfgs = _load()
    shell.plugin_configs = {name: dict(pc.data) for name, pc in cfgs.items()}

    result = shell.get_plugin_config("myplugin")
    assert result == {"settings": {"foo": 1}}
    # Mutating the returned copy must not affect internal state
    result["injected"] = "bad"
    assert "injected" not in shell.get_plugin_config("myplugin")


def test_pyshell_get_plugin_config_does_not_execute_toml(tmp_path: Path, monkeypatch) -> None:
    """Plugin TOML must not trigger any execution of Python or shell code."""
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    marker = tmp_path / "executed_marker"
    # Write TOML that looks dangerous but is pure data
    (plugin_dir / "evil.toml").write_text(
        f"[settings]\ncmd = 'touch {marker}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from pysh.config.runtime import load_plugin_configs as _load
    shell = PyShell()
    cfgs = _load()
    shell.plugin_configs = {name: dict(pc.data) for name, pc in cfgs.items()}

    cfg = shell.get_plugin_config("evil")
    assert cfg["settings"]["cmd"] == f"touch {marker}"
    # The marker must not have been created — the value is data, not executed
    assert not marker.exists()


def test_plugin_config_does_not_enable_or_load_plugins(tmp_path: Path, monkeypatch) -> None:
    """Presence of a plugin TOML file must not enable or import the plugin."""
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "myplugin.toml").write_text("[settings]\nfoo = 1\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    shell = PyShell()
    # Plugin must not be enabled just because a config file exists
    assert not shell.is_plugin_enabled("myplugin")
    # Plugin must not appear in loaded plugin commands
    assert "myplugin" not in shell.plugin_manager.command_names()


# ---------------------------------------------------------------------------
# config_check --locations includes plugin config files
# ---------------------------------------------------------------------------


def test_config_check_locations_includes_plugin_files(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "myplug.toml").write_text("[settings]\nfoo = 1\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    shell = PyShell()
    rc = shell._dispatch_builtin(["config_check", "--locations"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "plugin:" in out
    assert "myplug.toml" in out


def test_config_check_validate_with_valid_plugin_config(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "goodplugin.toml").write_text(
        "[plugin]\nname = 'goodplugin'\n[settings]\nenabled = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    shell = PyShell()
    rc = shell._dispatch_builtin(["config_check", "--validate"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pysh: config: valid" in out
