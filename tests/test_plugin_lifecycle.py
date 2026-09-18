# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_lifecycle.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for Plugin API lifecycle hooks."""
from __future__ import annotations

from pysh.plugins.manager import PluginManager


def test_startup_shutdown_and_env_hooks_are_contained() -> None:
    events: list[tuple[str, object, object]] = []
    manager = PluginManager(builtin_names=frozenset())
    manager.register_startup_hook("plug", lambda: events.append(("start", None, None)))
    manager.register_startup_hook("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    manager.register_shutdown_hook("plug", lambda: events.append(("stop", None, None)))
    manager.register_shutdown_hook("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    manager.register_env_hook("plug", lambda name, old, new: events.append((name, old, new)))

    manager.run_startup_hooks()
    manager.notify_env_change("X", None, "1")
    manager.run_shutdown_hooks()

    assert ("start", None, None) in events
    assert ("X", None, "1") in events
    assert ("stop", None, None) in events


def test_env_hook_recursion_guard() -> None:
    manager = PluginManager(builtin_names=frozenset())
    calls: list[str] = []

    def hook(name: str, old: str | None, new: str | None) -> None:
        calls.append(name)
        manager.notify_env_change("Y", old, new)

    manager.register_env_hook("plug", hook)

    manager.notify_env_change("X", None, "1")

    assert calls == ["X"]
