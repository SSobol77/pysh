# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_loader.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for controlled Plugin API loading."""
from __future__ import annotations

from pathlib import Path

from pysh.plugins.manager import PluginManager


def test_loader_loads_enabled_plugin_and_continues_after_failure(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(user_dir / "bad.py", "raise RuntimeError('boom')\n")
    _write_plugin(
        user_dir / "good.py",
        """
class GoodPlugin:
    name = "good"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("hello", self.hello)

    def hello(self, argv):
        print("hello")
        return 0
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")
    manager.enable_plugin("good")

    manager.discover_and_load()

    assert manager.has_command("hello")


def test_loader_rejects_ambiguous_plugin_classes(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "ambig.py",
        """
class A:
    name = "ambig"
    version = "0.1.0"
    api_version = (1, 0)
    def register(self, api):
        pass

class B:
    name = "ambig"
    version = "0.1.0"
    api_version = (1, 0)
    def register(self, api):
        pass
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("ambig")

    manager.discover_and_load()

    assert not manager.has_command("ambig")


def test_loader_rejects_invalid_metadata(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "badmeta.py",
        """
class BadPlugin:
    name = "badmeta"
    version = ""
    api_version = (1, 0)
    def register(self, api):
        pass
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("badmeta")

    manager.discover_and_load()

    assert manager.command_names() == ()


def test_disabled_user_plugin_is_discovered_but_not_imported(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "disabled.py",
        f"""
from pathlib import Path

Path({str(marker)!r}).write_text("imported", encoding="utf-8")

class DisabledPlugin:
    name = "disabled"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("disabledcmd", lambda argv: 0)
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)

    manager.discover_and_load()

    assert not marker.exists()
    assert manager.has_command("disabledcmd") is False


def test_failed_plugin_registration_does_not_leave_command(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "bad.py",
        """
class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("leak", self.leak)
        api.on_startup(lambda: None)
        raise RuntimeError("boom")

    def leak(self, argv):
        return 0
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")

    manager.discover_and_load()

    assert manager.has_command("leak") is False
    assert manager.command_names() == ()


def test_failed_plugin_registration_does_not_leave_completer(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "bad.py",
        """
class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_completer("leak", lambda args, cursor: ["leaked"])
        raise RuntimeError("boom")
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")

    manager.discover_and_load()

    assert manager.complete_command("leak", [], 0) == []


def test_failed_plugin_registration_does_not_leave_prompt_segment(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "bad.py",
        """
class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_prompt_segment("leak", lambda: "LEAK", position="end")
        raise RuntimeError("boom")
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")

    manager.discover_and_load()

    assert manager.prompt_segments("end") == []


def test_failed_plugin_registration_does_not_leave_lifecycle_hooks(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    marker_text = str(marker)
    _write_plugin(
        user_dir / "bad.py",
        f"""
from pathlib import Path

MARKER = Path({marker_text!r})

class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.on_startup(lambda: MARKER.write_text("startup", encoding="utf-8"))
        api.on_shutdown(lambda: MARKER.write_text("shutdown", encoding="utf-8"))
        api.on_env_change(lambda name, old, new: MARKER.write_text("env", encoding="utf-8"))
        raise RuntimeError("boom")
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")

    manager.discover_and_load()
    manager.run_startup_hooks()
    manager.notify_env_change("X", None, "1")
    manager.run_shutdown_hooks()

    assert not marker.exists()


def test_failed_plugin_registration_does_not_block_later_plugin(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "bad.py",
        """
class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("leak", lambda argv: 0)
        raise RuntimeError("boom")
""",
    )
    _write_plugin(
        user_dir / "good.py",
        """
class GoodPlugin:
    name = "good"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("goodcmd", lambda argv: 0)
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")
    manager.enable_plugin("good")

    manager.discover_and_load()

    assert manager.has_command("leak") is False
    assert manager.has_command("goodcmd") is True


def test_duplicate_commit_failure_discards_partial_bundle(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "a_good.py",
        """
class GoodPlugin:
    name = "a_good"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("taken", lambda argv: 0)
""",
    )
    _write_plugin(
        user_dir / "bad.py",
        """
class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("leak", lambda argv: 0)
        api.register_command("taken", lambda argv: 0)
""",
    )
    manager = PluginManager(builtin_names=frozenset(), user_plugin_dir=user_dir)
    manager.enable_plugin("a_good")
    manager.enable_plugin("bad")

    manager.discover_and_load()

    assert manager.has_command("taken") is True
    assert manager.has_command("leak") is False
    assert manager.command_names() == ("taken",)


def test_command_override_failure_discards_partial_bundle(tmp_path: Path) -> None:
    user_dir = tmp_path / "plugins"
    user_dir.mkdir()
    _write_plugin(
        user_dir / "bad.py",
        """
class BadPlugin:
    name = "bad"
    version = "0.1.0"
    api_version = (1, 0)

    def register(self, api):
        api.register_command("leak", lambda argv: 0)
        api.register_command("cd", lambda argv: 0)
""",
    )
    manager = PluginManager(builtin_names=frozenset({"cd"}), user_plugin_dir=user_dir)
    manager.enable_plugin("bad")

    manager.discover_and_load()

    assert manager.has_command("leak") is False
    assert manager.command_names() == ()


def _write_plugin(path: Path, body: str) -> None:
    path.write_text(body.lstrip(), encoding="utf-8")
