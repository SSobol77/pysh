# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_project_local.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for project-local Plugin API safety policy."""
from __future__ import annotations

from pathlib import Path

from pysh.plugins.manager import PluginManager


def test_project_plugins_warn_and_do_not_load_by_default(tmp_path: Path, capsys) -> None:
    project_dir = tmp_path / ".pysh" / "plugins"
    project_dir.mkdir(parents=True)
    _write_project_plugin(project_dir / "local.py")
    manager = PluginManager(
        builtin_names=frozenset(),
        user_plugin_dir=tmp_path / "user",
        project_plugin_dir=project_dir,
    )
    manager.enable_plugin("local")

    manager.discover_and_load()

    assert not manager.has_command("localcmd")
    assert "not loaded; use shell.enable_project_plugins() to enable" in capsys.readouterr().err


def test_project_plugin_enabled_by_name_but_not_project_opt_in_is_not_imported(
    tmp_path: Path,
    capsys,
) -> None:
    marker = tmp_path / "marker"
    project_dir = tmp_path / ".pysh" / "plugins"
    project_dir.mkdir(parents=True)
    _write_project_plugin_with_import_marker(project_dir / "local.py", marker)
    manager = PluginManager(
        builtin_names=frozenset(),
        user_plugin_dir=tmp_path / "user",
        project_plugin_dir=project_dir,
    )
    manager.enable_plugin("local")

    manager.discover_and_load()

    assert not marker.exists()
    assert manager.has_command("localcmd") is False
    assert "not loaded; use shell.enable_project_plugins() to enable" in capsys.readouterr().err


def test_project_plugins_load_only_after_opt_in(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pysh" / "plugins"
    project_dir.mkdir(parents=True)
    _write_project_plugin(project_dir / "local.py")
    manager = PluginManager(
        builtin_names=frozenset(),
        user_plugin_dir=tmp_path / "user",
        project_plugin_dir=project_dir,
    )
    manager.enable_plugin("local")
    manager.enable_project_plugins()

    manager.discover_and_load()

    assert manager.has_command("localcmd")


def test_project_plugin_imports_only_after_project_and_name_opt_in(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    project_dir = tmp_path / ".pysh" / "plugins"
    project_dir.mkdir(parents=True)
    _write_project_plugin_with_import_marker(project_dir / "local.py", marker)
    manager = PluginManager(
        builtin_names=frozenset(),
        user_plugin_dir=tmp_path / "user",
        project_plugin_dir=project_dir,
    )
    manager.enable_project_plugins()
    manager.enable_plugin("local")

    manager.discover_and_load()

    assert marker.read_text(encoding="utf-8") == "imported"
    assert manager.has_command("localcmd")


def _write_project_plugin(path: Path) -> None:
    path.write_text(
        """
class LocalPlugin:
    name = "local"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("localcmd", self.localcmd)

    def localcmd(self, argv):
        return 0
""".lstrip(),
        encoding="utf-8",
    )


def _write_project_plugin_with_import_marker(path: Path, marker: Path) -> None:
    path.write_text(
        f"""
from pathlib import Path

Path({str(marker)!r}).write_text("imported", encoding="utf-8")

class LocalPlugin:
    name = "local"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("localcmd", self.localcmd)

    def localcmd(self, argv):
        return 0
""".lstrip(),
        encoding="utf-8",
    )
