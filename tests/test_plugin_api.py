# SPDX-License-Identifier: GPL-2.0-only
# File: tests/test_plugin_api.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Tests for the Plugin API registration surface."""
from __future__ import annotations

import pytest

from pysh.plugins.api import PluginAPI
from pysh.plugins.errors import PluginRegistrationError, PluginValidationError
from pysh.plugins.manager import PluginManager


def test_api_registers_command_completer_prompt_and_hooks() -> None:
    manager = PluginManager(builtin_names=frozenset())
    bundle = manager.begin_registration("plug")
    api = PluginAPI(manager, "plug", bundle=bundle)

    api.register_command("hello", lambda argv: 0)
    api.register_completer("hello", lambda args, cursor: ["world"])
    api.register_prompt_segment("seg", lambda: "SEG", position="end")
    api.on_startup(lambda: None)
    api.on_shutdown(lambda: None)
    api.on_env_change(lambda name, old, new: None)

    assert not manager.has_command("hello")
    manager.commit_registration_bundle(bundle)

    assert manager.has_command("hello")
    assert manager.complete_command("hello", [], 0) == ["world"]
    assert manager.prompt_segments("end") == ["SEG"]


def test_api_requires_registration_bundle() -> None:
    manager = PluginManager(builtin_names=frozenset())

    with pytest.raises(TypeError):
        PluginAPI(manager, "plug")  # type: ignore[call-arg]


def test_api_rejects_builtin_override() -> None:
    manager = PluginManager(builtin_names=frozenset({"cd"}))
    bundle = manager.begin_registration("plug")
    api = PluginAPI(manager, "plug", bundle=bundle)

    with pytest.raises(PluginRegistrationError):
        api.register_command("cd", lambda argv: 0)


def test_api_rejects_duplicate_command() -> None:
    manager = PluginManager(builtin_names=frozenset())
    bundle = manager.begin_registration("plug")
    api = PluginAPI(manager, "plug", bundle=bundle)
    api.register_command("hello", lambda argv: 0)

    with pytest.raises(PluginRegistrationError):
        api.register_command("hello", lambda argv: 0)


def test_api_rejects_invalid_prompt_position() -> None:
    manager = PluginManager(builtin_names=frozenset())
    bundle = manager.begin_registration("plug")
    api = PluginAPI(manager, "plug", bundle=bundle)

    with pytest.raises(PluginRegistrationError):
        api.register_prompt_segment("seg", lambda: "x", position="middle")


def test_api_rejects_invalid_names() -> None:
    manager = PluginManager(builtin_names=frozenset())
    bundle = manager.begin_registration("plug")
    api = PluginAPI(manager, "plug", bundle=bundle)

    with pytest.raises(PluginValidationError):
        api.register_command("bad/name", lambda argv: 0)
