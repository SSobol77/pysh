# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_config_paths.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for XDG declarative config path resolution."""
from __future__ import annotations

from pathlib import Path

from pysh.cli import main
from pysh.config.paths import (
    config_file_locations,
    dropin_config_paths,
    plugin_config_dir,
    plugin_config_path,
    plugin_config_paths,
    primary_config_path,
)
from pysh.config.runtime import DEFAULT_CONFIG_TOML, ensure_default_toml_config
from pysh.core.shell import PyShell


def test_primary_config_path_uses_xdg_config_home(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    assert primary_config_path(environ=env) == tmp_path / "xdg" / "pysh" / "config.toml"


def test_primary_config_path_falls_back_to_home_config(tmp_path: Path) -> None:
    assert primary_config_path(environ={}, home=tmp_path) == tmp_path / ".config" / "pysh" / "config.toml"


def test_dropins_are_lexically_ordered(tmp_path: Path) -> None:
    directory = tmp_path / "xdg" / "pysh" / "conf.d"
    directory.mkdir(parents=True)
    (directory / "20-b.toml").write_text("[prompt]\nsymbol='b'\n", encoding="utf-8")
    (directory / "10-a.toml").write_text("[prompt]\nsymbol='a'\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    assert [p.name for p in dropin_config_paths(environ=env)] == ["10-a.toml", "20-b.toml"]
    assert [p.name for p in config_file_locations(environ=env)] == [
        "config.toml",
        "10-a.toml",
        "20-b.toml",
    ]


def test_default_config_generation_does_not_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    assert ensure_default_toml_config(target) is True
    assert target.read_text(encoding="utf-8") == DEFAULT_CONFIG_TOML
    target.write_text("# user\n", encoding="utf-8")
    assert ensure_default_toml_config(target) is False
    assert target.read_text(encoding="utf-8") == "# user\n"


def test_pyshell_construction_does_not_create_default_toml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    PyShell()
    assert not (tmp_path / "pysh" / "config.toml").exists()


def test_dash_c_does_not_create_default_toml(tmp_path: Path, monkeypatch, capfd) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["-c", "echo ok"]) == 0
    assert "ok" in capfd.readouterr().out
    assert not (tmp_path / "pysh" / "config.toml").exists()


def test_version_does_not_create_default_toml(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "pysh " in capsys.readouterr().out
    assert not (tmp_path / "pysh" / "config.toml").exists()


def test_plugin_config_dir_uses_xdg_config_home(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    assert plugin_config_dir(environ=env) == tmp_path / "xdg" / "pysh" / "plugins"


def test_plugin_config_dir_fallback_to_home(tmp_path: Path) -> None:
    assert plugin_config_dir(environ={}, home=tmp_path) == tmp_path / ".config" / "pysh" / "plugins"


def test_plugin_config_path_resolver(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert plugin_config_path("myplugin", environ=env) == tmp_path / "pysh" / "plugins" / "myplugin.toml"


def test_plugin_config_paths_missing_dir_is_empty(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}
    assert plugin_config_paths(environ=env) == ()


def test_plugin_config_paths_lexical_order(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "pysh" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "zzz.toml").write_text("[settings]\n", encoding="utf-8")
    (plugin_dir / "aaa.toml").write_text("[settings]\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert [p.name for p in plugin_config_paths(environ=env)] == ["aaa.toml", "zzz.toml"]
