# SPDX-License-Identifier: GPL-2.0-only
# File: src/pysh/plugins/api.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Public object passed to trusted PySH plugins during registration."""
from __future__ import annotations

from collections.abc import Callable

from pysh.plugins.errors import PluginRegistrationError
from pysh.plugins.models import PROMPT_POSITIONS, PluginRegistrationBundle
from pysh.plugins.names import validate_command_name, validate_segment_name


class PluginAPI:
    """Validated Plugin API 1.0 registration surface."""

    def __init__(
        self,
        manager: object,
        plugin_name: str,
        *,
        bundle: PluginRegistrationBundle,
    ) -> None:
        self._manager = manager
        self._plugin_name = plugin_name
        self._bundle = bundle

    def register_command(self, name: str, handler: Callable[[list[str]], int]) -> None:
        """Register a command handler for ``name``."""
        command_name = validate_command_name(name)
        if not callable(handler):
            raise PluginRegistrationError("command handler must be callable")
        self._manager.stage_command(self._bundle, command_name, handler)

    def register_completer(
        self,
        command_name: str,
        completer: Callable[[list[str], int], list[str]],
    ) -> None:
        """Register a command-specific completer callback."""
        name = validate_command_name(command_name)
        if not callable(completer):
            raise PluginRegistrationError("completer must be callable")
        self._manager.stage_completer(self._bundle, name, completer)

    def register_prompt_segment(
        self,
        name: str,
        renderer: Callable[[], str | None],
        *,
        position: str = "end",
    ) -> None:
        """Register a prompt segment renderer."""
        segment_name = validate_segment_name(name)
        if position not in PROMPT_POSITIONS:
            allowed = ", ".join(sorted(PROMPT_POSITIONS))
            raise PluginRegistrationError(f"prompt segment position must be one of: {allowed}")
        if not callable(renderer):
            raise PluginRegistrationError("prompt segment renderer must be callable")
        self._manager.stage_prompt_segment(self._bundle, segment_name, renderer, position)

    def on_startup(self, callback: Callable[[], None]) -> None:
        """Register a startup hook."""
        if not callable(callback):
            raise PluginRegistrationError("startup hook must be callable")
        self._manager.stage_startup_hook(self._bundle, callback)

    def on_shutdown(self, callback: Callable[[], None]) -> None:
        """Register a shutdown hook."""
        if not callable(callback):
            raise PluginRegistrationError("shutdown hook must be callable")
        self._manager.stage_shutdown_hook(self._bundle, callback)

    def on_env_change(
        self,
        callback: Callable[[str, str | None, str | None], None],
    ) -> None:
        """Register an environment-change hook."""
        if not callable(callback):
            raise PluginRegistrationError("environment hook must be callable")
        self._manager.stage_env_hook(self._bundle, callback)
